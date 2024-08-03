from datetime import datetime
import re
from typing import Any, List, Literal
import logging

from app.models.message_models import (
    Row,
    TemplateMessage,
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


def get_text_payload(recipient: str, text: str) -> str:
    payload = TextMessage(to=recipient, text={"body": text})
    return payload.model_dump_json()


def get_interactive_button_payload(
    recipient: str, text: str, options: List[str]
) -> str:
    buttons = [
        Button(type="reply", reply=Reply(id=f"option-{i}", title=opt))
        for i, opt in enumerate(options)
    ]

    interactive_button = InteractiveButton(
        body=TextObject(text=text),
        footer=TextObject(text="This is an automatic message 🦒"),
        action=ButtonsAction(buttons=buttons),
    )

    payload = InteractiveMessage(to=recipient, interactive=interactive_button)

    return payload.model_dump_json()


def get_interactive_list_payload(
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

    payload = InteractiveMessage(to=recipient, interactive=interactive_list)

    return payload.model_dump_json()


def get_template_payload(
    recipient: str,
    template_name: str,
    language_code: Literal["en_US", "en_GB", "en", "sw"],
) -> str:

    payload = TemplateMessage(
        to=recipient,
        template={
            "name": template_name,
            "language": {"code": language_code},
        },
    )

    return payload.model_dump_json()


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


def is_status_update(body: dict) -> bool:
    return (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ) is not None


def extract_message_info(body: dict) -> dict:
    entry = body["entry"][0]["changes"][0]["value"]
    return {
        "message": entry["messages"][0],
        "wa_id": entry["contacts"][0]["wa_id"],
        "timestamp": int(entry["messages"][0].get("timestamp")),
        "name": entry["contacts"][0]["profile"]["name"],
    }


def is_message_recent(message_timestamp: int) -> bool:
    current_timestamp = int(datetime.now().timestamp())
    return current_timestamp - message_timestamp <= 10
