import json
import logging
from fastapi import Request
from fastapi.responses import JSONResponse

import app.database.models as models
import app.database.enums as enums
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

logger = logging.getLogger(__name__)


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to the 'webhooks' and 'flows' endpoints.
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
    message = extract_message(message_info.get("message", None))

    if not message:
        logger.warning("Empty message received")
        return JSONResponse(
            content={"status": "error", "message": "Invalid message"},
            status_code=400,
        )

    user = await db.get_or_create_user(
        wa_id=message_info["wa_id"], name=message_info.get("name")
    )

    assert user.id is not None
    # Create message record
    user_message = await db.create_new_message(
        models.Message(user_id=user.id, role=enums.MessageRole.user, content=message)
    )

    logger.debug(f"Processing message from user {user.wa_id} in state {user.state}.")

    match user.state:
        case enums.UserState.blocked:
            return await state_client.handle_blocked(user)
        case enums.UserState.rate_limited:
            return await state_client.handle_rate_limited(user)
        case enums.UserState.onboarding:
            return await state_client.handle_onboarding(user)
        case enums.UserState.new:
            # Dummy data for development environment if not using Flows
            if not settings.business_env:
                logger.debug(
                    "Business environment is False, adding dummy data for new user"
                )
                return await handle_new_dummy(user)
            return await state_client.handle_onboarding(user)
        case enums.UserState.active:
            return await state_client.handle_active(user, message_info, user_message)

    raise Exception("Invalid user state, reached the end of handle_valid_message")


async def handle_new_dummy(user: models.User) -> JSONResponse:
    try:
        # Update the user object with dummy data
        user.state = enums.UserState.active
        user.onboarding_state = enums.OnboardingState.completed
        user.role = enums.Role.teacher
        user.class_info = models.ClassInfo(
            classes={enums.SubjectName.geography: [enums.GradeLevel.os2]}
        ).model_dump()

        # Read the class IDs from the class info
        class_ids = await db.get_class_ids_from_class_info(user.class_info)

        assert class_ids is not None

        # Update user and create teachers_classes entries
        user = await db.update_user(user)
        assert user.id is not None
        await db.assign_teacher_to_classes(user, class_ids)

        # Send a welcome message to the user
        response_text = strings.get_string(
            StringCategory.ONBOARDING, "onboarding_override"
        )
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            models.Message(
                user_id=user.id,
                role=enums.MessageRole.assistant,
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
