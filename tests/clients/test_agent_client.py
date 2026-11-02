import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE
from app.config import settings
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


@pytest.mark.asyncio
async def test_generate_response_returns_single_assistant_message_without_tools() -> (
    None
):
    client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("Explain fractions briefly.")

    with (
        patch(
            "app.clients.client_base.get_user_message_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(return_value=AIMessage(content="Fractions represent parts.")),
        ),
    ):
        response = await client.generate_response(user, incoming_message)

    assert response is not None
    assert len(response) == 1
    assert response[0].role == MessageRole.assistant
    assert response[0].content == "Fractions represent parts."


@pytest.mark.asyncio
async def test_generate_response_clears_assistant_content_when_tool_calls_present() -> (
    None
):
    client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("Create a quick quiz.")

    tool_response = AIMessage(
        content="I'll generate that for you.",
        tool_calls=[
            {
                "name": "generate_exercise",
                "args": {"query": "quiz", "class_id": 3},
                "id": "call_tool_1",
            }
        ],
    )
    final_response = AIMessage(content="Here is your quiz.")

    with (
        patch(
            "app.clients.client_base.get_user_message_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(side_effect=[tool_response, final_response]),
        ),
        patch.object(client, "_tool_call_notification", AsyncMock()),
        patch.object(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content="Quiz content.",
                        tool_call_id="call_tool_1",
                        tool_name="generate_exercise",
                    )
                ]
            ),
        ),
    ):
        response = await client.generate_response(user, incoming_message)

    assert response is not None
    assert response[0].content is None
    assert response[0].tool_calls is not None
    assert response[-1].role == MessageRole.assistant
    assert response[-1].content == "Here is your quiz."


@pytest.mark.asyncio
async def test_generate_response_recovers_malformed_tool_call_from_content() -> None:
    client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("Generate one algebra question.")

    malformed_tool_payload = json.dumps(
        {
            "name": "generate_exercise",
            "parameters": {"query": "algebra", "class_id": 2},
        }
    )

    with (
        patch(
            "app.clients.client_base.get_user_message_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(
                side_effect=[
                    AIMessage(content=malformed_tool_payload),
                    AIMessage(content="Done."),
                ]
            ),
        ),
        patch.object(client, "_tool_call_notification", AsyncMock()),
        patch.object(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content="Question text.",
                        tool_call_id="call_recovered",
                        tool_name="generate_exercise",
                    )
                ]
            ),
        ) as mock_process_tool_calls,
    ):
        response = await client.generate_response(user, incoming_message)

    assert response is not None
    mock_process_tool_calls.assert_awaited_once()
    assert mock_process_tool_calls.await_args.args[0][0]["function"]["name"] == (
        "generate_exercise"
    )


@pytest.mark.asyncio
async def test_generate_response_surfaces_tool_execution_errors() -> None:
    client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("Solve this equation.")

    tool_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "solve_equation",
                "args": {"equation": "x + 1 = 2"},
                "id": "call_solve",
            }
        ],
    )

    with (
        patch(
            "app.clients.client_base.get_user_message_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(
                side_effect=[tool_response, AIMessage(content="I could not solve it.")]
            ),
        ),
        patch.object(client, "_tool_call_notification", AsyncMock()),
        patch.object(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=user.id,
                        role=MessageRole.tool,
                        content=json.dumps({"error": "tool failed"}),
                        tool_call_id="call_solve",
                        tool_name="solve_equation",
                    )
                ]
            ),
        ),
    ):
        response = await client.generate_response(user, incoming_message)

    assert response is not None
    tool_messages = [
        message for message in response if message.role == MessageRole.tool
    ]
    assert len(tool_messages) == 1
    assert "error" in tool_messages[0].content


@pytest.mark.asyncio
async def test_generate_response_returns_system_error_when_character_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "message_character_limit", 10)
    client = AgentClient()
    user = _make_user()
    incoming_message = _make_user_message("This message is definitely too long.")

    with patch(
        "app.clients.client_base.get_user_message_history",
        AsyncMock(return_value=[]),
    ):
        response = await client.generate_response(user, incoming_message)

    assert response is not None
    assert len(response) == 1
    assert response[0].role == MessageRole.system
