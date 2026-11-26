import json
from typing import Any

from app.database.models import User
from app.services.profile import ClassUpdateAction, ProfileUpdateError, profile_service
from app.services.profile.parsing import parse_class_requests


async def update_my_classes(
    action: str,
    classes: list[dict[str, Any]],
    user: User,
    unavailable_subjects: list[str] | None = None,
) -> str:
    """Add, remove or replace the subjects and forms the teacher teaches.

    `user` is injected server-side (see `app/tools/internal_args.py`) and is
    never part of the tool schema, so the model can only change this teacher.
    """
    parsed = parse_class_requests(classes, unavailable_subjects)
    try:
        snapshot = await profile_service.update_classes(
            user,
            ClassUpdateAction(action),
            parsed.requested,
            unrecognized=parsed.unrecognized,
        )
    except ProfileUpdateError as error:
        return json.dumps(error.to_tool_payload())
    return json.dumps(snapshot.to_tool_payload())
