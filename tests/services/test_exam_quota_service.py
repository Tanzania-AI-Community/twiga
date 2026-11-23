from datetime import timedelta
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
        ((None, False), QuotaDecision(QuotaOutcome.DENIED)),
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
async def test_reserve_maps_db_result_to_decision(db_result, expected):
    with patch.object(
        module.db, "reserve_exam_generation", new=AsyncMock(return_value=db_result)
    ):
        assert await ExamQuotaService().reserve(1, "key") == expected


@pytest.mark.parametrize(
    ("db_result", "expected"),
    [
        ((None, True), QuotaDecision(QuotaOutcome.ALLOWED)),
        ((None, False), QuotaDecision(QuotaOutcome.DENIED)),
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
async def test_preview_maps_db_result_to_decision(db_result, expected):
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
            new=AsyncMock(return_value=(None, False)),
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
