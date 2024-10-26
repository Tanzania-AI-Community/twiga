import json
import logging
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse

from app.utils.whatsapp_utils import (
    extract_message_body,
    extract_message_info,
    generate_payload,
    get_text_payload,
    is_message_recent,
    is_status_update,
    is_valid_whatsapp_message,
)

from db.utils import AppDatabase
from app.services.whatsapp_service import whatsapp_client
from app.services.openai_service import llm_client
from app.services.state_service import state_client
from app.services.onboarding_service import onboarding_client
from app.database.db import get_or_create_user

logger = logging.getLogger(__name__)


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
        # Validate WhatsApp message
        if not is_valid_whatsapp_message(body):
            return JSONResponse(
                content={"status": "error", "message": "Not a WhatsApp API event"},
                status_code=404,
            )

        # Extract message info
        message_info = extract_message_info(body)

        # Get or create user
        user = await get_or_create_user(
            wa_id=message_info["wa_id"], name=message_info["name"]
        )
        # TODO: Figure out a better way to handle rate limiting and what to do with older messages

        # Handle state using the State Service
        response_text, options = state_client.process_state(
            user, message_info["message"]
        )

        if response_text:
            return JSONResponse(
                content=generate_payload(user.wa_id, response_text, options),
                status_code=200,
            )

        # Handle Onboarding Using the Onboarding Service
        response_text, options = onboarding_client.process_state(
            user, message_info["message"]
        )
        if response_text : 
            return JSONResponse(
            content=generate_payload(user.wa_id, response_text, options),
            status_code=200,
        )

        try:

            generated_response = await _process_message(
                wa_id=user.wa_id,
                name=user.name,
                message=message_info["message"],
                timestamp=message_info["timestamp"],
            )

            await whatsapp_client.send_message(generated_response)
            return JSONResponse(content={"status": "ok"}, status_code=200)
            # if is_message_recent(timestamp):
            #     if db.is_rate_limit_reached(wa_id):
            #         return await _handle_rate_limit(wa_id, message)

            #     generated_response = await _process_message(wa_id, name, message, timestamp)
            #     await whatsapp_client.send_message(generated_response)
            #     return JSONResponse(content={"status": "ok"}, status_code=200)
            # else:
            #     db.store_message(wa_id, message, role="user")
            #     logger.warning("Received a message with an outdated timestamp.")
            #     return JSONResponse(content={"status": "ok"}, status_code=200)
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            return JSONResponse(
                content={"status": "error", "message": "Failed to process message"},
                status_code=500,
            )
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

async def _process_message(
    wa_id: str, name: str, message: dict, timestamp: int
) -> Optional[str]:
    """
    Process an incoming WhatsApp message and generate a response.

    Args:
        wa_id (str): WhatsApp ID of the user (phone number).
        name (str): Name of the user.
        message (dict): Message content received from WhatsApp.
        timestamp (int): Timestamp of the message.

    Returns:
        Optional[str]: JSON payload to send back to WhatsApp, or None if no response is required.
    """
    db = AppDatabase()

    try:
        message_body = extract_message_body(message)
    except ValueError as e:
        logger.error(str(e))
        return None

    db.store_message(wa_id, message_body, role="user")

    # Retrieve the user's current state
    state = db.get_user_state(wa_id)

    # NOTE: this is a temporary integration for testing purposes
    data = _handle_testing(wa_id, message_body)
    # if state.get("state") != "completed":
    #     data = _handle_onboarding_flow(wa_id, message_body)
    # else:
    #     data = await _handle_twiga_integration(wa_id, name, message_body)

    return data


def _handle_testing(wa_id: str, message_body: str) -> Optional[str]:
    return get_text_payload(wa_id, message_body.upper())


async def _handle_twiga_integration(
    wa_id: str, name: str, message_body: str
) -> Optional[str]:

    db = AppDatabase()

    response_text = await llm_client.generate_response(message_body, wa_id, name)
    if response_text is None:
        logger.info("No response generated, user will not be contacted.")
        return None

    db.store_message(wa_id, response_text, role="twiga")
    return get_text_payload(wa_id, response_text)


def _handle_onboarding_flow(wa_id: str, message_body: str) -> str:
    response_text, options = onboarding_client.process_state(wa_id, message_body)
    return generate_payload(wa_id, response_text, options)


async def _handle_rate_limit(wa_id: str, message: dict) -> JSONResponse:
    db = AppDatabase()
    # TODO: This is a good place to use a template instead of hardcoding the message
    logger.warning("Message limit reached for wa_id: %s", wa_id)
    sleepy_text = (
        "🚫 You have reached your daily messaging limit, so Twiga 🦒 is quite sleepy 🥱 "
        "from all of today's texting. Let's talk more tomorrow!"
    )
    data = get_text_payload(wa_id, sleepy_text)
    db.store_message(wa_id, message, role="user")
    await whatsapp_client.send_message(data)
    return JSONResponse(content={"status": "ok"}, status_code=200)
