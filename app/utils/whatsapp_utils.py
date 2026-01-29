from datetime import datetime
from enum import Enum, auto
import re
from typing import Any, Dict, List, Optional
import logging


from app.models.message_models import (
    Row,
    TextMessage,
    TemplateMessage,
    Template,
    TemplateLanguage,
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

from app.config import settings


class RequestType(Enum):
    FLOW_EVENT = auto()
    MESSAGE_STATUS_UPDATE = auto()
    FLOW_COMPLETE = auto()
    INVALID_MESSAGE = auto()
    OUTDATED = auto()
    VALID_MESSAGE = auto()


class ValidMessageType(Enum):
    SETTINGS_FLOW_SELECTION = auto()
    COMMAND = auto()
    CHAT = auto()
    OTHER = auto()


logger = logging.getLogger(__name__)


def get_text_payload(recipient: str, text: str) -> dict:
    payload = TextMessage(to=recipient, text={"body": _format_text_for_whatsapp(text)})
    return dict(payload)


def get_template_payload(
    recipient: str, template_name: str, language_code: str = "en"
) -> dict:
    """
    Generate payload for WhatsApp template message.
    """
    template = Template(
        name=template_name,
        language=TemplateLanguage(code=language_code),
    )
    payload = TemplateMessage(to=recipient, template=template)
    return payload.model_dump()


def generate_payload_for_image(
    wa_id: str,
    media_id: str,
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a WhatsApp Cloud API payload for an image message."""

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "image",
        "image": {"id": media_id},
    }

    if caption:
        payload["image"]["caption"] = caption

    return payload


def get_interactive_button_payload(
    recipient: str, text: str, options: List[str]
) -> dict:
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

    return payload.model_dump()


def get_interactive_list_payload(
    recipient: str, text: str, options: List[str], title: str = "Options"
) -> dict:
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

    return dict(payload)


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


def is_invalid_whatsapp_message(body: Any) -> bool:
    try:
        return not (
            body.get("object")
            and body.get("entry")
            and body["entry"][0].get("changes")
            and body["entry"][0]["changes"][0].get("value")
            and body["entry"][0]["changes"][0]["value"].get("messages")
            and body["entry"][0]["changes"][0]["value"]["messages"][0]
        )
    except (IndexError, AttributeError, TypeError) as e:
        logger.error(f"Error validating WhatsApp message: {e}")
        return True  # Return True since an error means the message is invalid


def is_flow_complete_message(body: Any) -> bool:
    try:
        return (
            body.get("object")
            and body.get("entry")
            and body["entry"][0].get("changes")
            and body["entry"][0]["changes"][0].get("value")
            and body["entry"][0]["changes"][0]["value"].get("messages")
            and body["entry"][0]["changes"][0]["value"]["messages"][0].get(
                "interactive"
            )
            and body["entry"][0]["changes"][0]["value"]["messages"][0][
                "interactive"
            ].get("type")
            == "nfm_reply"
            and body["entry"][0]["changes"][0]["value"]["messages"][0][
                "interactive"
            ].get("nfm_reply")
            and body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"][
                "nfm_reply"
            ].get("response_json")
            and "flow_token"
            in body["entry"][0]["changes"][0]["value"]["messages"][0]["interactive"][
                "nfm_reply"
            ]["response_json"]
        )
    except (IndexError, AttributeError, TypeError, KeyError) as e:
        logger.error(f"Error checking flow complete message: {e}")
        return False


def is_flow_event(body: dict) -> bool:
    try:
        return bool(
            body.get("object") == "whatsapp_business_account"
            and body.get("entry") is not None
            and body["entry"][0].get("changes") is not None
            and body["entry"][0]["changes"][0].get("value") is not None
            and body["entry"][0]["changes"][0]["value"].get("event") is not None
        )
    except (IndexError, AttributeError, TypeError) as e:
        logger.error(f"Error checking flow event: {e}")
        return False


def is_status_update(body: dict) -> bool:
    try:
        return (
            body.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
            .get("statuses")
        ) is not None
    except (IndexError, AttributeError, TypeError) as e:
        logger.error(f"Error checking status update: {e}")
        return False


def extract_message_info(body: dict) -> dict:
    # logger.debug(f"Extracting message info from body: {body}")
    entry = body["entry"][0]["changes"][0]["value"]
    return {
        "message": entry["messages"][0],
        "wa_id": entry["contacts"][0]["wa_id"],
        "timestamp": int(entry["messages"][0].get("timestamp")),
        "name": entry["contacts"][0]["profile"]["name"],
    }


def is_message_outdated(message_timestamp: int) -> bool:
    if settings.mock_whatsapp:
        return False
    current_timestamp = int(datetime.now().timestamp())
    return current_timestamp - message_timestamp >= 10


def extract_message(message: dict) -> str:
    message_type = message.get("type")
    if message_type == "text":
        return message["text"]["body"]
    elif message_type == "image":
        return message.get("image", {}).get("caption", "")
    elif message_type == "interactive":
        interactive_type = message["interactive"]["type"]
        if interactive_type == "button_reply":
            return message["interactive"]["button_reply"]["title"]
        elif interactive_type == "list_reply":
            return message["interactive"]["list_reply"]["title"]

    logger.warning(f"Unsupported message type: {message_type}")
    return "warning: user sent an unsupported message type"


def is_interactive_message(message_info: dict) -> bool:
    message = message_info.get("message", {})
    return message.get("type") == "interactive"


COMMAND_OPTIONS = ["settings", "help"]


def is_command_message(message_info: dict) -> bool:
    message = message_info.get("message", {}).get("text", {}).get("body", "")
    # logger.debug(f"Checking if message is a command: {message}")

    if isinstance(message, str):
        return message.lower() in COMMAND_OPTIONS
    return False


def generate_payload(
    wa_id: str,
    response: str,
    options: Optional[list] = None,
    flow: Optional[dict] = None,
    template_name: Optional[str] = None,
) -> dict:
    if template_name:
        return get_template_payload(wa_id, template_name)
    if flow:
        return get_flow_payload(wa_id, flow)
    if options:
        if len(options) <= 3:
            return get_interactive_button_payload(wa_id, response, options)
        else:
            return get_interactive_list_payload(wa_id, response, options)
    else:
        return get_text_payload(wa_id, response)


def get_flow_payload(wa_id: str, flow: dict) -> dict:
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
                    "flow_token": flow.get("flow_token"),
                    "flow_name": flow.get("flow_name", "default_flow"),
                    "flow_cta": flow.get("flow_cta", "Start"),
                    "flow_action": flow.get("flow_action", "navigate"),
                    "flow_action_payload": flow.get("flow_action_payload", {}),
                },
            },
        },
    }
    return payload


def is_other_message(message_info: dict) -> bool:
    return message_info.get("message", {}).get("type") not in [
        "text",
        "interactive",
        "image",
    ]


def get_valid_message_type(message_info: dict) -> ValidMessageType:

    if is_interactive_message(message_info):
        return ValidMessageType.SETTINGS_FLOW_SELECTION
    if is_other_message(message_info):
        logger.debug("WE ENCOUNTERED ANOTHER MESSAGE TYPE")
        return ValidMessageType.OTHER
    if is_command_message(message_info):
        return ValidMessageType.COMMAND

    return ValidMessageType.CHAT


def get_request_type(body: dict) -> RequestType:
    try:
        if is_flow_event(body):  # Various standard Flow events
            return RequestType.FLOW_EVENT
        if is_status_update(body):  # WhatsApp status update (sent, delivered, read)
            return RequestType.MESSAGE_STATUS_UPDATE
        if is_flow_complete_message(body):  # Flow completion message
            return RequestType.FLOW_COMPLETE
        if is_invalid_whatsapp_message(body):  # Non-status updates (message, other)
            return RequestType.INVALID_MESSAGE

        # For valid WhatsApp messages, extract the message info
        message_info = extract_message_info(body)

        if is_message_outdated(message_info["timestamp"]):
            return RequestType.OUTDATED

    except Exception as e:
        logger.error(f"Error determining request type: {e}")
        raise

    return RequestType.VALID_MESSAGE
