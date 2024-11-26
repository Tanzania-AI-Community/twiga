import json
import logging
from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.database.models import (
    ClassInfo,
    Message,
    User,
    UserState,
)
from app.database.enums import (
    GradeLevel,
    MessageRole,
    OnboardingState,
    Role,
    SubjectNames,
)
from app.utils.whatsapp_utils import (
    RequestType,
    extract_message,
    extract_message_info,
    get_request_type,
)
from app.services.whatsapp_service import whatsapp_client
from app.services.state_service import state_client
import app.database.db as db
from app.config import settings
from app.utils.string_manager import strings, StringCategory
import app.utils.flow_utils as futil
from app.services.flow_service import flow_client

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


async def handle_flows_request(
    request: Request, bg_tasks: BackgroundTasks
) -> PlainTextResponse:
    try:
        body = await request.json()
        decrypted_data = futil.decrypt_flow_webhook(body)
        logger.info(f"Decrypted data: {decrypted_data}")
        decrypted_payload = decrypted_data["decrypted_payload"]
        aes_key = decrypted_data["aes_key"]
        initial_vector = decrypted_data["initial_vector"]
        action = decrypted_payload.get("action")
    except ValueError as e:
        logger.error(f"Error decrypting payload: {e}")
        return PlainTextResponse(content="Decryption failed", status_code=421)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return PlainTextResponse(content="Decryption failed", status_code=500)

    logger.info(f"Flow Webhook Decrypted payload: {decrypted_payload}")

    if action == "ping":
        logger.info("Received ping action")
        return await flow_client.handle_health_check(
            decrypted_payload, aes_key, initial_vector
        )

    flow_token = decrypted_payload.get("flow_token")
    if not flow_token:
        logger.error("Missing flow token")
        return JSONResponse(
            content={"error_msg": "Missing flow token, Unable to process request"},
            status_code=422,
        )

    try:
        _, flow_id = futil.decrypt_flow_token(flow_token)
        logger.info(f"Flow Action: {action}, Flow ID: {flow_id}")
    except Exception as e:
        logger.error(f"Error decrypting flow token: {e}")
        return JSONResponse(
            content={"error_msg": "Your request has expired please start again"},
            status_code=422,
        )

    handler = flow_client.get_action_handler(action, flow_id)
    # Check if the action is a data exchange action and handle accordingly
    if action in ["data_exchange", "INIT"]:
        if action == "data_exchange":
            return await handler(decrypted_payload, aes_key, initial_vector, bg_tasks)
        else:
            return await handler(decrypted_payload, aes_key, initial_vector)
    else:
        return await handler(decrypted_payload, aes_key, initial_vector)


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
            if not settings.business_env:
                logger.debug(
                    "Business environment is False, adding dummy data for new user"
                )
                return await handle_new_dummy(user)
            return await state_client.handle_onboarding(user)
        case UserState.active:
            return await state_client.handle_active(user, message_info, user_message)

    raise Exception("Invalid user state, reached the end of handle_valid_message")


async def handle_new_dummy(user: User) -> JSONResponse:
    try:
        # Update the user object with dummy data
        user.state = UserState.active
        user.onboarding_state = OnboardingState.completed
        user.role = Role.teacher
        user.class_info = ClassInfo(
            subjects={
                SubjectNames.geography: [
                    GradeLevel.os2
                ]  # Using GradeLevel.os2 for Secondary Form 2
            }
        ).model_dump()

        # Read the class IDs from the class info
        class_ids = await db.get_class_ids_from_class_info(user.class_info)

        # Update user and create teachers_classes entries
        user = await db.update_user(user)
        await db.assign_teacher_to_classes(user, class_ids)

        # Send a welcome message to the user
        response_text = strings.get_string(
            StringCategory.ONBOARDING, "onboarding_override"
        )
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        logger.warning(f"Dummy {user.wa_id} created with the data: {user}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )
    except Exception as e:
        logger.error(f"Error while handling new dummy user: {e}")
        return JSONResponse(
            content={"status": "error"},
            status_code=500,
        )