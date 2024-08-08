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
from app.services.whatsapp_service import whatsapp_client
from app.services.onboarding_service import handle_onboarding
from app.services.openai_service import llm_client
from db.utils import get_user_state, is_rate_limit_reached, store_message

logger = logging.getLogger(__name__)


async def handle_request(request: Request) -> JSONResponse:
    """
    Handles HTTP requests to this webhook for message, sent, delivered, and read events.
    """
    body = await request.json()

    # Check if it's a WhatsApp status update (sent, delivered, read)
    if is_status_update(body):
        return whatsapp_client.handle_status_update(body)

    # Process non-status updates (message, other)
    try:
        if not is_valid_whatsapp_message(body):
            return JSONResponse(
                content={"status": "error", "message": "Not a WhatsApp API event"},
                status_code=404,
            )

        message_info = extract_message_info(body)
        wa_id = message_info["wa_id"]
        message = message_info["message"]
        timestamp = message_info["timestamp"]
        name = message_info["name"]

        # TODO: Figure out a better way to handle rate limiting and what to do with older messages
        if is_message_recent(timestamp):
            if is_rate_limit_reached(wa_id):
                return await whatsapp_client.handle_rate_limit(wa_id, message)

            generated_response = await process_message(wa_id, name, message, timestamp)
            await whatsapp_client.send_message(generated_response)
            return JSONResponse(content={"status": "ok"}, status_code=200)
        else:
            store_message(wa_id, message, role="user")
            logger.warning("Received a message with an outdated timestamp.")
            return JSONResponse(content={"status": "ok"}, status_code=200)
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON")
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON provided"},
            status_code=400,
        )


async def process_message(
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

    try:
        message_body = extract_message_body(message)
    except ValueError as e:
        logger.error(str(e))
        return None

    store_message(wa_id, message_body, role="user")

    # Retrieve the user's current state
    state = get_user_state(wa_id)

    if state.get("state") != "completed":
        data = handle_onboarding_flow(wa_id, message_body)
    else:
        data = await handle_twiga_integration(wa_id, name, message_body)

    return data


async def handle_twiga_integration(
    wa_id: str, name: str, message_body: str
) -> Optional[str]:

    response_text = await llm_client.generate_response(message_body, wa_id, name)
    if response_text is None:
        logger.info("No response generated, user will not be contacted.")
        return None

    store_message(wa_id, response_text, role="twiga")
    return get_text_payload(wa_id, response_text)


def handle_onboarding_flow(wa_id: str, message_body: str) -> str:
    response_text, options = handle_onboarding(wa_id, message_body)
    return generate_payload(wa_id, response_text, options)
