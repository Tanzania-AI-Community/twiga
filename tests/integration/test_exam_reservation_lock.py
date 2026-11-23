import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlmodel import delete

from app.database import db
from app.database.engine import get_session
from app.database.models import User

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("RUN_DB_INTEGRATION_TESTS"),
        reason="Needs the dev Postgres with migrations applied; set RUN_DB_INTEGRATION_TESTS=1",
    ),
]


@pytest.fixture
async def user_id():
    async with get_session() as session:
        user = User(name="Reservation lock test", wa_id=f"999{uuid4().int % 10**12}")
        session.add(user)
        await session.flush()
        created_id = user.id
    yield created_id
    async with get_session() as session:  # reservations cascade
        await session.execute(delete(User).where(User.id == created_id))


async def test_concurrent_reservations_respect_the_limit(user_id):
    now = datetime.now(timezone.utc)

    async def reserve(request_key: str):
        return await db.reserve_exam_generation(
            user_id,
            request_key,
            limit=1,
            window_start=now - timedelta(days=7),
            pending_since=now - timedelta(minutes=30),
            reuse_since=now - timedelta(minutes=30),
        )

    results = await asyncio.gather(*(reserve(f"key-{i}") for i in range(5)))

    assert sum(created for _, created in results) == 1
