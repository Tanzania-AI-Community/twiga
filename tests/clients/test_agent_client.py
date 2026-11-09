from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients import client_base
from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE, GeneratedResponse
from app.database import db
from app.database.enums import MessageRole
from app.database.models import Message, User
from app.services.conversation_summary_service import ConversationSummaryService
from tests.database import conversation_summary_fixtures as summary_fixtures


@pytest.fixture
def message_history_session(monkeypatch):
    """Execute the real history query locally without a PostgreSQL connection."""
    engine = create_engine("sqlite:///:memory:")
    Message.__table__.create(engine)
    try:
        with Session(engine) as session:
            async_session = AsyncMock()
            async_session.execute.side_effect = session.execute

            @asynccontextmanager
            async def get_session():
                yield async_session

            monkeypatch.setattr(db, "get_session", get_session)

            async def summary_snapshot(user_id):
                rows = (
                    session.query(Message)
                    .filter(Message.user_id == user_id)
                    .order_by(Message.created_at, Message.id)
                    .all()
                )
                sources = tuple(
                    db.SummarySource(m.id, m.role, m.content or "", m.created_at)
                    for m in rows
                    if db.is_summary_source_eligible(m)
                )
                return db.ConversationSummarySnapshot(
                    user_id, None, 1, "", 0, 0, (), frozenset(), sources
                )

            monkeypatch.setattr(
                db, "get_conversation_summary_snapshot", summary_snapshot
            )
            monkeypatch.setattr(
                client_base,
                "conversation_summary_service",
                ConversationSummaryService(counter=len),
            )
            yield session
    finally:
        engine.dispose()


def _make_user() -> User:
    return User(id=1, name="Test User", wa_id="255700000001")


def _make_user_message(content: str) -> Message:
    return Message(user_id=1, role=MessageRole.user, content=content)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_content", "visible_content"),
    [
        (
            "An explanation. {{TWIGA_CITATION:123}}",
            "An explanation. [1]\n\nSources:\n[1] Biology textbook",
        ),
        (
            'Here is your exam. {{TWIGA_EXAM_DELIVERY:{"exam_id":"exam-1"}}}',
            "Here is your exam.",
        ),
    ],
)
async def test_llm_request_contains_visible_assistant_response_without_raw_duplicate(
    message_history_session, raw_content, visible_content
) -> None:
    client = AgentClient()
    user = _make_user()
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    messages = [
        Message(
            user_id=user.id,
            role=MessageRole.user,
            content="Help me prepare a lesson.",
            is_present_in_conversation=True,
        ),
        Message(user_id=user.id, role=MessageRole.assistant, content=raw_content),
        Message(
            user_id=user.id,
            role=MessageRole.assistant,
            content=visible_content,
            is_present_in_conversation=True,
        ),
        Message(
            user_id=user.id,
            role=MessageRole.user,
            content="Tell me more.",
            is_present_in_conversation=True,
        ),
    ]
    for index, message in enumerate(messages):
        message.created_at = start + timedelta(seconds=index)
    message_history_session.add_all(messages)
    message_history_session.commit()

    with patch(
        "app.clients.agent_client.async_llm_request",
        AsyncMock(return_value=AIMessage(content="More detail.")),
    ) as mock_request:
        response = await client.generate_response(user, messages[-1])

    assert isinstance(response, GeneratedResponse)
    mock_request.assert_awaited_once()
    payload = mock_request.await_args.kwargs["messages"]
    assert [(message.type, message.content) for message in payload[1:]] == [
        ("human", "Help me prepare a lesson."),
        ("ai", visible_content),
        ("human", "Tell me more."),
    ]
    assert payload[0].type == "system"


@pytest.mark.asyncio
async def test_repeated_tool_calls_notify_the_user_only_once(
    message_history_session,
) -> None:
    """A tool called in several agent iterations is announced once, not once per call."""
    client = AgentClient()
    user = _make_user()
    incoming_message = Message(
        user_id=user.id,
        role=MessageRole.user,
        content="Create 10 questions on trigonometry.",
        is_present_in_conversation=True,
    )
    incoming_message.created_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    message_history_session.add(incoming_message)
    message_history_session.commit()

    def _exercise_call(call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "generate_exercise",
                    "args": {"query": "trigonometry question", "class_id": 21},
                    "id": call_id,
                }
            ],
        )

    llm_responses = [
        _exercise_call("call_1"),
        _exercise_call("call_2"),
        AIMessage(content="Here are your questions."),
    ]

    with (
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(side_effect=llm_responses),
        ),
        patch.object(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content="A question.",
                        tool_call_id="call_1",
                        tool_name="generate_exercise",
                    )
                ]
            ),
        ),
        patch.object(
            client, "_tool_call_notification", AsyncMock()
        ) as mock_notification,
    ):
        response = await client.generate_response(user, incoming_message)

    assert isinstance(response, GeneratedResponse)
    mock_notification.assert_awaited_once_with(user, "generate_exercise")


@pytest.mark.asyncio
async def test_generate_response_returns_buffered_when_processor_is_locked() -> None:
    agent_client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("second quick message")

    processor = agent_client._get_processor(user.id)
    await processor.lock.acquire()

    try:
        response = await agent_client.generate_response(
            user=user,
            message=incoming_message,
        )
    finally:
        processor.lock.release()
        processor.clear_messages()
        agent_client._cleanup_processor(user.id)

    assert response is BUFFERED_RESPONSE


@pytest.mark.asyncio
async def test_generate_response_requires_user_id() -> None:
    agent_client = AgentClient()
    user = User(name="No ID User", wa_id="255700000002")

    with pytest.raises(ValueError, match="must have an ID"):
        await agent_client.generate_response(
            user=user,
            message=_make_user_message("hello"),
        )


summary_pg = summary_fixtures.summary_pg
summary_pg_schema = summary_fixtures.summary_pg_schema


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,current_text", [(30, "new"), (31, "new"), (1, "🌍" * 66001)]
)
async def test_real_preparation_payload_and_envelope(
    summary_pg, monkeypatch, count, current_text
):
    from app.clients import client_base
    from app.services import conversation_summary_service as summary_mod
    from tests.services.test_conversation_summary_service import current, source

    factory, _ = summary_pg
    sources = tuple(
        source(i, current_text if i == count else f"older-{i}")
        for i in range(1, count + 1)
    )
    async with factory.begin() as session:
        session.add(_make_user())
        await session.flush()
        session.add_all(current(s) for s in sources)
    monkeypatch.setattr(
        client_base,
        "conversation_summary_service",
        summary_mod.ConversationSummaryService(counter=len),
    )
    summary_call = AsyncMock(return_value=AIMessage(content="Older history summary"))
    monkeypatch.setattr(summary_mod, "async_llm_request", summary_call)
    client = AgentClient()
    think = AsyncMock(return_value=AIMessage(content="Answer"))
    monkeypatch.setattr(client, "_think", think)
    result = await client.generate_response(_make_user(), current(sources[-1]))
    assert isinstance(result, GeneratedResponse)
    payload = think.await_args.kwargs["api_messages"]
    assert payload[0].type == "system"
    assert payload[-1].content == current_text
    assert sum(m.content == current_text for m in payload[1:]) == 1
    assert result.summary_context.current_user_message_ids == (count,)
    assert result.summary_context.accepted_source_ids == tuple(range(1, count + 1))
    assert result.summary_context.hard_protected is (count == 31 or count == 1)
    assert summary_call.await_count == int(count == 31)
    if count == 31:
        assert "Older history summary" in payload[1].content
        assert len(payload) == 3
    else:
        assert len(payload) == count + 1


@pytest.mark.asyncio
async def test_input_during_preparation_is_rerun_and_hard_protection_survives(
    monkeypatch,
):
    from app.clients import client_base
    from app.services import conversation_summary_service as summary_mod
    from tests.services.test_conversation_summary_service import (
        current,
        snapshot,
        source,
    )

    client = AgentClient()
    user = _make_user()
    first, second = current(source(1)), current(source(2))
    seen = []

    async def prepare(user_id, captured):
        seen.append(tuple(m.id for m in captured))
        if len(seen) == 1:
            assert await client.generate_response(user, second) is BUFFERED_RESPONSE
        sources = tuple(summary_mod.message_source(m) for m in captured)
        return summary_mod.PreparedConversation(
            snapshot(sources),
            summary_mod.SummaryRequestContext(
                user_id,
                tuple(m.id for m in captured),
                tuple(m.id for m in captured),
                len(seen) == 1,
            ),
        )

    monkeypatch.setattr(client_base.conversation_summary_service, "prepare", prepare)
    think = AsyncMock(return_value=AIMessage(content="Final accepted reply"))
    monkeypatch.setattr(client, "_think", think)
    response = await client.generate_response(user, first)
    assert isinstance(response, GeneratedResponse)
    assert seen == [(1,), (1, 2)] and think.await_count == 1
    assert response.summary_context.current_user_message_ids == (1, 2)
    assert response.summary_context.hard_protected
    assert not client._get_processor(1).has_messages


@pytest.mark.asyncio
async def test_input_during_generation_discards_old_output(monkeypatch):
    from app.clients import client_base
    from app.services import conversation_summary_service as summary_mod
    from tests.services.test_conversation_summary_service import (
        current,
        snapshot,
        source,
    )

    client = AgentClient()
    user = _make_user()
    first, second = current(source(1)), current(source(2))

    async def prepare(user_id, captured):
        return summary_mod.PreparedConversation(
            snapshot(tuple(summary_mod.message_source(m) for m in captured)),
            summary_mod.SummaryRequestContext(
                user_id, tuple(m.id for m in captured), tuple(m.id for m in captured)
            ),
        )

    count = 0

    async def think(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            assert await client.generate_response(user, second) is BUFFERED_RESPONSE
        return AIMessage(content=f"reply-{count}")

    monkeypatch.setattr(client_base.conversation_summary_service, "prepare", prepare)
    monkeypatch.setattr(client, "_think", think)
    response = await client.generate_response(user, first)
    assert isinstance(response, GeneratedResponse)
    assert count == 2 and response.messages[-1].content == "reply-2"
    assert response.summary_context.accepted_source_ids == (1, 2)


@pytest.mark.asyncio
async def test_hard_preparation_failure_never_calls_agent(monkeypatch):
    from app.clients import client_base
    from app.services.conversation_summary_service import SummaryError
    from tests.services.test_conversation_summary_service import current, source

    client = AgentClient()
    monkeypatch.setattr(
        client_base.conversation_summary_service,
        "prepare",
        AsyncMock(side_effect=SummaryError("cannot reduce older sources")),
    )
    think = AsyncMock()
    monkeypatch.setattr(client, "_think", think)
    assert await client.generate_response(_make_user(), current(source(1))) is None
    think.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("competing_write", [False, True])
async def test_hard_compaction_and_stale_snapshot_use_only_committed_context(
    summary_pg, monkeypatch, competing_write
):
    from app.clients import client_base
    from app.services import conversation_summary_service as summary_mod
    from tests.services.test_conversation_summary_service import current, source

    factory, _ = summary_pg
    async with factory.begin() as session:
        session.add(_make_user())
        await session.flush()
        session.add_all(current(source(i)) for i in range(1, 37))
    for i in range(1, 6):
        await db.commit_conversation_summary(
            db.SummaryUpdate(1, i - 1 if i > 1 else None, i, (i,), "b" * 15000, 15000)
        )
    monkeypatch.setattr(
        client_base,
        "conversation_summary_service",
        summary_mod.ConversationSummaryService(counter=len),
    )
    monkeypatch.setattr(
        summary_mod,
        "async_llm_request",
        AsyncMock(return_value=AIMessage(content="candidate summary")),
    )
    original_write = db.commit_conversation_summary
    raced = False

    async def write(candidate):
        nonlocal raced
        if competing_write and not raced:
            raced = True
            assert (
                await original_write(
                    db.SummaryUpdate(
                        1,
                        5,
                        6,
                        (6,),
                        "peer batch",
                        10,
                        db.RollupUpdate((1,), "peer older", 10),
                    )
                )
                is db.SummaryWriteResult.COMMITTED
            )
        return await original_write(candidate)

    monkeypatch.setattr(db, "commit_conversation_summary", write)
    client = AgentClient()
    think = AsyncMock(return_value=AIMessage(content="answer"))
    monkeypatch.setattr(client, "_think", think)
    response = await client.generate_response(_make_user(), current(source(36)))
    assert (
        isinstance(response, GeneratedResponse)
        and response.summary_context.hard_protected
    )
    payload = think.await_args.kwargs["api_messages"]
    texts = [m.content for m in payload]
    assert texts[-1] == "hello"
    stored = await db.get_conversation_summary_snapshot(1)
    assert stored.compacted_through_batch == 1
    assert stored.older_history_summary == payload[1].content
    assert [b.summary_text for b in stored.active_batches] == texts[2:7]
    assert len(stored.active_batches) == 5
    if competing_write:
        assert "peer batch" in texts and not any(
            "candidate summary" in text for text in texts
        )
        assert [s.id for s in stored.pending_sources] == list(range(7, 37))
    else:
        assert any("candidate summary" in text for text in texts)
        assert [s.id for s in stored.pending_sources] == [36]
