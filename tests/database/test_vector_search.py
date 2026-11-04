from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database import db
from app.database.models import Chunk


@pytest.mark.asyncio
async def test_vector_search_truncates_long_chunks_only_after_commit(monkeypatch):
    long_chunk = Chunk(id=1, content="x" * (db.MAX_CHUNK_CONTENT_CHARS + 500))
    short_chunk = Chunk(id=2, content="short")
    lengths_at_commit = []

    result = MagicMock()
    result.scalars.return_value.all.return_value = [long_chunk, short_chunk]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_session():
        yield session
        # Like engine.get_session(), commit when the block exits.
        lengths_at_commit.extend(len(c.content) for c in (long_chunk, short_chunk))

    monkeypatch.setattr(db, "get_session", get_session)
    monkeypatch.setattr(db.embedder, "get_embedding", lambda query: [0.1] * 1024)

    chunks = await db.vector_search("query", n_results=2, where={"resource_id": 1})

    assert lengths_at_commit == [db.MAX_CHUNK_CONTENT_CHARS + 500, len("short")]
    assert [len(c.content) for c in chunks] == [db.MAX_CHUNK_CONTENT_CHARS, 5]
