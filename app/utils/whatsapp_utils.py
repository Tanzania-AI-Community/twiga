from datetime import datetime
from enum import Enum, auto
import re
from typing import Any, Dict, List, Optional
import logging
from sympy import sympify, preview
from sympy.parsing.latex import parse_latex
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import tempfile
import os

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
    return message_info.get("message", {}).get("type") not in ["text", "interactive"]


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

def _catch_latex_math(msg):
    """checks if the message contains LaTeX math expressions"""
    if not msg:
        return None
    
    # Patterns for different LaTeX math formats
    patterns = [
        r'\$\$(.*?)\$\$',           # $$...$$
        r'\\\[(.*?)\\\]',           # \[...\]
        r'\\\((.*?)\\\)',           # \(...\)
        r'\\begin\{equation\}(.*?)\\end\{equation\}',  # \begin{equation}...\end{equation}
        r'\\begin\{align\}(.*?)\\end\{align\}',        # \begin{align}...\end{align}
        r'\$(.*?)\$'                # $...$ (inline math, check last to avoid conflicts)
    ]
    
    found_formulas = []
    
    for pattern in patterns:
        matches = re.findall(pattern, msg, re.DOTALL)
        if matches:
            logger.warning(f"LaTeX math expressions detected in final response")
            return True
    if found_formulas:
        return found_formulas
    
    return None

def parse_msg_with_latex(msg):
    """parses a message with detected latex formulas and returns a list of alternating text and latex parts"""
    if not msg:
        return []

    # Patterns for different LaTeX math formats
    patterns = [
        r'\$\$(.*?)\$\$',           # $$...$$
        r'\\\[(.*?)\\\]',           # \[...\]
        r'\\\((.*?)\\\)',           # \(...\)
        r'\\begin\{equation\}(.*?)\\end\{equation\}',  # \begin{equation}...\end{equation}
        r'\\begin\{align\}(.*?)\\end\{align\}',        # \begin{align}...\end{align}
        r'\$(.*?)\$'                # $...$ (inline math, check last to avoid conflicts)
    ]

    # Find all formula positions in the text
    formula_positions = []
    for pattern in patterns:
        for match in re.finditer(pattern, msg, re.DOTALL):
            formula_positions.append({
                'start': match.start(),
                'end': match.end(),
                'full_match': match.group(0),  # Full match including delimiters
                'formula': match.group(1).strip(),  # Just the formula content
                'type': 'latex'
            })

    # Sort by position to process in order
    formula_positions.sort(key=lambda x: x['start'])

    # Build the result list with alternating text and LaTeX parts
    result = []
    current_pos = 0

    for formula_info in formula_positions:
        # Add text before the formula (if any)
        if current_pos < formula_info['start']:
            text_part = msg[current_pos:formula_info['start']].strip()
            if text_part:
                result.append({
                    'content': text_part,
                    'type': 'text'
                })
        image_path = convert_latex_to_image(formula_info['formula'])  # Generate image for the LaTeX formula
        # Add the LaTeX formula with image path
        result.append({
            'content': formula_info['formula'],
            'full_match': formula_info['full_match'],
            'image_path': image_path,  # Add the temp image path
            'type': 'latex'
        })
        current_pos = formula_info['end']
    # Add remaining text after all formulas (if any)
    if current_pos < len(msg):
        remaining_text = msg[current_pos:].strip()
        if remaining_text:
            result.append({
                'content': remaining_text,
                'type': 'text'
            })
    return result


def convert_latex_to_image(latex_content: str) -> Optional[str]:
    """converts latex content to an image using SymPy and returns the temporary file path"""

    # Skip empty or whitespace-only content
    if not latex_content or not latex_content.strip():
        logger.warning("Empty LaTeX content provided, skipping image generation")
        return None
    
    try:
        # Try to parse the LaTeX content
        try:
            expr = parse_latex(latex_content)
        except:
            try:
                expr = sympify(latex_content)
            except:
                logger.warning(f"Could not parse LaTeX content: {latex_content}")
                return _matplotlib_fallback(latex_content)
        
        # Create a temporary file (SymPy preview needs a file path)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Generate the image using SymPy's preview function
            preview(expr, viewer='file', filename=temp_path, 
                    dvioptions=['-T', 'tight', '-z', '0', '--truecolor', '-D 300'])
            
            # Return the temporary file path
            return temp_path
        except Exception as preview_error:
            # If SymPy preview fails (LaTeX not installed), try matplotlib fallback
            logger.warning(f"SymPy preview failed for '{latex_content}': {preview_error}")
            os.unlink(temp_path)  # Clean up the empty file
            return _matplotlib_fallback(latex_content)
        
    except Exception as e:
        logger.warning(f"Failed to generate LaTeX image for '{latex_content}': {e}")
        return None


def _matplotlib_fallback(latex_content: str) -> Optional[str]:
    """Fallback to matplotlib for basic LaTeX rendering when SymPy preview fails"""
    try:
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_path = temp_file.name
        
        # Create figure with white background
        fig, ax = plt.subplots(figsize=(8, 2), facecolor='white')
        ax.set_facecolor('white')
        
        # Try to render LaTeX with matplotlib
        try:
            # Clean up the LaTeX for matplotlib (add $ if not present)
            if not latex_content.startswith('$'):
                latex_display = f'${latex_content}$'
            else:
                latex_display = latex_content
                
            ax.text(0.5, 0.5, latex_display, fontsize=16, ha='center', va='center',
                   transform=ax.transAxes, usetex=False)
        except:
            # If LaTeX rendering fails, show as plain text
            ax.text(0.5, 0.5, f"Formula: {latex_content}", fontsize=14, ha='center', va='center',
                   transform=ax.transAxes, family='monospace')
        
        # Remove axes
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        
        # Save with tight bbox
        plt.savefig(temp_path, format='png', bbox_inches='tight', 
                   facecolor='white', edgecolor='none', dpi=150)
        plt.close(fig)
        
        logger.info(f"Generated fallback image for LaTeX: {latex_content}")
        return temp_path
        
    except Exception as e:
        logger.warning(f"Matplotlib fallback failed for '{latex_content}': {e}")
        return None