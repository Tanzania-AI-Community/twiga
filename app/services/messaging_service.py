from typing import Any
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


async def process_message(body: Any) -> str:

    # A check has been made already that this is a valid WhatsApp message so no need to check again
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]

    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message_type = message.get("type")
    message_timestamp = message.get("timestamp")

    # Extract the message body
    if message_type == "text":  # If the message is a standard text message
        message_body = message["text"]["body"]
    elif (
        message_type == "interactive"
        and message["interactive"]["type"] == "button_reply"
    ):  # If the message is an interactive message with visible buttons
        message_body = message["interactive"]["button_reply"]["title"]
    elif (
        message_type == "interactive" and message["interactive"]["type"] == "list_reply"
    ):  # If the message is an interactive message with a list of options
        message_body = message["interactive"]["list_reply"]["title"]
    else:
        logger.error(f"Unsupported message type: {message_type}")
        raise Exception("Unsupported message type")

    store_message(wa_id, message_body, role="user")

    # Get the user's state from the users shelve database
    state = get_user_state(wa_id)

    # If the onboarding process is not completed, handle onboarding
    if state["state"] != "completed":
        response_text, options = handle_onboarding(wa_id, message_body)
        response = format_text_for_whatsapp(response_text)
        # This section handles the type of message to send to the user depending on the number of options available to select from
        if options:
            if len(options) <= 3:
                data = get_interactive_button_payload(wa_id, response, options)
            else:
                data = get_interactive_list_payload(wa_id, response, options)
        else:
            data = get_text_payload(wa_id, response)
    else:  # Twiga Integration
        response_text = await generate_response(message_body, wa_id, name)
        if (
            response_text is None
        ):  # Don't send anything back to the user if we decide to ghost them
            return
        response = format_text_for_whatsapp(response_text)
        data = get_text_payload(wa_id, response)

    store_message(wa_id, response_text, role="twiga")
    return data
