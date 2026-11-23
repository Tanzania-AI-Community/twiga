from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import db
from app.database.models import ExamGenerationReservation


@pytest.fixture
def exam_reservation_db(monkeypatch):
    """In-memory SQLite behind the exam reservation queries.

    SQLite has no advisory locks, so the lock is a no-op here; the real lock is
    covered by tests/integration/test_exam_reservation_lock.py.
    """
    engine = create_engine("sqlite:///:memory:")
    ExamGenerationReservation.__table__.create(engine)
    try:
        with Session(engine) as session:
            async_session = MagicMock()
            async_session.execute = AsyncMock(side_effect=session.execute)
            async_session.flush = AsyncMock(side_effect=session.flush)
            async_session.add = session.add

            @asynccontextmanager
            async def get_session():
                yield async_session
                session.commit()

            monkeypatch.setattr(db, "get_session", get_session)
            monkeypatch.setattr(db, "_lock_exam_reservations", AsyncMock())
            yield session
    finally:
        engine.dispose()
