"""Small, in-memory types for the WhatsApp image pathway."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncomingImage(BaseModel):
    media_id: str = Field(min_length=1, pattern=r"^[0-9]+$")
    caption: str = ""


@dataclass(frozen=True)
class DownloadedImage:
    data: bytes = field(repr=False)
    mime_type: str


class ImageInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transcription: str
    visual_details: str
    readability: Literal["clear", "partial", "unreadable"]
    clarification_reason: str

    @model_validator(mode="after")
    def validate_readability(self):
        if self.readability == "clear" and self.clarification_reason.strip():
            raise ValueError("A clear extraction cannot need clarification")
        if self.readability == "clear" and not (
            self.transcription.strip() or self.visual_details.strip()
        ):
            raise ValueError("A readable image must have extracted content")
        if self.readability != "clear" and not self.clarification_reason.strip():
            raise ValueError("Unclear content needs a clarification reason")
        return self

    def to_request_text(self, caption: str) -> str:
        return (
            "Source: teacher image\n"
            f"Teacher instruction: {caption.strip() or 'none'}\n"
            f"Transcription: {self.transcription.strip() or 'none'}\n"
            f"Relevant visual details: {self.visual_details.strip() or 'none'}"
        )


class ImageInputError(Exception):
    """A safe, teacher-facing error key; never include provider payloads."""

    def __init__(self, message_key: str = "image_processing_failed"):
        self.message_key = message_key
        super().__init__(message_key)
