from datetime import datetime
import json
import re
from typing import Any, List, Literal, Optional
import logging

import httpx

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
from app.utils.logging_utils import log_httpx_response
from app.config import settings


logger = logging.getLogger(__name__)


def get_text_payload(recipient: str, text: str) -> str:
    payload = TextMessage(to=recipient, text={"body": _format_text_for_whatsapp(text)})
    return payload.model_dump_json()


def get_interactive_button_payload(
    recipient: str, text: str, options: List[str]
) -> str:
    buttons = [
        Button(
            type="reply",
            reply=Reply(id=f"option-{i}", title=opt),
        )
        for i, opt in enumerate(options)
    ]

    interactive_button = InteractiveButton(
        body=TextObject(text=_format_text_for_whatsapp(text)),
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
        body=TextObject(text=_format_text_for_whatsapp(text)),
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


def _format_text_for_whatsapp(text: str) -> str:
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


def is_whatsapp_user_message(body: Any) -> bool:
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )


def is_flow_complete_message(body: Any) -> bool:
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0].get("interactive")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"].get(
            "type"
        )
        == "nfm_reply"
        and body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"].get(
            "nfm_reply"
        )
        and body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"][
            "nfm_reply"
        ].get("response_json")
        and "flow_token"
        in body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"][
            "nfm_reply"
        ]["response_json"]
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


def extract_message_body(message: dict) -> str:
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


# def generate_payload(wa_id: str, response: str, options: Optional[list]) -> str:
#     if options:
#         if len(options) <= 3:
#             return get_interactive_button_payload(wa_id, response, options)
#         else:
#             return get_interactive_list_payload(wa_id, response, options)
#     else:
#         return get_text_payload(wa_id, response)


def generate_payload(
    wa_id: str,
    response: str,
    options: Optional[list] = None,
    flow: Optional[dict] = None,
) -> str:
    if flow:
        return get_flow_payload(wa_id, flow)
    elif options:
        if len(options) <= 3:
            return get_interactive_button_payload(wa_id, response, options)
        else:
            return get_interactive_list_payload(wa_id, response, options)
    else:
        return get_text_payload(wa_id, response)


def get_flow_payload(wa_id: str, flow: dict) -> str:
    payload = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {
                "type": "text",
                "text": flow.get("header", "Flow message header"),
            },
            "body": {"text": flow.get("body", "Flow message body")},
            "footer": {"text": flow.get("footer", "Flow message footer")},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": flow.get("flow_message_version", "3"),
                    "flow_token": flow.get("flow_token", settings.flow_token),
                    "flow_name": flow.get("flow_name", "default_flow"),
                    "flow_cta": flow.get("flow_cta", "Start"),
                    "flow_action": flow.get("flow_action", "navigate"),
                    "flow_action_payload": flow.get("flow_action_payload", {}),
                },
            },
        },
    }
    return json.dumps(payload)
