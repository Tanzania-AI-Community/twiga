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
from app.config import Environment, settings
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

    message = extract_message(message_info.get("message") or {})

    if not message:
        logger.warning("Empty message received")
        return JSONResponse(
            content={"status": "error", "message": "Invalid message"},
            status_code=400,
        )

    # Create or get the user from the database
    user = await db.get_or_create_user(
        wa_id=message_info["wa_id"], name=message_info.get("name")
    )

    assert user.id is not None

    # First, check if user is rate_limited and reset if TTL expired
    user = await state_client.check_and_reset_rate_limit_state(user)

    # Check rate limiting and update state if needed (only for non-new users to avoid double processing)
    is_rate_limited, user = await state_client.check_rate_limit_and_update_state(
        user, message_info["wa_id"]
    )
    if is_rate_limited:
        logger.info(f"User {user.wa_id} is rate limited, handling appropriately")
        return await state_client.handle_rate_limited(user)

    logger.debug(f"Processing message from user {user.wa_id} in state {user.state}.")

    match user.state:
        case enums.UserState.blocked:
            return await state_client.handle_blocked(user)
        case enums.UserState.rate_limited:
            return await state_client.handle_rate_limited(user)
        case enums.UserState.in_review:
            logger.info(f"User {user.wa_id} is under review.")

            review_message = strings.get_string(
                StringCategory.ONBOARDING, "in_review_message"
            )
            await whatsapp_client.send_message(user.wa_id, review_message)
            assert user.id is not None  # Type checker safety
            await db.create_new_message(
                models.Message(
                    user_id=user.id,
                    role=enums.MessageRole.assistant,
                    content=review_message,
                )
            )

            return JSONResponse(content={"status": "ok"}, status_code=200)

        case enums.UserState.inactive:
            # Don't respond to inactive users
            logger.info(f"User {user.wa_id} is inactive, not responding")
            return JSONResponse(content={"status": "ok"}, status_code=200)
        case enums.UserState.onboarding:
            # Create message record for onboarding users
            assert user.id is not None
            user_message = await db.create_new_message(
                models.Message(
                    user_id=user.id, role=enums.MessageRole.user, content=message
                )
            )
            return await state_client.handle_onboarding(user)
        case enums.UserState.new:
            # Check if this is a development environment
            if settings.environment not in (
                Environment.PRODUCTION,
                Environment.STAGING,
                Environment.DEVELOPMENT,
            ):
                # Development environment - create dummy data and mark as active
                logger.debug(
                    "Development environment detected with new user, adding dummy data"
                )
                return await handle_new_dummy(user)
            else:
                # Production environment - user has been approved by admin, send welcome message
                logger.info(
                    f"Approved user {user.wa_id} is texting, sending welcome template message"
                )

                # Send welcome template message
                await whatsapp_client.send_template_message(
                    user.wa_id, settings.welcome_template_id
                )

                # Update user state to onboarding
                user.state = enums.UserState.onboarding
                user.onboarding_state = enums.OnboardingState.new
                await db.update_user(user)
                logger.info(f"Updated user {user.wa_id} state from new to onboarding")

                return JSONResponse(content={"status": "ok"}, status_code=200)
        case enums.UserState.active:
            # Create message record for active users
            assert user.id is not None
            user_message = await db.create_new_message(
                models.Message(
                    user_id=user.id, role=enums.MessageRole.user, content=message
                )
            )
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
