import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.database import db
from app.database.enums import MessageRole
from app.database.models import (
    ConversationSummaryBatch,
    ConversationSummaryState,
    Message,
    User,
)
from tests.database import conversation_summary_fixtures as summary_fixtures

summary_pg = summary_fixtures.summary_pg
summary_pg_schema = summary_fixtures.summary_pg_schema


START = datetime(2026, 10, 25, tzinfo=timezone.utc)


def message(message_id=1, user_id=1, **kwargs):
    fields = dict(
        id=message_id,
        user_id=user_id,
        role=MessageRole.user,
        content=f"source {message_id}",
        is_present_in_conversation=True,
        created_at=START + timedelta(seconds=message_id),
    )
    fields.update(kwargs)
    return Message(**fields)


def candidate(ids, *, user_id=1, version=None, sequence=1, tokens=10, rollup=None):
    return db.SummaryUpdate(
        user_id, version, sequence, tuple(ids), "[summary]", tokens, rollup
    )


def test_summary_models_register_and_default_to_empty_rollup():
    state = ConversationSummaryState(user_id=1)
    assert SQLModel.metadata.tables["conversation_summary_state"] is state.__table__
    assert "conversation_summary_batches" in SQLModel.metadata.tables
    assert (
        state.older_history_summary,
        state.token_count,
        state.compacted_through_batch,
        state.version,
    ) == ("", 0, 0, 0)
    assert state.updated_at.utcoffset() == timedelta(0)
    for table in (
        ConversationSummaryState.__table__,
        ConversationSummaryBatch.__table__,
    ):
        assert {fk.ondelete for fk in table.foreign_keys} == {"CASCADE"}
        assert {fk.target_fullname for fk in table.foreign_keys} == {"users.id"}
    assert {r.value for r in MessageRole} == {"system", "user", "assistant", "tool"}


@pytest.mark.parametrize(
    "changes,eligible",
    [
        ({}, True),
        ({"content": ""}, True),
        ({"content": None}, True),
        ({"role": MessageRole.system}, True),
        ({"role": MessageRole.assistant}, True),
        ({"is_present_in_conversation": False}, False),
        ({"role": MessageRole.tool}, False),
        ({"role": MessageRole.assistant, "tool_calls": [{"id": "call"}]}, False),
        ({"content": "[FLOW_SENT] lesson"}, False),
        ({"content": "[FLOW_COMPLETED] done"}, False),
        ({"content": "User mentions [FLOW_SENT] in normal text"}, True),
    ],
)
def test_shared_eligibility(changes, eligible):
    assert db.is_summary_source_eligible(message(**changes)) is eligible


def test_model_constraints_and_chronological_endpoints():
    # SQLite verifies portable constraints only; races/isolation are PostgreSQL tests.
    engine = create_engine("sqlite:///:memory:")
    ConversationSummaryState.__table__.create(engine)
    ConversationSummaryBatch.__table__.create(engine)
    try:
        with Session(engine) as session:
            for changes in (
                {"token_count": -1},
                {"token_count": 25001},
                {"version": -1},
                {"compacted_through_batch": -1},
            ):
                session.add(ConversationSummaryState(user_id=1, **changes))
                with pytest.raises(IntegrityError):
                    session.commit()
                session.rollback()
            base = dict(
                user_id=1,
                sequence_number=1,
                first_message_id=9,
                last_message_id=3,
                first_message_at=START,
                last_message_at=START,
                covered_message_ids=[9, 3],
                summary_text="summary",
                token_count=3,
            )
            session.add(ConversationSummaryBatch(**base))
            session.commit()  # Chronological endpoints need not ascend numerically.
            for changes in (
                {"sequence_number": 0},
                {"token_count": -1},
                {"covered_message_ids": []},
                {"first_message_id": 0},
                {"first_message_at": START + timedelta(days=1)},
                {"is_compacted": True},
            ):
                session.add(
                    ConversationSummaryBatch(
                        **(base | {"sequence_number": 2} | changes)
                    )
                )
                with pytest.raises(IntegrityError):
                    session.commit()
                session.rollback()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_is_detached_and_transaction_closes(monkeypatch):
    batch = ConversationSummaryBatch(
        id=5,
        user_id=1,
        sequence_number=2,
        first_message_id=1,
        last_message_id=1,
        first_message_at=START,
        last_message_at=START,
        covered_message_ids=[1],
        summary_text="active",
        token_count=3,
    )
    archived = batch.model_copy(
        update={
            "id": 4,
            "sequence_number": 1,
            "covered_message_ids": [8],
            "is_compacted": True,
            "summary_text": "",
            "token_count": 0,
        }
    )
    state = ConversationSummaryState(
        user_id=1,
        older_history_summary="older",
        token_count=2,
        version=4,
        compacted_through_batch=1,
    )
    results = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    results[1].scalar_one_or_none.return_value = state
    results[2].scalars.return_value.all.return_value = [archived, batch]
    results[3].scalars.return_value.all.return_value = [
        message(2, content=None),
        message(3, role=MessageRole.tool),
    ]
    session = AsyncMock()
    session.execute.side_effect = results
    closed = False

    @asynccontextmanager
    async def scope():
        nonlocal closed
        yield session
        closed = True

    monkeypatch.setattr(db, "get_session", scope)
    snapshot = await db.get_conversation_summary_snapshot(1)
    assert closed
    assert snapshot.covered_message_ids == frozenset({1, 8})
    assert snapshot.next_sequence_number == 3
    assert snapshot.version == 4 and snapshot.older_history_summary == "older"
    assert [b.summary_text for b in snapshot.active_batches] == ["active"]
    assert [(m.id, m.content) for m in snapshot.pending_sources] == [(2, "")]
    with pytest.raises(FrozenInstanceError):
        snapshot.version = 99
    assert "REPEATABLE READ, READ ONLY" in str(
        session.execute.await_args_list[0].args[0]
    )
    query = str(session.execute.await_args_list[-1].args[0])
    assert "json_array_elements_text" in query and "NOT IN" in query
    assert "LIMIT" not in query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update",
    [
        candidate([]),
        candidate([1, 1]),
        candidate([-1]),
        replace(candidate([1]), summary_text=" "),
        candidate([1], tokens=-1),
        candidate([1], tokens=75001),
        candidate([1], rollup=db.RollupUpdate((), "older", 2)),
        candidate([1], rollup=db.RollupUpdate((1,), "older", 25001)),
    ],
)
async def test_invalid_plan_fails_before_opening_a_transaction(monkeypatch, update):
    scope = MagicMock()
    monkeypatch.setattr(db, "get_session", scope)
    with pytest.raises(ValueError):
        await db.commit_conversation_summary(update)
    scope.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, 4])
async def test_stale_result_is_distinct_from_database_failure(monkeypatch, version):
    session = AsyncMock()
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(db, "get_session", scope)
    assert (
        await db.commit_conversation_summary(candidate([1], version=version))
        is db.SummaryWriteResult.STALE
    )
    session.execute.assert_awaited_once()
    session.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await db.commit_conversation_summary(candidate([1], version=version))


async def seed(factory, count=15):
    async with factory.begin() as session:
        session.add_all(
            [
                User(id=1, name="One", wa_id="summary-one"),
                User(id=2, name="Two", wa_id="summary-two"),
            ]
        )
        await session.flush()
        session.add_all([message(i) for i in range(1, count + 1)])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_snapshot_visibility_gaps_ordering_and_user_isolation(
    summary_pg,
):
    factory, _ = summary_pg
    await seed(factory)
    async with factory.begin() as session:
        session.add_all(
            [
                message(16, content="[FLOW_SENT] form"),
                message(17, role=MessageRole.tool),
                message(18, role=MessageRole.assistant, tool_calls=[{"id": "call"}]),
                message(19, is_present_in_conversation=False),
                message(20, user_id=2),
                message(21, created_at=START + timedelta(seconds=1), content=""),
            ]
        )
    snapshot = await db.get_conversation_summary_snapshot(1)
    assert snapshot.version is None
    assert [s.id for s in snapshot.pending_sources] == [1, 21, *range(2, 16)]
    # Exact coverage leaves a gap and a chronologically late/lower ID pending.
    assert (
        await db.commit_conversation_summary(candidate([1, 3]))
        is db.SummaryWriteResult.COMMITTED
    )
    updated = await db.get_conversation_summary_snapshot(1)
    assert updated.covered_message_ids == frozenset({1, 3})
    assert [s.id for s in updated.pending_sources] == [21, 2, *range(4, 16)]
    other = await db.get_conversation_summary_snapshot(2)
    assert other.version is None and [s.id for s in other.pending_sources] == [20]
    async with factory.begin() as session:
        session.add(
            message(22, created_at=START)
        )  # A late committed source before earlier endpoints.
    assert (await db.get_conversation_summary_snapshot(1)).pending_sources[0].id == 22


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_append_compact_retains_coverage_sources_and_activity(
    summary_pg,
):
    factory, _ = summary_pg
    await seed(factory)
    async with factory() as session:
        before = list(
            (await session.execute(select(Message).order_by(Message.id))).scalars()
        )
        archived = [
            (m.id, m.content, m.is_present_in_conversation, m.created_at)
            for m in before
        ]
        user_before = await session.get(User, 1)
        activity = (user_before.updated_at, user_before.last_message_at)
    for i in range(1, 7):
        snapshot = await db.get_conversation_summary_snapshot(1)
        rollup = db.RollupUpdate((1,), "[older rollup]", 3) if i == 6 else None
        result = await db.commit_conversation_summary(
            candidate([i], version=snapshot.version, sequence=i, rollup=rollup)
        )
        assert result is db.SummaryWriteResult.COMMITTED
    after = await db.get_conversation_summary_snapshot(1)
    assert after.version == 6 and after.next_sequence_number == 7
    assert (
        after.compacted_through_batch == 1
        and after.older_history_summary == "[older rollup]"
    )
    assert [b.sequence_number for b in after.active_batches] == [2, 3, 4, 5, 6]
    assert all(
        b.summary_text == "[summary]" and b.token_count == 10
        for b in after.active_batches
    )
    assert after.covered_message_ids == frozenset(range(1, 7))
    assert [s.id for s in after.pending_sources] == list(range(7, 16))
    async with factory() as session:
        rows = list(
            (await session.execute(select(Message).order_by(Message.id))).scalars()
        )
        assert [
            (m.id, m.content, m.is_present_in_conversation, m.created_at) for m in rows
        ] == archived
        user_after = await session.get(User, 1)
        assert (user_after.updated_at, user_after.last_message_at) == activity
        compacted = (
            await session.execute(
                select(ConversationSummaryBatch).where(
                    ConversationSummaryBatch.sequence_number == 1
                )
            )
        ).scalar_one()
        assert (
            compacted.covered_message_ids == [1]
            and compacted.summary_text == ""
            and compacted.token_count == 0
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_postgres_two_independent_writers_have_one_winner(
    summary_pg, monkeypatch, existing
):
    factory, _ = summary_pg
    await seed(factory)
    if existing:
        await db.commit_conversation_summary(candidate([1]))
    snapshot = await db.get_conversation_summary_snapshot(1)
    barrier = asyncio.Barrier(2)
    original = db.get_session

    @asynccontextmanager
    async def simultaneous_sessions():
        async with original() as session:
            # Establish separate physical transactions before racing the CAS.
            await session.execute(text("SELECT 1"))
            await barrier.wait()
            yield session

    monkeypatch.setattr(db, "get_session", simultaneous_sessions)
    update = candidate(
        [2], version=snapshot.version, sequence=snapshot.next_sequence_number
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            db.commit_conversation_summary(update),
            db.commit_conversation_summary(update),
        ),
        timeout=15,
    )
    assert results.count(db.SummaryWriteResult.COMMITTED) == 1
    assert results.count(db.SummaryWriteResult.STALE) == 1
    monkeypatch.setattr(db, "get_session", original)
    after = await db.get_conversation_summary_snapshot(1)
    assert after.version == (snapshot.version or 0) + 1
    assert after.covered_message_ids == ({1, 2} if existing else {2})
    assert len(after.active_batches) == (2 if existing else 1)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_postgres_midwrite_failure_rolls_back_state_and_batch(
    summary_pg, existing
):
    factory, engine = summary_pg
    await seed(factory)
    if existing:
        await db.commit_conversation_summary(candidate([1]))
    before = await db.get_conversation_summary_snapshot(1)

    def fail_batch_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO conversation_summary_batches"):
            raise RuntimeError("induced mid-write failure")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_batch_insert)
    try:
        with pytest.raises(RuntimeError, match="induced mid-write failure"):
            await db.commit_conversation_summary(
                candidate(
                    [2], version=before.version, sequence=before.next_sequence_number
                )
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_batch_insert)
    assert await db.get_conversation_summary_snapshot(1) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_invalid_coverage_prefix_budget_and_unique_sequence(summary_pg):
    factory, _ = summary_pg
    await seed(factory)
    await db.commit_conversation_summary(candidate([1]))
    for invalid in (
        candidate([1], version=1, sequence=2),
        candidate([2], version=1, sequence=3),
        candidate([3, 2], version=1, sequence=2),
        candidate([999], version=1, sequence=2),
        candidate([2], version=1, sequence=2, tokens=75000),
        candidate([2], version=1, sequence=2, rollup=db.RollupUpdate((1,), "older", 3)),
    ):
        with pytest.raises(ValueError):
            await db.commit_conversation_summary(invalid)
        assert (await db.get_conversation_summary_snapshot(1)).version == 1
    async with factory() as session:
        batch = (await session.execute(select(ConversationSummaryBatch))).scalar_one()
        fields = batch.model_dump(exclude={"id"})
    with pytest.raises(IntegrityError):
        async with factory.begin() as session:
            session.add(ConversationSummaryBatch(**fields))
    assert (await db.get_conversation_summary_snapshot(1)).version == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_user_deletion_cascades_only_its_summary_rows(summary_pg):
    factory, _ = summary_pg
    await seed(factory)
    async with factory.begin() as session:
        session.add(message(20, user_id=2))
    await db.commit_conversation_summary(candidate([1]))
    await db.commit_conversation_summary(candidate([20], user_id=2))
    async with factory.begin() as session:
        await session.execute(text("DELETE FROM users WHERE id = 1"))
    snapshot = await db.get_conversation_summary_snapshot(1)
    assert (
        snapshot.version is None
        and not snapshot.active_batches
        and not snapshot.pending_sources
    )
    assert (await db.get_conversation_summary_snapshot(2)).covered_message_ids == {20}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_repeatable_snapshot_survives_concurrent_summary_commit(
    summary_pg, monkeypatch
):
    factory, _ = summary_pg
    await seed(factory)
    original = db.get_session
    reader_started = asyncio.Event()
    continue_reader = asyncio.Event()

    @asynccontextmanager
    async def paused_snapshot():
        async with original() as session:
            execute = session.execute
            calls = 0

            async def pause_after_state(statement, *args, **kwargs):
                nonlocal calls
                result = await execute(statement, *args, **kwargs)
                calls += 1
                if calls == 2:  # State SELECT establishes the repeatable-read snapshot.
                    reader_started.set()
                    await continue_reader.wait()
                return result

            session.execute = pause_after_state
            yield session

    monkeypatch.setattr(db, "get_session", paused_snapshot)
    task = asyncio.create_task(db.get_conversation_summary_snapshot(1))
    try:
        await asyncio.wait_for(reader_started.wait(), timeout=5)
        monkeypatch.setattr(db, "get_session", original)
        assert (
            await db.commit_conversation_summary(candidate([1]))
            is db.SummaryWriteResult.COMMITTED
        )
        continue_reader.set()
        old = await asyncio.wait_for(task, timeout=5)
        assert old.version is None and not old.active_batches
        assert [s.id for s in old.pending_sources] == list(range(1, 16))
        fresh = await db.get_conversation_summary_snapshot(1)
        assert fresh.version == 1 and [s.id for s in fresh.pending_sources] == list(
            range(2, 16)
        )
    finally:
        continue_reader.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_rollup_only_and_late_lower_id_remain_representable(summary_pg):
    factory, _ = summary_pg
    async with factory.begin() as session:
        session.add(User(id=1, name="One", wa_id="rollup-only"))
        await session.flush()
        session.add(
            ConversationSummaryState(
                user_id=1,
                older_history_summary="Older context",
                token_count=2,
                version=1,
                compacted_through_batch=1,
            )
        )
        prior_time = START - timedelta(days=1)
        session.add(message(100, created_at=prior_time))
        session.add(
            ConversationSummaryBatch(
                user_id=1,
                sequence_number=1,
                first_message_id=100,
                last_message_id=100,
                first_message_at=prior_time,
                last_message_at=prior_time,
                covered_message_ids=[100],
                summary_text="",
                token_count=0,
                is_compacted=True,
            )
        )
    empty = await db.get_conversation_summary_snapshot(1)
    assert (
        empty.older_history_summary == "Older context"
        and not empty.active_batches
        and not empty.pending_sources
    )
    # An earlier ID is allocated/inserted in a transaction that commits later.
    async with factory() as delayed:
        async with delayed.begin():
            delayed.add(message(1))
            await delayed.flush()
            async with factory.begin() as other:
                other.add(message(2))
            snap = await db.get_conversation_summary_snapshot(1)
            assert [s.id for s in snap.pending_sources] == [2]
            await db.commit_conversation_summary(candidate([2], version=1, sequence=2))
    final = await db.get_conversation_summary_snapshot(1)
    assert final.covered_message_ids == {100, 2} and [
        s.id for s in final.pending_sources
    ] == [1]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_failed_compaction_rolls_back_archival_and_rollup(summary_pg):
    factory, engine = summary_pg
    await seed(factory)
    for i in range(1, 6):
        snap = await db.get_conversation_summary_snapshot(1)
        await db.commit_conversation_summary(
            candidate([i], version=snap.version, sequence=i)
        )
    before = await db.get_conversation_summary_snapshot(1)

    def fail_batch_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO conversation_summary_batches"):
            raise RuntimeError("induced compaction failure")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_batch_insert)
    try:
        with pytest.raises(RuntimeError, match="induced compaction failure"):
            await db.commit_conversation_summary(
                candidate(
                    [6],
                    version=5,
                    sequence=6,
                    rollup=db.RollupUpdate((1,), "new rollup", 2),
                )
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_batch_insert)
    assert await db.get_conversation_summary_snapshot(1) == before
