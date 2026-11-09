"""Opt-in fixtures used only by the Issue #92 persistence tests.

Set ISSUE92_TEST_DATABASE_URL to a disposable PostgreSQL database whose name
begins with issue92_test. Each test owns a fresh schema, dropped on teardown.
Never derive this URL from application settings or run migrations/env.py.
"""

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import db
from app.database.models import (
    ConversationSummaryBatch,
    ConversationSummaryState,
    Message,
    User,
)


@pytest.fixture
def summary_pg_schema():
    raw_url = os.environ.get("ISSUE92_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip(
            "Set ISSUE92_TEST_DATABASE_URL to an explicit disposable issue92_test database"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "issue92_test"
    ):
        pytest.fail(
            "Issue #92 tests require an explicit PostgreSQL database named issue92_test..."
        )
    schema = "issue92_" + uuid4().hex
    engine = create_engine(
        url.set(drivername="postgresql+psycopg2"), poolclass=NullPool
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield url, schema, engine
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


@pytest_asyncio.fixture
async def summary_pg(summary_pg_schema, monkeypatch):
    url, schema, _ = summary_pg_schema
    engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        connect_args={"server_settings": {"search_path": f'"{schema}", public'}},
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            for model in (
                User,
                Message,
                ConversationSummaryState,
                ConversationSummaryBatch,
            ):
                await connection.run_sync(model.__table__.create)

        @asynccontextmanager
        async def session_scope():
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        monkeypatch.setattr(db, "get_session", session_scope)
        yield factory, engine
    finally:
        await engine.dispose()
