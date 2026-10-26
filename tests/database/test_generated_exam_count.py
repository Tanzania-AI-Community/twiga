from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import db
from app.database.models import GeneratedExam


@pytest.fixture
def generated_exam_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    GeneratedExam.__table__.create(engine)
    try:
        with Session(engine) as session:
            async_session = AsyncMock()
            async_session.execute.side_effect = session.execute

            @asynccontextmanager
            async def get_session():
                yield async_session

            monkeypatch.setattr(db, "get_session", get_session)
            yield session
    finally:
        engine.dispose()


def _exam(exam_id: str, user_id: int, generated_at: datetime | None):
    return GeneratedExam(
        id=exam_id,
        exam_json={},
        user_id=user_id,
        class_id=1,
        subject="Biology",
        topics=["Cells"],
        generated_at_utc=generated_at,
    )


@pytest.mark.asyncio
async def test_count_generated_exams_filters_user_and_includes_boundary(
    generated_exam_session,
):
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)
    generated_exam_session.add_all(
        [
            _exam("boundary", 1, since),
            _exam("older", 1, since - timedelta(microseconds=1)),
            _exam("other-user", 2, since),
            _exam("missing-time", 1, None),
        ]
    )
    generated_exam_session.commit()

    assert await db.count_generated_exams_since(1, since) == 1
    assert await db.count_generated_exams_since(3, since) == 0


@pytest.mark.asyncio
async def test_count_generated_exams_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        await db.count_generated_exams_since(1, datetime(2026, 9, 1))
