from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.database.enums import ExamReservationStatus
from app.services import exam_quota_service as module
from app.services.exam_quota_service import (
    ExamQuotaService,
    QuotaDecision,
    QuotaOutcome,
    exam_request_key,
)

NEXT_AVAILABLE_AT = datetime(2026, 11, 27, 6, 14, tzinfo=timezone.utc)


@pytest.fixture
def next_available_at():
    with patch.object(
        ExamQuotaService,
        "_next_available_at",
        new=AsyncMock(return_value=NEXT_AVAILABLE_AT),
    ):
        yield NEXT_AVAILABLE_AT


def test_request_key_ignores_topic_order_case_and_spacing():
    assert exam_request_key(7, "Geography", ["Climate", "map  reading"]) == (
        exam_request_key(7, " geography ", ["Map reading", "climate", " "])
    )


@pytest.mark.parametrize(
    "other",
    [
        (8, "Geography", ["Climate"]),
        (7, "Biology", ["Climate"]),
        (7, "Geography", ["Climate", "Weather"]),
    ],
)
def test_request_key_differs_for_a_different_exam(other):
    assert exam_request_key(7, "Geography", ["Climate"]) != exam_request_key(*other)


@pytest.mark.parametrize(
    ("db_result", "expected"),
    [
        (
            (None, False),
            QuotaDecision(QuotaOutcome.DENIED, next_available_at=NEXT_AVAILABLE_AT),
        ),
        (
            (SimpleNamespace(id="r-1", status=ExamReservationStatus.pending), True),
            QuotaDecision(QuotaOutcome.ALLOWED, reservation_id="r-1"),
        ),
        (
            (
                SimpleNamespace(
                    id="r-1", status=ExamReservationStatus.completed, exam_id="e-1"
                ),
                False,
            ),
            QuotaDecision(QuotaOutcome.REUSE, exam_id="e-1"),
        ),
        (
            (SimpleNamespace(id="r-1", status=ExamReservationStatus.pending), False),
            QuotaDecision(QuotaOutcome.IN_PROGRESS),
        ),
    ],
    ids=["denied", "allowed", "reuse", "in-progress"],
)
async def test_reserve_maps_db_result_to_decision(
    db_result, expected, next_available_at
):
    with patch.object(
        module.db, "reserve_exam_generation", new=AsyncMock(return_value=db_result)
    ):
        assert await ExamQuotaService().reserve(1, "key") == expected


@pytest.mark.parametrize(
    ("db_result", "expected"),
    [
        ((None, True), QuotaDecision(QuotaOutcome.ALLOWED)),
        (
            (None, False),
            QuotaDecision(QuotaOutcome.DENIED, next_available_at=NEXT_AVAILABLE_AT),
        ),
        (
            (
                SimpleNamespace(status=ExamReservationStatus.completed, exam_id="e-1"),
                False,
            ),
            QuotaDecision(QuotaOutcome.REUSE, exam_id="e-1"),
        ),
        (
            (SimpleNamespace(status=ExamReservationStatus.pending), False),
            QuotaDecision(QuotaOutcome.IN_PROGRESS),
        ),
    ],
    ids=["allowed", "denied", "reuse", "in-progress"],
)
async def test_preview_maps_db_result_to_decision(
    db_result, expected, next_available_at
):
    with patch.object(
        module.db, "preview_exam_generation", new=AsyncMock(return_value=db_result)
    ):
        assert await ExamQuotaService().preview(1, "key") == expected


async def test_reserve_passes_configured_limit_and_windows():
    with (
        patch.object(module.settings, "exam_generation_limit", 3),
        patch.object(module.settings, "exam_generation_window_days", 2),
        patch.object(module.settings, "exam_reservation_timeout_minutes", 15),
        patch.object(module.settings, "exam_reuse_window_minutes", 45),
        patch.object(
            module.db,
            "reserve_exam_generation",
            new=AsyncMock(return_value=(SimpleNamespace(id="r-1"), True)),
        ) as reserve,
    ):
        await ExamQuotaService().reserve(1, "key")

    kwargs = reserve.await_args.kwargs
    assert kwargs["limit"] == 3
    assert kwargs["pending_since"] - kwargs["window_start"] == timedelta(
        days=2, minutes=-15
    )
    assert kwargs["pending_since"] - kwargs["reuse_since"] == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("method", "db_function", "args"),
    [
        ("complete", "mark_exam_reservation_completed", ("r-1", "e-1")),
        ("release", "mark_exam_reservation_failed", ("r-1",)),
    ],
)
async def test_complete_and_release_do_not_raise_on_db_errors(
    method, db_function, args
):
    with patch.object(
        module.db, db_function, new=AsyncMock(side_effect=RuntimeError("db down"))
    ) as db_call:
        await getattr(ExamQuotaService(), method)(*args)

    db_call.assert_awaited_once_with(*args)


@pytest.mark.parametrize(
    ("oldest", "expected"),
    [
        (
            datetime(2026, 11, 20, 6, 14, tzinfo=timezone.utc),
            datetime(2026, 11, 27, 6, 14, tzinfo=timezone.utc),
        ),
        (None, None),
    ],
    ids=["oldest-slot-plus-window", "freed-meanwhile"],
)
async def test_next_available_at_is_when_oldest_slot_leaves_window(oldest, expected):
    with (
        patch.object(module.settings, "exam_generation_window_days", 7),
        patch.object(
            module.db,
            "get_oldest_counted_exam_slot_at",
            new=AsyncMock(return_value=oldest),
        ),
    ):
        before = datetime.now(timezone.utc)
        result = await ExamQuotaService._next_available_at(
            1, ExamQuotaService._limits()
        )

    if expected is None:
        assert before <= result <= datetime.now(timezone.utc)
    else:
        assert result == expected
