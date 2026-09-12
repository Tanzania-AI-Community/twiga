from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE
from app.database import db
from app.database.enums import MessageRole
from app.database.models import Message, User


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

    assert response is not None
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

    assert response is not None
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
