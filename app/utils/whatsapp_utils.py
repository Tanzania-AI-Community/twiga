import json
import re
from typing import Any, List
import logging

from app.services.onboarding_service import handle_onboarding
from app.services.openai_service import generate_response
from db.utils import store_message, get_user_state
from app.models.message_models import (
    Row,
    TextMessage,
    InteractiveMessage,
    InteractiveButton,
    InteractiveList,
    TextObject,
    Button,
    Reply,
    ButtonsAction,
    Section,
    ListAction,
)


logger = logging.getLogger(__name__)


def get_text_input(recipient: str, text: str) -> str:
    # Create a TextMessage instance
    message = TextMessage(to=recipient, text={"body": text})
    # Convert the Pydantic model instance to JSON
    return message.model_dump_json()


def get_interactive_button_input(recipient: str, text: str, options: List[str]) -> str:
    # Create buttons from the options
    buttons = [
        Button(type="reply", reply=Reply(id=f"option-{i}", title=opt))
        for i, opt in enumerate(options)
    ]

    # Create an InteractiveButton instance
    interactive_button = InteractiveButton(
        body=TextObject(text=text),
        footer=TextObject(text="This is an automatic message 🦒"),
        action=ButtonsAction(buttons=buttons),
    )

    # Create an InteractiveMessage instance using the InteractiveButton
    message = InteractiveMessage(to=recipient, interactive=interactive_button)

    # Convert the Pydantic model instance to JSON
    return message.model_dump_json()


def get_interactive_list_input(
    recipient: str, text: str, options: List[str], title: str = "Options"
) -> str:
    # Create rows from the options
    rows = [Row(id=f"option-{i}", title=opt) for i, opt in enumerate(options)]

    # Create a section with the rows
    section = Section(title=title, rows=rows)

    # Create an InteractiveList instance
    interactive_list = InteractiveList(
        body=TextObject(text=text),
        footer=TextObject(text="This is an automated message 🦒"),
        action=ListAction(
            button="Options", sections=[section]  # List containing the section
        ),
    )

    # Create an InteractiveMessage instance using the InteractiveList
    message = InteractiveMessage(to=recipient, interactive=interactive_list)

    # Convert the Pydantic model instance to JSON
    return message.model_dump_json()


def format_text_for_whatsapp(text: str) -> str:
    # TODO: Check bold and code block formatting
    # Bold: **text** or __text__ to *text*
    text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.*?)__", r"*\1*", text)

    # Italic: *text* or _text_ to _text_
    text = re.sub(
        r"\*(.*?)\*", r"_\1_", text
    )  # This might need adjustments for overlapping bold/italic
    text = re.sub(r"_(.*?)_", r"_\1_", text)

    # Strikethrough: ~~text~~ to ~text~
    text = re.sub(r"~~(.*?)~~", r"~\1~", text)

    # Monospace (Code Block): ```text``` to ```text```
    text = re.sub(r"```(.*?)```", r"```\1```", text, flags=re.DOTALL)

    # Bulleted List: * text or - text (No change needed, WhatsApp supports this directly)
    # Handle unordered list bullets to ensure they have a leading space
    text = re.sub(r"^\s*[*-]\s+", r"* ", text, flags=re.MULTILINE)

    # Numbered List: 1. text (No change needed, WhatsApp supports this directly)

    # Blockquotes: > text (No change needed, WhatsApp supports this directly)

    # Inline Code: `text` to `text`
    text = re.sub(r"`(.*?)`", r"`\1`", text)

    return text


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
        response = format_text_for_whatsapp(response_text)
        # This section handles the type of message to send to the user depending on the number of options available to select from
        if options:
            if len(options) <= 3:
                data = get_interactive_button_input(wa_id, response, options)
            else:
                data = get_interactive_list_input(wa_id, response, options)
        else:
            data = get_text_input(wa_id, response)
    else:  # Twiga Integration
        response_text = await generate_response(message_body, wa_id, name)
        if (
            response_text is None
        ):  # Don't send anything back to the user if we decide to ghost them
            return
        response = format_text_for_whatsapp(response_text)
        data = get_text_input(wa_id, response)

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
