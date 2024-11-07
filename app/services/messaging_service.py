from enum import Enum, auto
import json
import logging
from typing import List, Literal, Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import (
    ClassInfo,
    GradeLevel,
    Message,
    MessageRole,
    Role,
    Subject,
    User,
    UserState,
)
from app.utils.whatsapp_utils import (
    extract_message,
    extract_message_info,
    generate_payload,
    is_flow_event,
    is_invalid_whatsapp_message,
    is_message_outdated,
    is_status_update,
    is_flow_complete_message,
    is_interactive_message,
    is_command_message,
)

from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.flow_service import flow_client
from app.services.state_service import state_client
from app.services.onboarding_service import onboarding_client
import app.database.db as db
from app.config import settings

logger = logging.getLogger(__name__)


class RequestType(Enum):
    # Auto just assigns an incremental int to each num
    FLOW_EVENT = auto()
    MESSAGE_STATUS_UPDATE = auto()
    FLOW_COMPLETE = auto()
    INVALID_MESSAGE = auto()
    OUTDATED = auto()
    SETTINGS_FLOW_SELECTION = auto()
    COMMAND = auto()
    VALID_MESSAGE = auto()


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to this webhook for message, sent, delivered, and read events.
    Includes user management with database integration.
    """
    try:
        body = await request.json()
        logger.debug(f"Received message on webhook: {body}")

        request_type = await get_request_type(body)
        logger.debug(f"Request type: {request_type}")

        # Route the basic and stateless request types
        match request_type:
            case RequestType.FLOW_EVENT:
                return whatsapp_client.handle_flow_event(body)
            case RequestType.MESSAGE_STATUS_UPDATE:
                return whatsapp_client.handle_status_update(body)
            case RequestType.FLOW_COMPLETE:
                return whatsapp_client.handle_flow_message_complete(body)
            case RequestType.INVALID_MESSAGE:
                return whatsapp_client.handle_invalid_message(body)
            case RequestType.OUTDATED:
                return whatsapp_client.handle_outdated_message(body)
            case _:  # Valid message, continue.
                pass

        # Extract information from the message
        message_info = extract_message_info(body)
        message = extract_message(message_info.get("message", {}))
        user = await db.get_or_create_user(
            wa_id=message_info["wa_id"], name=message_info["name"]
        )

        # Store the user message in the database
        user_message = await db.create_new_message(
            Message(user_id=user.id, role=MessageRole.user, content=message)
        )

        logger.debug(
            f"Processing state for user {user.name} with wa_id {user.wa_id} and user state {user.state}"
        )

        match user.state:
            case UserState.blocked:
                return await state_client.handle_blocked()
            case UserState.rate_limited:
                return await state_client.handle_rate_limited()
            case UserState.onboarding:
                return await state_client.handle_onboarding(user)
            case UserState.new:
                # Dummy data for development environment if not using Flows
                if not settings.business_env:
                    return await handle_new_dummy(user)
                return await state_client.handle_onboarding(user)
            case UserState.active:  # User is active
                return await handle_active_user(user, user_message, request_type)

        raise Exception("Invalid user state, reached the end of handle_request")
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON")
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON provided"},
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {str(e)}")
        return JSONResponse(
            content={"status": "error", "message": "Internal server error"},
            status_code=500,
        )


async def handle_settings_selection(user: User, message: Message) -> JSONResponse:
    try:
        # Extract the title from the message using extract_message
        logger.debug(f"Handling interactive message with title: {message.content}")

        if message.content == "Personal Info":
            logger.debug("Sending update personal and school info flow")
            await flow_client.send_update_personal_and_school_info_flow(user)
        elif message.content == "Class and Subject":
            logger.debug("Sending update class and subject info flow")
            await flow_client.send_update_class_and_subject_info_flow(user)
        else:
            raise Exception(f"Unrecognized reply: {message.content}")
            # # Technically this should never happen
            # logger.warning(f"Unrecognized reply: {message.content}")
            # response_text = "⚠️ Your reply was not recognized. Please try again."
            # await whatsapp_client.send_message(
            #     generate_payload(user.wa_id, response_text)
            # )
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Error handling the settings selection message: {e}")
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )


async def handle_command_message(user: User, message: Message) -> JSONResponse:  # type: ignore
    logger.debug(f"Handling command message: {message.content}")
    try:
        if message.content == "settings":
            response_text = (
                "Welcome to the Settings Menu, please select what you want to update"
            )
            options = ["Personal Info", "Class and Subject"]
            payload = generate_payload(user.wa_id, response_text, options)
            return await whatsapp_client.send_message(payload)
        else:
            response_text = "Command not recognized. Please try again."
            await whatsapp_client.send_message(
                generate_payload(user.wa_id, response_text)
            )

    except Exception as e:
        logger.error(f"Error handling command message: {e}")
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )


async def handle_active_user(
    user: User, user_message: Message, request_type: RequestType
) -> JSONResponse:
    # We get here if the user is active
    match request_type:
        case RequestType.SETTINGS_FLOW_SELECTION:
            return await handle_settings_selection(user, user_message)
        case RequestType.COMMAND:
            return await handle_command_message(user, user_message)
        case _:
            pass

    llm_responses = await llm_client.generate_response(user=user, message=user_message)

    if llm_responses:
        # Update the database with the responses
        llm_responses = await db.create_new_messages(llm_responses)

        # Send the last message back to the user
        logger.debug(f"Sending message to {user.wa_id}: {llm_responses[-1].content}")
        payload = generate_payload(user.wa_id, llm_responses[-1].content)
        await whatsapp_client.send_message(payload)
    else:
        logger.error("No responses generated by LLM")
        err_message = "Sorry, something went wrong on my end. Please try again later."
        payload = generate_payload(user.wa_id, err_message)
        await whatsapp_client.send_message(payload)

    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


async def handle_new_dummy(user: User) -> JSONResponse:
    # Updates user state to active and set them as a Geography Form 2 Teacher (alternatively, create custom onboarding)
    user.state = UserState.active
    user.role = Role.teacher

    # Create ClassInfo and convert to dictionary for storage
    class_info = ClassInfo(subjects={Subject.geography: [GradeLevel.os2]})
    user.class_info = class_info.model_dump()

    user = await db.update_user(user)
    logger.info(
        "User is new and in development environment. Setting user as active with dummy data."
    )
    await db.add_teacher_class(user, Subject.geography, GradeLevel.os2)
    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


async def get_request_type(body: dict) -> RequestType:
    if is_flow_event(body):  # Various standard Flow events
        return RequestType.FLOW_EVENT
    if is_status_update(body):  # WhatsApp status update (sent, delivered, read)
        return RequestType.MESSAGE_STATUS_UPDATE
    if is_flow_complete_message(body):  # Flow completion message
        return RequestType.FLOW_COMPLETE
    if is_invalid_whatsapp_message(body):  # Non-status updates (message, other)
        return RequestType.INVALID_MESSAGE

    # For valid WhatsApp messages, extract the message info
    message_info = extract_message_info(body)

    # TODO: SETTINGS_FLOW_SELECTION and COMMAND are also VALID_MESSAGE, fix logic issue
    if is_message_outdated(message_info["timestamp"]):
        return RequestType.OUTDATED
    if is_interactive_message(message_info):  # NOTE: Only settings choice interactive
        return RequestType.SETTINGS_FLOW_SELECTION
    if is_command_message(message_info):
        return RequestType.COMMAND

    return RequestType.VALID_MESSAGE
