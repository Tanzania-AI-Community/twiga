from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.database import db
from app.database.enums import ExamReservationStatus
from app.database.models import ExamGenerationReservation

NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(days=7)
PENDING_SINCE = NOW - timedelta(minutes=30)
REUSE_SINCE = NOW - timedelta(minutes=30)


async def _reserve(user_id=1, request_key="key-a", limit=2):
    return await db.reserve_exam_generation(
        user_id,
        request_key,
        limit=limit,
        window_start=WINDOW_START,
        pending_since=PENDING_SINCE,
        reuse_since=REUSE_SINCE,
    )


def _reservation(
    request_key="key-old",
    status=ExamReservationStatus.completed,
    created_at=NOW - timedelta(days=1),
    user_id=1,
    exam_id="exam-old",
    completed_at=None,
):
    return ExamGenerationReservation(
        user_id=user_id,
        request_key=request_key,
        status=status,
        created_at=created_at,
        exam_id=exam_id if status == ExamReservationStatus.completed else None,
        completed_at=completed_at or created_at,
    )


def _all(session):
    return session.execute(select(ExamGenerationReservation)).scalars().all()


async def test_new_request_under_limit_creates_pending_reservation(
    exam_reservation_db,
):
    exam_reservation_db.add(_reservation())
    exam_reservation_db.commit()

    reservation, created = await _reserve()

    assert created is True
    assert reservation.status == ExamReservationStatus.pending
    assert len(_all(exam_reservation_db)) == 2


async def test_request_at_limit_is_denied(exam_reservation_db):
    exam_reservation_db.add_all(
        [
            _reservation("key-1"),
            _reservation("key-2", status=ExamReservationStatus.pending, created_at=NOW),
        ]
    )
    exam_reservation_db.commit()

    assert await _reserve() == (None, False)
    assert len(_all(exam_reservation_db)) == 2


async def test_same_request_completed_recently_is_reused_without_new_slot(
    exam_reservation_db,
):
    exam_reservation_db.add(
        _reservation("key-a", created_at=NOW - timedelta(minutes=10), completed_at=NOW)
    )
    exam_reservation_db.commit()

    # limit=1 is already used by this exam: it is returned, not refused
    reservation, created = await _reserve(limit=1)

    assert created is False
    assert reservation.exam_id == "exam-old"
    assert len(_all(exam_reservation_db)) == 1


async def test_same_request_completed_before_reuse_window_takes_new_slot(
    exam_reservation_db,
):
    exam_reservation_db.add(_reservation("key-a", created_at=NOW - timedelta(hours=2)))
    exam_reservation_db.commit()

    reservation, created = await _reserve()

    assert created is True
    assert reservation.exam_id is None


async def test_same_request_pending_is_in_progress(exam_reservation_db):
    exam_reservation_db.add(
        _reservation("key-a", status=ExamReservationStatus.pending, created_at=NOW)
    )
    exam_reservation_db.commit()

    reservation, created = await _reserve()

    assert created is False
    assert reservation.status == ExamReservationStatus.pending
    assert len(_all(exam_reservation_db)) == 1


@pytest.mark.parametrize(
    "ignored",
    [
        _reservation(
            "key-a",
            status=ExamReservationStatus.pending,
            created_at=NOW - timedelta(hours=1),
        ),
        _reservation("key-b", status=ExamReservationStatus.failed, created_at=NOW),
        _reservation("key-c", created_at=NOW - timedelta(days=8)),
        _reservation("key-d", user_id=2, created_at=NOW),
    ],
    ids=["stale-pending", "failed", "outside-window", "other-user"],
)
async def test_reservations_that_do_not_count(exam_reservation_db, ignored):
    exam_reservation_db.add(ignored)
    exam_reservation_db.commit()

    reservation, created = await _reserve(limit=1)

    assert created is True
    assert reservation.id != ignored.id


async def test_mark_completed_and_failed_update_the_reservation(exam_reservation_db):
    first, _ = await _reserve(request_key="key-1")
    second, _ = await _reserve(request_key="key-2")

    await db.mark_exam_reservation_completed(first.id, "exam-new")
    await db.mark_exam_reservation_failed(second.id)

    exam_reservation_db.expire_all()
    rows = {row.id: row for row in _all(exam_reservation_db)}
    assert rows[first.id].status == ExamReservationStatus.completed
    assert rows[first.id].exam_id == "exam-new"
    assert rows[first.id].completed_at is not None
    assert rows[second.id].status == ExamReservationStatus.failed


async def test_reserve_rejects_naive_datetime():
    with pytest.raises(ValueError, match="window_start must be timezone-aware"):
        await db.reserve_exam_generation(
            1,
            "key-a",
            limit=1,
            window_start=datetime(2026, 11, 1),
            pending_since=PENDING_SINCE,
            reuse_since=REUSE_SINCE,
        )


async def _preview(user_id=1, request_key="key-a", limit=2):
    return await db.preview_exam_generation(
        user_id,
        request_key,
        limit=limit,
        window_start=WINDOW_START,
        pending_since=PENDING_SINCE,
        reuse_since=REUSE_SINCE,
    )


@pytest.mark.parametrize(
    ("rows", "expected_slot_free"),
    [
        ([], True),
        ([_reservation("key-1"), _reservation("key-2")], False),
    ],
    ids=["free", "at-limit"],
)
async def test_preview_reports_slot_without_writing_or_locking(
    exam_reservation_db, rows, expected_slot_free
):
    exam_reservation_db.add_all(rows)
    exam_reservation_db.commit()

    assert await _preview() == (None, expected_slot_free)
    assert len(_all(exam_reservation_db)) == len(rows)
    db._lock_exam_reservations.assert_not_awaited()


async def test_preview_returns_same_request_in_progress(exam_reservation_db):
    exam_reservation_db.add(
        _reservation("key-a", status=ExamReservationStatus.pending, created_at=NOW)
    )
    exam_reservation_db.commit()

    existing, slot_free = await _preview()

    assert existing.status == ExamReservationStatus.pending
    assert slot_free is False
