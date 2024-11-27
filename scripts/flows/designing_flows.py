from typing import Any, Dict
from fastapi.responses import PlainTextResponse
import logging

from app.database import db
from app.database.models import User
import app.utils.flow_utils as futil

logger = logging.getLogger(__name__)


async def handle_select_classes_init_action(user: User) -> Dict[str, Any]:
    try:
        subject_id = 1  # Hardcoded subject_id as 1, because init action is only used when testing
        subject_data = await db.get_subject_grade_levels(subject_id)
        subject_title = subject_data["subject_name"]
        classes = subject_data["classes"]
        logger.debug(f"Subject title for subject ID {subject_id}: {subject_title}")
        logger.debug(f"Available classes for subject ID {subject_id}: {classes}")

        select_class_question_text = f"Select the class you are in for {subject_title}."
        select_class_text = f"This helps us find the best answers for your questions in {subject_title}."
        no_classes_text = (
            f"Sorry, currently there are no active classes for {subject_title}."
        )
        has_classes = len(classes) > 0

        response_payload = futil.create_flow_response_payload(
            screen="select_classes",
            data={
                "classes": (
                    classes
                    if has_classes
                    else [
                        {
                            "id": "0",
                            "title": "No classes available",
                        }
                    ]
                ),
                "has_classes": has_classes,
                "no_classes_text": no_classes_text,
                "select_class_text": select_class_text,
                "select_class_question_text": select_class_question_text,
                "subject_id": str(subject_id),
            },
        )

        return response_payload

    except ValueError as e:
        return PlainTextResponse(
            content={"error_msg": str(e)},
            status_code=422,
        )


async def handle_onboarding_init_action(user: User) -> Dict[str, Any]:
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


async def handle_select_subjects_init_action(user: User) -> Dict[str, Any]:
    try:
        # Get available subjects from the database
        subjects = await db.get_available_subjects()
        logger.debug(f"Available subjects: {subjects}")

        select_subject_text = "This helps us find the best answers for your questions."
        no_subjects_text = "Sorry, currently there are no active subjects."
        has_subjects = len(subjects) > 0

        response_payload = futil.create_flow_response_payload(
            screen="select_subjects",
            data={
                "subjects": (
                    subjects
                    if has_subjects
                    else [{"id": "0", "title": "No subjects available"}]
                ),  # doing this because the response in whatsapp flows expects a list of subjects with id and title
                "has_subjects": has_subjects,
                "no_subjects_text": no_subjects_text,
                "select_subject_text": select_subject_text,
            },
        )
        return response_payload

    except ValueError as e:
        return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
