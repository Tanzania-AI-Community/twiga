from pydantic import BaseModel, constr, Field
from typing import List, Dict, Literal, Optional
import json


class TextObject(BaseModel):
    text: str


class Reply(BaseModel):
    id: str
    title: str


class Button(BaseModel):
    type: Literal["reply"]
    reply: Reply


class ButtonsAction(BaseModel):
    buttons: List[Button]


class Row(BaseModel):
    id: str
    title: str
    description: Optional[str] = None


class Section(BaseModel):
    title: str
    rows: List[Row]


class ListAction(BaseModel):
    button: str
    sections: List[Section]


# Main model for interactive button message
class InteractiveButton(BaseModel):
    type: Literal["button"] = "button"
    body: TextObject
    footer: TextObject
    action: ButtonsAction


# Main model for interactive list message
class InteractiveList(BaseModel):
    type: Literal["list"] = "list"
    body: TextObject
    footer: TextObject
    action: ListAction


"""
Main model for Text Messages
"""


class TextMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    preview_url: bool = False
    to: str
    type: Literal["text"] = "text"
    text: Dict[Literal["body"], str]


"""
Main model for interactive messages
"""


class InteractiveMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    to: str
    type: Literal["interactive"] = "interactive"
    interactive: InteractiveButton | InteractiveList
