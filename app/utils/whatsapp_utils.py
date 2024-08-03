import json
import re
from typing import Any
import logging

from app.services.onboarding_service import handle_onboarding
from app.services.openai_service import generate_response
from db.utils import store_message, get_user_state
from app.config import settings

logger = logging.getLogger(__name__)


def get_text_message_input(recipient, text) -> str:
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }
    )


def get_interactive_message_input(recipient, text, options) -> str:
    buttons = [
        {
            "type": "reply",
            "reply": {"id": f"option-{i}", "title": opt},
        }
        for i, opt in enumerate(options)
    ]

    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "footer": {"text": "Twiga 🦒"},
                "action": {"buttons": buttons},
            },
        }
    )


def get_interactive_list_message_input(recipient, text, options) -> str:

    sections = [{"id": f"option-{i}", "title": opt} for i, opt in enumerate(options)]

    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "footer": {"text": "Twiga 🦒"},
                "action": {
                    "sections": [
                        {
                            "title": "Options",
                            "rows": sections,
                        }
                    ],
                    "button": "Options",
                },
            },
        }
    )


def process_text_for_whatsapp(text: str) -> str:
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


async def process_whatsapp_message(body: Any) -> str:

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
        response = process_text_for_whatsapp(response_text)
        # This section handles the type of message to send to the user depending on the number of options available to select from
        if options:
            if len(options) <= 3:
                data = get_interactive_message_input(wa_id, response, options)
            else:
                data = get_interactive_list_message_input(wa_id, response, options)
        else:
            data = get_text_message_input(wa_id, response)
    else:  # Twiga Integration
        response_text = await generate_response(message_body, wa_id, name)
        if (
            response_text is None
        ):  # Don't send anything back to the user if we decide to ghost them
            return
        response = process_text_for_whatsapp(response_text)
        data = get_text_message_input(wa_id, response)

    store_message(wa_id, response_text, role="twiga")
    return data
    # await send_message(data)  # this is non-blocking now that it's async


def is_valid_whatsapp_message(body: Any) -> bool:
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
