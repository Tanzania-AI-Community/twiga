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
    # Extract message information
    message_info = extract_message_info(body)

    message = extract_message(message_info.get("message") or {})

    if not message:
        logger.warning("Empty message received")
        return JSONResponse(
            content={"status": "error", "message": "Invalid message"},
            status_code=400,
        )

    # Main message routing logic
    return await handle_chat_message(message_info["wa_id"], message_info)


async def handle_chat_message(phone_number: str, message_info: dict) -> JSONResponse:
    """Main entry point for handling all valid WhatsApp messages based on user state"""

    # Try to get existing user
    user = await db.get_user_by_waid(phone_number)

    if not user:
        # New user - start registration/onboarding flow
        return await state_client.handle_new_user_registration(
            phone_number, message_info
        )

    # Handle rate limiting
    rate_limit_response = await state_client._handle_rate_limiting(user, phone_number)
    if rate_limit_response:
        return rate_limit_response

    # Route based on user state
    match user.state:
        case enums.UserState.blocked:
            return await state_client.handle_blocked(user)
        case enums.UserState.in_review:  # Handle registered but unapproved users
            return await state_client.handle_in_review_user(user)
        case enums.UserState.approved:
            # Users approved by dashboard - send welcome message and transition to onboarding
            # Persist the triggering user message but don't process it
            assert user.id is not None
            await db.create_new_message(
                models.Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content=message_info.get("message", {})
                    .get("text", {})
                    .get("body", ""),
                )
            )

            # Send welcome message and move user to onboarding state
            welcome_response = await state_client.handle_new_approved_user(user)
            return welcome_response

        case enums.UserState.inactive:
            # Users who haven't been active - reactivate them then process normally
            reactivate_response = await state_client.handle_inactive_user(user)
            if reactivate_response.status_code != 200:
                return reactivate_response

            # User is now active, process their message normally
            # Create user message record
            assert user.id is not None
            user_message = await db.create_new_message(
                models.Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content=message_info.get("message", {})
                    .get("text", {})
                    .get("body", ""),
                )
            )
            return await state_client.handle_active(user, message_info, user_message)

        case enums.UserState.onboarding:
            # Create user message record for onboarding users
            assert user.id is not None
            user_message = await db.create_new_message(
                models.Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content=message_info.get("message", {})
                    .get("text", {})
                    .get("body", ""),
                )
            )
            return await state_client.handle_onboarding(user)

        case enums.UserState.active:
            # Create user message record
            assert user.id is not None
            user_message = await db.create_new_message(
                models.Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content=message_info.get("message", {})
                    .get("text", {})
                    .get("body", ""),
                )
            )
            return await state_client.handle_active(user, message_info, user_message)
        case _:
            logger.warning(f"Unknown user state: {user.state}")
            return JSONResponse(content={"status": "error"}, status_code=400)
