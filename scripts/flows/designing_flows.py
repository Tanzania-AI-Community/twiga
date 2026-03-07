from typing import Any, Dict
from fastapi.responses import PlainTextResponse
import logging

from app.database import db
from app.database.models import User
import app.utils.flow_utils as futil

logger = logging.getLogger(__name__)


async def handle_onboarding_init_action(
    user: User,
) -> Dict[str, Any] | PlainTextResponse:
    try:
        response_payload = futil.create_flow_response_payload(
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
            subject_title = subject.name.value.replace("_", " ").title()
            subject_options.append({"id": str(subject.id), "title": subject_title})

        response_payload = futil.create_flow_response_payload(
            screen="select_subject",
            data={
                "subject_options": subject_options,
                "has_subject_options": len(subject_options) > 0,
                "select_subject_text": "Select a subject, save its classes, then repeat for other subjects.",
                "configured_subjects_text": "Configured subjects: 0",
                "no_subjects_text": "Sorry, there are no available subjects.",
                "subject_dropdown_label": "Subject",
                "complete_button_label": "Complete",
            },
        )

        return response_payload

    except ValueError as e:
        return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
