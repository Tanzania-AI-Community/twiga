from typing import Any, Literal, Optional

from pydantic import BaseModel

"""
Main model for Text Messages
"""


class TextMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    recipient_type: Literal["individual"] = "individual"
    preview_url: bool = False
    to: str
    type: Literal["text"] = "text"
    text: dict[Literal["body"], str]


"""
Main model for template messages
"""


class TemplateLanguage(BaseModel):
    code: str = "en"


class TemplateComponent(BaseModel):
    type: Literal["header", "body", "footer", "button"]
    parameters: Optional[list[dict[str, Any]]] = None


class Template(BaseModel):
    name: str
    language: TemplateLanguage
    components: Optional[list[TemplateComponent]] = None


class TemplateMessage(BaseModel):
    messaging_product: Literal["whatsapp"] = "whatsapp"
    to: str
    type: Literal["template"] = "template"
    template: Template
