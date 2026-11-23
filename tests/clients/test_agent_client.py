from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE, PreparationFailed
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


@pytest.mark.asyncio
async def test_generate_response_requires_user_id() -> None:
    agent_client = AgentClient()
    user = User(name="No ID User", wa_id="255700000002")

    with pytest.raises(ValueError, match="must have an ID"):
        await agent_client.generate_response(
            user=user,
            message=_make_user_message("hello"),
        )


def _save_history(session, *contents: str) -> list[Message]:
    """Persist visible user messages in arrival order."""
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    messages = [
        Message(
            user_id=1,
            role=MessageRole.user,
            content=content,
            is_present_in_conversation=True,
            created_at=start + timedelta(seconds=index),
        )
        for index, content in enumerate(contents)
    ]
    session.add_all(messages)
    session.commit()
    return messages


@pytest.mark.asyncio
async def test_text_sent_while_photo_is_prepared_is_answered_with_it(
    message_history_session,
) -> None:
    """The text waits for the photo and both reach the agent in one turn."""
    client = AgentClient()
    user = _make_user()
    photo, text = _save_history(
        message_history_session, "Image not yet interpreted.", "answer question 1 only"
    )
    text_responses = []

    async def prepare() -> None:
        # The teacher's text arrives while the photo is still being read
        text_responses.append(await client.generate_response(user, text))
        photo.content = "The teacher sent a photo. 1. x + 2 = 3"

    with patch(
        "app.clients.agent_client.async_llm_request",
        AsyncMock(return_value=AIMessage(content="x = 1")),
    ) as mock_request:
        response = await client.generate_response(user, photo, prepare=prepare)

    assert text_responses == [BUFFERED_RESPONSE]
    mock_request.assert_awaited_once()
    payload = mock_request.await_args.kwargs["messages"]
    assert [(message.type, message.content) for message in payload[1:]] == [
        ("human", "The teacher sent a photo. 1. x + 2 = 3"),
        ("human", "answer question 1 only"),
    ]
    assert isinstance(response, list)
    assert response[-1].content == "x = 1"
    # The finished turn leaves no idle processor behind
    assert user.id not in client._processors


@pytest.mark.asyncio
async def test_failed_preparation_with_nothing_else_skips_the_agent(
    message_history_session,
) -> None:
    client = AgentClient()
    (photo,) = _save_history(message_history_session, "Image not yet interpreted.")

    with patch("app.clients.agent_client.async_llm_request", AsyncMock()) as request:
        response = await client.generate_response(
            _make_user(), photo, prepare=AsyncMock(return_value="image_unreadable")
        )

    assert response == PreparationFailed("image_unreadable")
    request.assert_not_awaited()
    assert 1 not in client._processors


@pytest.mark.asyncio
async def test_failed_preparation_still_answers_text_buffered_meanwhile(
    message_history_session,
) -> None:
    client = AgentClient()
    user = _make_user()
    photo, text = _save_history(
        message_history_session, "Image not yet interpreted.", "what is a map scale?"
    )

    async def prepare() -> str:
        await client.generate_response(user, text)
        return "image_unreadable"

    with patch(
        "app.clients.agent_client.async_llm_request",
        AsyncMock(return_value=AIMessage(content="A map scale is...")),
    ) as mock_request:
        response = await client.generate_response(user, photo, prepare=prepare)

    assert isinstance(response, list)
    assert response[-1].content == "A map scale is..."
    mock_request.assert_awaited_once()
    # The photo is dropped from the batch; only the text is the new message
    payload = mock_request.await_args.kwargs["messages"]
    assert payload[-1].content == "what is a map scale?"


@pytest.mark.asyncio
async def test_photo_arriving_during_another_turn_is_prepared_before_buffering() -> (
    None
):
    """The running turn must never pick up the photo before it was read."""
    client = AgentClient()
    user = _make_user()
    photo = _make_user_message("Image not yet interpreted.")

    async def prepare() -> None:
        photo.content = "The teacher sent a photo. 1. x + 2 = 3"

    processor = client._get_processor(user.id)
    await processor.lock.acquire()
    try:
        response = await client.generate_response(user, photo, prepare=prepare)
        pending = processor.get_pending_messages()
    finally:
        processor.lock.release()
        processor.clear_messages()
        client._cleanup_processor(user.id)

    assert response is BUFFERED_RESPONSE
    assert [message.content for message in pending] == [
        "The teacher sent a photo. 1. x + 2 = 3"
    ]


@pytest.mark.asyncio
async def test_failed_photo_during_another_turn_is_not_buffered() -> None:
    client = AgentClient()
    user = _make_user()

    processor = client._get_processor(user.id)
    await processor.lock.acquire()
    try:
        response = await client.generate_response(
            user,
            _make_user_message("Image not yet interpreted."),
            prepare=AsyncMock(return_value="image_disabled"),
        )
        pending = processor.get_pending_messages()
    finally:
        processor.lock.release()
        client._cleanup_processor(user.id)

    assert response == PreparationFailed("image_disabled")
    assert pending == []
