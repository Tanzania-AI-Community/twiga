import json
from unittest.mock import AsyncMock, patch

from app.clients.agent_client import AgentClient
from app.database.models import User
from app.tools import tool_manager as tool_manager_module
from app.tools.tool_manager import ToolManager

EXAM = "generate_necta_style_exam"
LIMIT_RESULT = json.dumps({"status": "rate_limited", "message": "Limit reached."})


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


EXAM_CALL = _call(
    "call_exam", EXAM, {"class_id": "7", "subject": "Biology", "topics": ["Cells"]}
)
EXERCISE_CALL = _call(
    "call_exercise", "generate_exercise", {"query": "cells", "class_id": 7}
)
USER = User(id=1, name="Test User", wa_id="255700000001")


def _preflights(preflight):
    return patch.dict(tool_manager_module.TOOL_PREFLIGHT_MAP, {EXAM: preflight})


async def test_run_preflights_answers_settled_call_with_tool_args():
    preflight = AsyncMock(return_value=LIMIT_RESULT)
    with _preflights(preflight):
        responses = await ToolManager().run_preflights([EXAM_CALL, EXERCISE_CALL], USER)

    assert [(r.tool_call_id, r.tool_name, r.content) for r in responses] == [
        ("call_exam", EXAM, LIMIT_RESULT)
    ]
    preflight.assert_awaited_once_with(
        class_id=7, subject="Biology", topics=["Cells"], user_id=1
    )


async def test_run_preflights_lets_tool_run_when_preflight_passes_or_fails():
    for preflight in (
        AsyncMock(return_value=None),
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        with _preflights(preflight):
            assert await ToolManager().run_preflights([EXAM_CALL], USER) == []


async def test_observe_skips_notification_and_tool_for_settled_call():
    client = AgentClient()
    with (
        _preflights(AsyncMock(return_value=LIMIT_RESULT)),
        patch.object(
            client.tool_manager, "process_tool_calls", AsyncMock(return_value=[])
        ) as process,
        patch.object(client, "_tool_call_notification", AsyncMock()) as notify,
    ):
        responses = await client._observe(
            tool_calls=[EXAM_CALL, EXERCISE_CALL],
            user=USER,
            api_messages=[],
            final_messages=[],
            notified_tools=set(),
        )

    notify.assert_awaited_once_with(USER, "generate_exercise")
    process.assert_awaited_once_with([EXERCISE_CALL], USER)
    assert [r.content for r in responses] == [LIMIT_RESULT]
