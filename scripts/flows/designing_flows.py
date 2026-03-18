from typing import Any, Dict
from fastapi.responses import PlainTextResponse
import logging

from app.database import db
from app.database.models import User
import app.services.flows.utils as flow_utils

logger = logging.getLogger(__name__)
FLOW_OPTION_TITLE_MAX_LEN = 30
FLOW_MAX_CHIPS_OPTIONS = 20


def _get_subject_title_with_leading_emoji(display_value: str) -> str:
    parts = display_value.rsplit(" ", 1)
    if len(parts) == 2:
        name_part, emoji_part = parts
        if emoji_part:
            return f"{emoji_part} {name_part}"
    return display_value


def _truncate_option_title(title: str) -> str:
    if len(title) <= FLOW_OPTION_TITLE_MAX_LEN:
        return title
    return f"{title[: FLOW_OPTION_TITLE_MAX_LEN - 3]}..."


async def handle_onboarding_init_action(
    user: User,
) -> Dict[str, Any] | PlainTextResponse:
    try:
        response_payload = flow_utils.create_flow_response_payload(
            screen="personal_info",
            data={
                "full_name": user.name,
            },
        )
        return response_payload
    except ValueError as e:
        return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)


async def handle_subjects_classes_init_action(
    user: User,
) -> Dict[str, Any] | PlainTextResponse:
    try:
        subjects = await db.read_subjects()
        subject_options = []
        for subject in subjects or []:
            if subject.id is None:
                continue
            display_value = subject.name.display_format
            subject_title = _truncate_option_title(
                _get_subject_title_with_leading_emoji(display_value)
            )
            subject_options.append({"id": str(subject.id), "title": subject_title})
        subject_options = sorted(
            subject_options, key=lambda option: option["title"].lower()
        )[:FLOW_MAX_CHIPS_OPTIONS]

        response_payload = flow_utils.create_flow_response_payload(
            screen="select_subject",
            data={
                "subject_options": subject_options,
                "selected_subject_ids": [],
                "has_subject_options": len(subject_options) > 0,
            },
        )

        return response_payload

    except ValueError as e:
        return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
