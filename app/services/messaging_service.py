import json
import logging
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database.models import MessageRole, User, UserState
from app.utils.whatsapp_utils import (
    extract_message_body,
    extract_message_info,
    generate_payload,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_valid_whatsapp_message,
)

from app.services.whatsapp_service import whatsapp_client
from app.services.llm_service import llm_client
from app.services.state_service import state_client
from app.services.onboarding_service import onboarding_client
import app.database.db as db

logger = logging.getLogger(__name__)


# TODO: make this function less complex
async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to this webhook for message, sent, delivered, and read events.
    Includes user management with database integration.
    """
    try:
        body = await request.json()

        # Check if it's a WhatsApp status update (sent, delivered, read)
        if is_status_update(body):
            return whatsapp_client.handle_status_update(body)

        # Process non-status updates (message, other)
        if not is_valid_whatsapp_message(body):
            return JSONResponse(
                content={"status": "error", "message": "Not a WhatsApp API event"},
                status_code=404,
            )

        # Extract message info (NOTE: the message format might look different in flow responses)
        message_info = extract_message_info(body)

        # Get or create user
        user = await db.get_or_create_user(
            wa_id=message_info["wa_id"], name=message_info["name"]
        )

        request_message = extract_message_body(message_info["message"])

        # Upload the message to the database
        user_message = await db.create_new_message(
            user_id=user.id,
            content=request_message,
            role=MessageRole.user,
        )

        # Handle state using the State Service
        response_text, options = state_client.process_state(user)

        if response_text is not None:
            # In this scenario the user is in a state that had a predefined response
            payload = generate_payload(user.wa_id, response_text, options)
            await whatsapp_client.send_message(payload)

            # Store the bot response in the database
            await db.create_new_message(
                user_id=user.id, content=response_text, role=MessageRole.assistant
            )
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )
        elif (
            is_message_recent(message_info["timestamp"])  # might do this elsewhere
            and user.state == UserState.active
        ):
            # In this scenario the user is active so they are directed to the LLM
            generated_response = await _process_message(
                user=user,
                message=user_message.content,
            )

            if generated_response:
                # Send the response back to the user
                payload = generate_payload(user.wa_id, generated_response)
                await whatsapp_client.send_message(payload)

                # Store the response message in the database
                await db.create_new_message(
                    user_id=user.id,
                    content=generated_response,
                    role=MessageRole.assistant,
                )
            return JSONResponse(content={"status": "ok"}, status_code=200)
        else:
            # TODO: Determine whether this is the right approach, if it should be handled way at the start, or not at all.
            logger.warning("Received a message with an outdated timestamp. Ignoring.")
            return JSONResponse(content={"status": "ok"}, status_code=200)

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


async def _process_message(user: User, message: str) -> Optional[str]:
    data = await _handle_llm(user, message)
    return data


async def _handle_llm(user: User, message_body: str) -> Optional[str]:

    response_text = await llm_client.generate_response(
        user=user, message=message_body, verbose=True
    )

    if response_text is None:
        logger.warning(f"No response received for message: {message_body}")
        return None

    return response_text


def _handle_testing(wa_id: str, message_body: str) -> Optional[str]:
    return get_text_payload(wa_id, message_body.upper())
