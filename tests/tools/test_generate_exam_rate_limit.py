import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.exam_quota_service import QuotaDecision, QuotaOutcome
from app.tools.tool_code.generate_necta_style_exam import main


@contextmanager
def _pipeline(decision=None, generate_error=None):
    """Patch retrieval, generation and persistence.

    With a `decision`, the quota service is mocked too; without one, the real
    service runs (against the `exam_reservation_db` fixture).
    """
    with (
        patch.object(main.db, "get_class_resources", new=AsyncMock(return_value=[9])),
        patch.object(main.db, "vector_search", new=AsyncMock(return_value=[])),
        patch.object(
            main.exam_generator,
            "generate_exam",
            new=AsyncMock(
                return_value={"generation_trace": {"exam_id": "exam-1"}},
                side_effect=generate_error,
            ),
        ) as generate,
        patch.object(
            main,
            "create_new_exam",
            new=AsyncMock(return_value=SimpleNamespace(id="exam-1")),
        ) as persist,
    ):
        mocks = SimpleNamespace(generate=generate, persist=persist)
        if decision is None:
            yield mocks
            return
        quota = main.exam_quota_service
        with (
            patch.object(quota, "reserve", new=AsyncMock(return_value=decision)),
            patch.object(quota, "complete", new=AsyncMock()) as complete,
            patch.object(quota, "release", new=AsyncMock()) as release,
        ):
            mocks.complete = complete
            mocks.release = release
            yield mocks


async def _call(topics=("Cells",)):
    return json.loads(
        await main.generate_necta_style_exam(7, "Biology", list(topics), 1)
    )


async def test_denied_returns_limit_message_without_generating():
    with (
        patch.object(main.settings, "exam_generation_limit", 2),
        patch.object(main.settings, "exam_generation_window_days", 3),
        _pipeline(QuotaDecision(QuotaOutcome.DENIED)) as mocks,
    ):
        result = await _call()

    assert result == {
        "status": "rate_limited",
        "message": "You have reached the limit of 2 generated exams in 3 days. Please try again later.",
        "limit": 2,
        "window_days": 3,
    }
    mocks.generate.assert_not_awaited()
    mocks.persist.assert_not_awaited()


async def test_reuse_returns_existing_exam_without_generating():
    with _pipeline(QuotaDecision(QuotaOutcome.REUSE, exam_id="exam-old")) as mocks:
        result = await _call()

    assert result["exam_id"] == "exam-old"
    assert result["reused"] is True
    assert "error" not in result
    mocks.generate.assert_not_awaited()
    mocks.complete.assert_not_awaited()


async def test_in_progress_returns_error_without_generating():
    with _pipeline(QuotaDecision(QuotaOutcome.IN_PROGRESS)) as mocks:
        result = await _call()

    assert result == {
        "error": "Your exam is still being prepared. I'll send it here as soon as it's ready.",
        "error_code": "exam_in_progress",
    }
    mocks.generate.assert_not_awaited()


async def test_allowed_generates_saves_and_completes_reservation():
    with _pipeline(QuotaDecision(QuotaOutcome.ALLOWED, reservation_id="r-1")) as mocks:
        result = await _call()

    assert result["exam_id"] == "exam-1"
    assert "reused" not in result
    mocks.persist.assert_awaited_once()
    mocks.complete.assert_awaited_once_with("r-1", "exam-1")
    mocks.release.assert_not_awaited()


async def test_generation_failure_releases_reservation():
    with _pipeline(
        QuotaDecision(QuotaOutcome.ALLOWED, reservation_id="r-1"),
        generate_error=RuntimeError("model timeout"),
    ) as mocks:
        with pytest.raises(Exception, match="model timeout"):
            await _call()

    mocks.release.assert_awaited_once_with("r-1")
    mocks.complete.assert_not_awaited()
    mocks.persist.assert_not_awaited()


async def test_reserve_failure_does_not_start_generation():
    with (
        _pipeline() as mocks,
        patch.object(
            main.exam_quota_service,
            "reserve",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
    ):
        with pytest.raises(Exception, match="database unavailable"):
            await _call()

    mocks.generate.assert_not_awaited()


async def test_repeated_request_returns_same_exam_instead_of_refusing(
    exam_reservation_db,
):
    """The 2026-11-10 case: limit 1, exam saved, then the agent calls the tool again."""
    with (
        patch.object(main.settings, "exam_generation_limit", 1),
        _pipeline() as mocks,
    ):
        first = await _call(["Cells"])
        second = await _call([" cells "])

    assert first["exam_id"] == second["exam_id"] == "exam-1"
    assert second["reused"] is True
    mocks.generate.assert_awaited_once()
    mocks.persist.assert_awaited_once()
