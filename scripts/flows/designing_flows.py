from typing import Any, Dict
from fastapi.responses import PlainTextResponse
import logging

from app.database import db
from app.database.models import User
import app.utils.flow_utils as futil

logger = logging.getLogger(__name__)


# async def handle_select_classes_init_action(
#     user: User,
# ) -> Dict[str, Any] | PlainTextResponse:
#     try:
#         subject_id = 1  # Hardcoded subject_id as 1, because init action is only used when testing
#         subject_data = await db.get_subject_grade_levels(subject_id)
#         subject_title = subject_data["subject_name"]
#         classes = subject_data["classes"]
#         logger.debug(f"Subject title for subject ID {subject_id}: {subject_title}")
#         logger.debug(f"Available classes for subject ID {subject_id}: {classes}")
#
#         select_class_question_text = f"Select the class you are in for {subject_title}."
#         select_class_text = f"This helps us find the best answers for your questions in {subject_title}."
#         no_classes_text = (
#             f"Sorry, currently there are no active classes for {subject_title}."
#         )
#         has_classes = len(classes) > 0
#
#         response_payload = futil.create_flow_response_payload(
#             screen="select_classes",
#             data={
#                 "classes": (
#                     classes
#                     if has_classes
#                     else [
#                         {
#                             "id": "0",
#                             "title": "No classes available",
#                         }
#                     ]
#                 ),
#                 "has_classes": has_classes,
#                 "no_classes_text": no_classes_text,
#                 "select_class_text": select_class_text,
#                 "select_class_question_text": select_class_question_text,
#                 "subject_id": str(subject_id),
#             },
#         )
#
#         return response_payload
#
#     except ValueError as e:
#         return PlainTextResponse(
#             content={"error_msg": str(e)},
#             status_code=422,
#         )


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


async def handle_select_subjects_init_action(
    user: User,
) -> Dict[str, Any] | PlainTextResponse:
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


# Hardcoded data for subjects and classes
HARDCODED_SUBJECTS_AND_CLASSES = {
    "subject1": {
        "subject_id": "1",
        "subject_title": "Mathematics",
        "classes": [
            {"id": "101", "title": "Class 1"},
            {"id": "102", "title": "Class 2"},
        ],
        "available": True,
        "label": "Classes for Mathematics",
    },
    "subject2": {
        "subject_id": "2",
        "subject_title": "Science",
        "classes": [
            {"id": "201", "title": "Class 3"},
            {"id": "202", "title": "Class 4"},
        ],
        "available": True,
        "label": "Classes for Science",
    },
    "subject3": {
        "subject_id": "3",
        "subject_title": "History",
        "classes": [
            {"id": "301", "title": "Class 5"},
            {"id": "302", "title": "Class 6"},
        ],
        "available": True,
        "label": "Classes for History",
    },
    "subject4": {
        "subject_id": "4",
        "subject_title": "Geography",
        "classes": [
            {"id": "401", "title": "Class 7"},
            {"id": "402", "title": "Class 8"},
        ],
        "available": False,
        "label": "Classes for Geography",
    },
    "subject5": {
        "subject_id": "5",
        "subject_title": "English",
        "classes": [
            {"id": "501", "title": "Class 9"},
            {"id": "502", "title": "Class 10"},
        ],
        "available": False,
        "label": "Classes for English",
    },
    "subject6": {
        "subject_id": "6",
        "subject_title": "Physics",
        "classes": [
            {"id": "601", "title": "Class 11"},
            {"id": "602", "title": "Class 12"},
        ],
        "available": False,
        "label": "Classes for Physics",
    },
}


async def handle_simple_subjects_classes_init_action(user: User) -> Dict[str, Any]:
    try:
        # Hardcoded data for subjects and classes
        subjects_data = HARDCODED_SUBJECTS_AND_CLASSES

        # Prepare the response payload
        response_payload = futil.create_flow_response_payload(
            screen="select_subjects_and_classes",
            data={
                "subject1": (subjects_data["subject1"]),
                "subject2": (subjects_data["subject2"]),
                "subject3": (subjects_data["subject3"]),
                "subject4": (subjects_data["subject4"]),
                "subject5": (subjects_data["subject5"]),
                "subject6": (subjects_data["subject6"]),
                "subject1_available": subjects_data["subject1"]["available"],
                "subject2_available": subjects_data["subject2"]["available"],
                "subject3_available": subjects_data["subject3"]["available"],
                "subject4_available": subjects_data["subject4"]["available"],
                "subject5_available": subjects_data["subject5"]["available"],
                "subject6_available": subjects_data["subject6"]["available"],
                "subject1_label": subjects_data["subject1"]["label"],
                "subject2_label": subjects_data["subject2"]["label"],
                "subject3_label": subjects_data["subject3"]["label"],
                "subject4_label": subjects_data["subject4"]["label"],
                "subject5_label": subjects_data["subject5"]["label"],
                "subject6_label": subjects_data["subject6"]["label"],
                "select_subject_text": "Please select the subjects and the classes you teach.",
                "no_subjects_text": "Sorry, there are no available subjects.",
            },
        )

        return response_payload

    except ValueError as e:
        return PlainTextResponse(content={"error_msg": str(e)}, status_code=422)
