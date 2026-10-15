import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.tool_code.generate_necta_style_exam import main


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [2, 4])
async def test_rate_limited_before_retrieval_or_generation(count):
    with (
        patch.object(main.settings, "exam_generation_limit", 2),
        patch.object(main.settings, "exam_generation_window_days", 3),
        patch.object(
            main.db, "count_generated_exams_since", new=AsyncMock(return_value=count)
        ),
        patch.object(main.db, "get_class_resources", new=AsyncMock()) as resources,
        patch.object(main.db, "vector_search", new=AsyncMock()) as search,
        patch.object(main.exam_generator, "generate_exam", new=AsyncMock()) as generate,
        patch.object(main, "create_new_exam", new=AsyncMock()) as persist,
    ):
        result = json.loads(
            await main.generate_necta_style_exam(1, "Biology", ["Cells"], 7)
        )

    assert result == {
        "status": "rate_limited",
        "message": "You have reached the limit of 2 generated exams in 3 days. Please try again later.",
        "limit": 2,
        "window_days": 3,
    }
    resources.assert_not_awaited()
    search.assert_not_awaited()
    generate.assert_not_awaited()
    persist.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 4])
async def test_under_limit_generates_and_persists_exam(count):
    with (
        patch.object(
            main.db, "count_generated_exams_since", new=AsyncMock(return_value=count)
        ),
        patch.object(main.db, "get_class_resources", new=AsyncMock(return_value=[9])),
        patch.object(main.db, "vector_search", new=AsyncMock(return_value=[])),
        patch.object(
            main.exam_generator,
            "generate_exam",
            new=AsyncMock(return_value={"generation_trace": {"exam_id": "exam-1"}}),
        ) as generate,
        patch.object(
            main,
            "create_new_exam",
            new=AsyncMock(return_value=SimpleNamespace(id="exam-1")),
        ) as persist,
    ):
        result = json.loads(
            await main.generate_necta_style_exam(1, "Biology", ["Cells"], 7)
        )

    assert result["exam_id"] == "exam-1"
    generate.assert_awaited_once()
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_failure_does_not_start_generation():
    with (
        patch.object(
            main.db,
            "count_generated_exams_since",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        patch.object(main.db, "get_class_resources", new=AsyncMock()) as resources,
        patch.object(main.exam_generator, "generate_exam", new=AsyncMock()) as generate,
    ):
        with pytest.raises(Exception, match="database unavailable"):
            await main.generate_necta_style_exam(1, "Biology", ["Cells"], 7)

    resources.assert_not_awaited()
    generate.assert_not_awaited()
