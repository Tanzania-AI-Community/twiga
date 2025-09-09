from pydantic import BaseModel
from typing import List, Dict, Literal, Optional, Union, Any
from pydantic import model_validator


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
Main model for template messages
"""


class TemplateLanguage(BaseModel):
    code: str = "en"


class TemplateComponent(BaseModel):
    type: Literal["header", "body", "footer", "button"]
    parameters: Optional[List[Dict[str, Any]]] = None


class Template(BaseModel):
    name: str
    language: TemplateLanguage
    components: Optional[List[TemplateComponent]] = None


class TemplateMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    to: str
    type: Literal["template"] = "template"
    template: Template


"""
Models for flow interactive messages
"""


class FlowActionPayload(BaseModel):
    screen: str
    data: Dict[str, Union[str, int]]


class FlowParameters(BaseModel):
    flow_message_version: str
    flow_token: str
    flow_name: Optional[str] = None
    flow_id: Optional[str] = None
    flow_cta: str
    flow_action: str
    flow_action_payload: FlowActionPayload

    @model_validator(mode="before")
    def check_flow_name_or_id(cls, values):
        flow_name, flow_id = values.get("flow_name"), values.get("flow_id")
        if not flow_name and not flow_id:
            raise ValueError("Either flow_name or flow_id must be provided")
        if flow_name and flow_id:
            raise ValueError("Only one of flow_name or flow_id should be provided")
        return values


class FlowAction(BaseModel):
    name: Literal["flow"]
    parameters: FlowParameters


class FlowInteractive(BaseModel):
    type: Literal["flow"] = "flow"
    header: TextObject
    body: TextObject
    footer: TextObject
    action: FlowAction


class FlowInteractiveMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    to: str
    type: Literal["interactive"] = "interactive"
    interactive: FlowInteractive


"""
Main model for interactive messages
"""


class InteractiveMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    to: str
    type: Literal["interactive"] = "interactive"
    interactive: Union[InteractiveButton, InteractiveList, FlowInteractive]
