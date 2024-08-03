from typing import Any, Optional
import logging

from app.services.onboarding_service import handle_onboarding
from app.services.openai_service import generate_response
from app.utils.whatsapp_utils import (
    format_text_for_whatsapp,
    get_interactive_button_payload,
    get_interactive_list_payload,
    get_text_payload,
)
from db.utils import store_message, get_user_state

logger = logging.getLogger(__name__)


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
        message_body = _extract_message_body(message)
    except ValueError as e:
        logger.error(str(e))
        return None

    store_message(wa_id, message_body, role="user")

    # Retrieve the user's current state
    state = get_user_state(wa_id)

    if state.get("state") != "completed":
        data = _handle_onboarding_flow(wa_id, message_body)
    else:
        data = await _handle_twiga_integration(wa_id, name, message_body)

    return data


async def _handle_twiga_integration(
    wa_id: str, name: str, message_body: str
) -> Optional[str]:

    response_text = await generate_response(message_body, wa_id, name)
    if response_text is None:
        logger.info("No response generated, user will not be contacted.")
        return None

    response = format_text_for_whatsapp(response_text)
    store_message(wa_id, response_text, role="twiga")
    return get_text_payload(wa_id, response)


def _extract_message_body(message: dict) -> str:
    message_type = message.get("type")
    if message_type == "text":
        return message["text"]["body"]
    elif message_type == "interactive":
        interactive_type = message["interactive"]["type"]
        if interactive_type == "button_reply":
            return message["interactive"]["button_reply"]["title"]
        elif interactive_type == "list_reply":
            return message["interactive"]["list_reply"]["title"]

    raise ValueError(f"Unsupported message type: {message_type}")


def _handle_onboarding_flow(wa_id: str, message_body: str) -> str:
    response_text, options = handle_onboarding(wa_id, message_body)
    response = format_text_for_whatsapp(response_text)
    return _generate_payload(wa_id, response, options)


def _generate_payload(wa_id: str, response: str, options: Optional[list]) -> str:
    if options:
        if len(options) <= 3:
            return get_interactive_button_payload(wa_id, response, options)
        else:
            return get_interactive_list_payload(wa_id, response, options)
    else:
        return get_text_payload(wa_id, response)
