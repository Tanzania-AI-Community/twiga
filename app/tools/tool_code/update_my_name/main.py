import json

from app.database.models import User
from app.services.profile import ProfileUpdateError, profile_service


async def update_my_name(name: str, user: User) -> str:
    """Save the name the teacher wants to be called.

    `user` is injected server-side (see `app/tools/internal_args.py`) and is
    never part of the tool schema, so the model can only rename this teacher.
    """
    try:
        snapshot = await profile_service.set_name(user, name)
    except ProfileUpdateError as error:
        return json.dumps(error.to_tool_payload())
    return json.dumps(snapshot.to_tool_payload())
