import re
from typing import Any, List
import logging

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
    message = TextMessage(to=recipient, text={"body": text})
    return message.model_dump_json()


def get_interactive_button_input(recipient: str, text: str, options: List[str]) -> str:
    buttons = [
        Button(type="reply", reply=Reply(id=f"option-{i}", title=opt))
        for i, opt in enumerate(options)
    ]

    interactive_button = InteractiveButton(
        body=TextObject(text=text),
        footer=TextObject(text="This is an automatic message 🦒"),
        action=ButtonsAction(buttons=buttons),
    )

    message = InteractiveMessage(to=recipient, interactive=interactive_button)

    return message.model_dump_json()


def get_interactive_list_input(
    recipient: str, text: str, options: List[str], title: str = "Options"
) -> str:
    rows = [Row(id=f"option-{i}", title=opt) for i, opt in enumerate(options)]

    section = Section(title=title, rows=rows)

    interactive_list = InteractiveList(
        body=TextObject(text=text),
        footer=TextObject(text="This is an automated message 🦒"),
        action=ListAction(
            button="Options", sections=[section]  # List containing the section
        ),
    )

    message = InteractiveMessage(to=recipient, interactive=interactive_list)

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

    return text


def is_valid_whatsapp_message(body: Any) -> bool:
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
