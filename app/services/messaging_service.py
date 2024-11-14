import json
import logging
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import (
    Message,
    MessageRole,
    User,
    UserState,
)
from app.utils.whatsapp_utils import (
    RequestType,
    ValidMessageType,
    extract_message,
    extract_message_info,
    get_request_type,
    get_valid_message_type,
)
from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.flow_service import flow_client
from app.services.state_service import state_client
import app.database.db as db
from app.config import settings
from app.utils.string_manager import strings, StringCategory

logger = logging.getLogger(__name__)


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to this webhook for message, sent, delivered, and read events.
    Includes user management with database integration.
    """
    try:
        body = await request.json()
        request_type = get_request_type(body)
        logger.info(f"Received a request of type: {request_type}")

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
            case RequestType.VALID_MESSAGE:
                return await handle_valid_message(body)

        raise Exception(f"Invalid request type. This is the request body: {body}")
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


async def handle_valid_message(body: dict) -> JSONResponse:
    # Extract message information and create/get user
    message_info = extract_message_info(body)
    message = extract_message(message_info.get("message", {}))
    user = await db.get_or_create_user(
        wa_id=message_info.get("wa_id"), name=message_info.get("name")
    )

    # Create message record
    user_message = await db.create_new_message(
        Message(user_id=user.id, role=MessageRole.user, content=message)
    )

    logger.debug(f"Processing message for user {user.wa_id} in state {user.state}")

    match user.state:
        case UserState.blocked:
            return await state_client.handle_blocked(user)
        case UserState.rate_limited:
            return await state_client.handle_rate_limited(user)
        case UserState.onboarding:
            return await state_client.handle_onboarding(user)
        case UserState.new:
            # Dummy data for development environment if not using Flows
            logger.debug("Handling new user")
            if not settings.business_env:
                logger.debug("Business environment is False")
                logger.debug("Adding dummy data for new user")
                return await state_client.handle_new_dummy(user)
            return await state_client.handle_onboarding(user)
        case UserState.active:
            message_type = get_valid_message_type(message_info)
            match message_type:
                case ValidMessageType.SETTINGS_FLOW_SELECTION:
                    return await handle_settings_selection(user, user_message)
                case ValidMessageType.COMMAND:
                    return await handle_command_message(user, user_message)
                case ValidMessageType.CHAT:
                    return await handle_chat_message(user, user_message)

    raise Exception("Invalid user state, reached the end of handle_valid_message")


async def handle_settings_selection(user: User, message: Message) -> JSONResponse:
    logger.debug(f"Handling interactive message with title: {message.content}")
    if message.content == "Personal Info":
        logger.debug("Sending update personal and school info flow")
        await flow_client.send_personal_and_school_info_flow(user, is_update=True)
    elif message.content == "Class and Subject":
        logger.debug("Sending update class and subject info flow")
        await flow_client.send_select_subject_flow(user, is_update=True)
    else:
        raise Exception(f"Unrecognized user reply: {message.content}")
    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


async def handle_command_message(user: User, message: Message) -> JSONResponse:  # type: ignore
    logger.debug(f"Handling command message: {message.content}")
    if message.content.lower() == "settings":
        response_text = strings.get_string(StringCategory.SETTINGS, "intro")
        options = [
            strings.get_string(StringCategory.SETTINGS, "personal_info"),
            strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
        ]
        await whatsapp_client.send_message(user.wa_id, response_text, options)
    elif message.content.lower() == "help":
        response_text = strings.get_string(StringCategory.INFO, "help")
        await whatsapp_client.send_message(user.wa_id, response_text)
    else:
        response_text = strings.get_string(StringCategory.ERROR, "command_not_found")
        await whatsapp_client.send_message(user.wa_id, response_text)
    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


async def handle_chat_message(user: User, user_message: Message) -> JSONResponse:
    available_user_resources = await db.get_user_resources(user)
    llm_responses = await llm_client.generate_response(
        user=user, message=user_message, resources=available_user_resources
    )
    if llm_responses:
        logger.debug(f"Sending message to {user.wa_id}: {llm_responses[-1].content}")

        # Update the database with the responses
        llm_responses = await db.create_new_messages(llm_responses)

        # Send the last message back to the user
        await whatsapp_client.send_message(user.wa_id, llm_responses[-1].content)
    else:
        logger.error("No responses generated by LLM")
        err_message = strings.get_string(StringCategory.ERROR, "general")
        await whatsapp_client.send_message(user.wa_id, err_message)

    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )
