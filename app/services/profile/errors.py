from enum import Enum


class ProfileErrorCode(str, Enum):
    """Why a profile update was refused. Values are part of the tool contract."""

    invalid_name = "invalid_name"
    unknown_subject = "unknown_subject"
    unknown_form = "unknown_form"
    class_unavailable = "class_unavailable"
    limit_exceeded = "limit_exceeded"
    would_remove_all = "would_remove_all"
    missing_forms = "missing_forms"


class ProfileUpdateError(Exception):
    """A refused profile update; `detail` is safe to show the teacher."""

    def __init__(self, code: ProfileErrorCode, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def to_tool_payload(self) -> dict:
        return {"ok": False, "error": self.code.value, "detail": self.detail}
