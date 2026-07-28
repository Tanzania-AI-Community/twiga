"""Auto-reconnecting asyncpg wrapper for long eval runs.

A full eval run can hold a connection open for hours; server idle timeouts or
network blips then kill it mid-run and every remaining row fails with
"connection is closed" (this lost 35/120 rows of the first full validation
run). This wrapper reconnects and retries once on connection-loss errors.

Backed by a real asyncpg pool (not a single Connection) so concurrent rows —
see the `concurrency` param on run_generation_eval/run_retrieval_eval/
run_abstention_eval — don't serialize on one connection or raise asyncpg's
"another operation is in progress" error. The pool already discards and
replaces broken connections on its own, so the retry-once wrapper mainly
covers transient errors surfaced through fetch/fetchrow.

Only the query surface the eval code uses (fetch / fetchrow) is exposed.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_RECONNECT_ERRORS = (
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.InterfaceError,
    ConnectionResetError,
)


class ReconnectingConnection:
    """Drop-in replacement for an asyncpg.Connection in the eval pipelines,
    pool-backed so multiple rows can query concurrently."""

    def __init__(self, dsn: str, ssl: Any = "require", min_size: int = 2, max_size: int = 10):
        self._dsn = dsn
        self._ssl = ssl
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def _ensure(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn, ssl=self._ssl, min_size=self._min_size, max_size=self._max_size,
            )
        return self._pool

    async def _run(self, method: str, *args: Any) -> Any:
        try:
            pool = await self._ensure()
            return await getattr(pool, method)(*args)
        except _RECONNECT_ERRORS as e:
            logger.warning("DB pool error (%s) — recreating pool and retrying", e)
            if self._pool is not None:
                await self._pool.close()
            self._pool = None
            pool = await self._ensure()
            return await getattr(pool, method)(*args)

    async def fetch(self, *args: Any) -> Any:
        return await self._run("fetch", *args)

    async def fetchrow(self, *args: Any) -> Any:
        return await self._run("fetchrow", *args)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
