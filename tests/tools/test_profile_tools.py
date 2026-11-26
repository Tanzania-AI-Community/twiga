import json
from unittest.mock import AsyncMock, patch

import pytest

from app.database.enums import GradeLevel, SubjectName
from app.database.models import User
from app.services.profile import (
    ClassUpdateAction,
    ProfileErrorCode,
    ProfileSnapshot,
    ProfileUpdateError,
    SubjectForms,
)
from app.tools.registry import CURRICULUM_TOOLS, PROFILE_TOOLS, ToolName
from app.tools.tool_code.update_my_classes.main import update_my_classes
from app.tools.tool_code.update_my_name.main import update_my_name
from app.tools.tool_manager import ToolManager

USER = User(id=7, wa_id="255700000007", name="Ali")
SNAPSHOT = ProfileSnapshot(
    name="Luke Nuru", classes={SubjectName.geography: (GradeLevel.os2,)}
)


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


# --- adapters ---------------------------------------------------------------


async def test_update_my_name_returns_saved_profile() -> None:
    with patch(
        "app.tools.tool_code.update_my_name.main.profile_service.set_name",
        AsyncMock(return_value=SNAPSHOT),
    ) as set_name:
        result = json.loads(await update_my_name(name="Luke Nuru", user=USER))

    set_name.assert_awaited_once_with(USER, "Luke Nuru")
    assert result["ok"] is True
    assert result["profile"]["name"] == "Luke Nuru"


async def test_update_my_name_returns_error_payload() -> None:
    error = ProfileUpdateError(ProfileErrorCode.invalid_name, "Letters only.")
    with patch(
        "app.tools.tool_code.update_my_name.main.profile_service.set_name",
        AsyncMock(side_effect=error),
    ):
        result = json.loads(await update_my_name(name="my name is Luke", user=USER))

    assert result == {"ok": False, "error": "invalid_name", "detail": "Letters only."}


async def test_update_my_classes_parses_and_delegates() -> None:
    with patch(
        "app.tools.tool_code.update_my_classes.main.profile_service.update_classes",
        AsyncMock(return_value=SNAPSHOT),
    ) as update_classes:
        result = json.loads(
            await update_my_classes(
                action="add",
                classes=[{"subject": "geography", "forms": ["Form 2"]}],
                unavailable_subjects=["Kiswahili"],
                user=USER,
            )
        )

    update_classes.assert_awaited_once_with(
        USER,
        ClassUpdateAction.add,
        (SubjectForms(SubjectName.geography, frozenset({GradeLevel.os2})),),
        unrecognized=("Kiswahili",),
    )
    assert result["ok"] is True


async def test_update_my_classes_returns_error_payload() -> None:
    error = ProfileUpdateError(ProfileErrorCode.would_remove_all, "Keep one class.")
    with patch(
        "app.tools.tool_code.update_my_classes.main.profile_service.update_classes",
        AsyncMock(side_effect=error),
    ):
        result = json.loads(
            await update_my_classes(action="remove", classes=[], user=USER)
        )

    assert result["error"] == "would_remove_all"


# --- tool manager: server-side user and allowlist --------------------------


async def test_profile_tool_gets_the_sender_even_if_model_forges_a_user() -> None:
    manager = ToolManager()
    forged = _tool_call(
        ToolName.update_my_name.value, {"name": "Luke", "user": {"id": 999}}
    )

    with patch(
        "app.tools.tool_code.update_my_name.main.profile_service.set_name",
        AsyncMock(return_value=SNAPSHOT),
    ) as set_name:
        [response] = await manager.process_tool_calls([forged], USER)

    assert set_name.await_args.args[0] is USER
    assert json.loads(response.content)["ok"] is True


async def test_profile_tool_rejects_extra_model_arguments() -> None:
    manager = ToolManager()
    call = _tool_call(ToolName.update_my_name.value, {"name": "Luke", "user_id": 999})

    with patch(
        "app.tools.tool_code.update_my_name.main.profile_service.set_name",
        AsyncMock(return_value=SNAPSHOT),
    ) as set_name:
        [response] = await manager.process_tool_calls([call], USER)

    set_name.assert_not_awaited()
    assert "error" in json.loads(response.content)


async def test_tools_outside_the_allowlist_are_refused() -> None:
    manager = ToolManager()
    call = _tool_call(
        ToolName.search_knowledge.value, {"search_phrase": "rivers", "class_id": 1}
    )

    with patch(
        "app.tools.tool_manager.TOOL_FUNCTION_MAP",
        {ToolName.search_knowledge.value: AsyncMock()},
    ) as function_map:
        [response] = await manager.process_tool_calls(
            [call], USER, allowed=PROFILE_TOOLS
        )

    function_map[ToolName.search_knowledge.value].assert_not_awaited()
    assert json.loads(response.content) == {"error": "tool_not_available"}


@pytest.mark.parametrize("allowed", [None, CURRICULUM_TOOLS | PROFILE_TOOLS])
async def test_allowed_tools_still_run(allowed) -> None:
    manager = ToolManager()
    call = _tool_call(ToolName.update_my_name.value, {"name": "Luke"})

    with patch(
        "app.tools.tool_code.update_my_name.main.profile_service.set_name",
        AsyncMock(return_value=SNAPSHOT),
    ) as set_name:
        await manager.process_tool_calls([call], USER, allowed=allowed)

    set_name.assert_awaited_once()
