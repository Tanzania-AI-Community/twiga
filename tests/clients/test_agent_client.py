import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients.agent_client import AgentClient
from app.clients.agent_modes import AgentMode
from app.clients.client_base import BUFFERED_RESPONSE, PreparationFailed
from app.database import db
from app.database.enums import GradeLevel, MessageRole, SubjectName
from app.database.models import Class, Message, Subject, TeacherClass, User
from app.services.profile import Catalog
from app.tools.registry import CURRICULUM_TOOLS, PROFILE_TOOLS, ToolName


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


# --- agent modes and profile updates -----------------------------------------

_PROFILE_CATALOG = Catalog(
    classes={SubjectName.geography: {GradeLevel.os1: 101, GradeLevel.os2: 102}}
)


def _tool_names(request_call) -> set[str]:
    return {tool["function"]["name"] for tool in request_call.kwargs["tools"]}


def _class_id_enum(tools: list) -> list:
    search = next(
        tool
        for tool in tools
        if tool["function"]["name"] == ToolName.search_knowledge.value
    )
    return search["function"]["parameters"]["properties"]["class_id"]["enum"]


def _geography_form_2_teacher() -> User:
    return User(
        id=1,
        wa_id="255700000001",
        name="Luke Nuru",
        class_info={"geography": ["os2"]},
        taught_classes=[
            TeacherClass(
                teacher_id=1,
                class_id=102,
                class_=Class(
                    id=102,
                    subject_id=1,
                    grade_level=GradeLevel.os2,
                    subject_=Subject(id=1, name=SubjectName.geography),
                ),
            )
        ],
    )


@pytest.mark.asyncio
async def test_profile_change_refreshes_prompt_and_class_ids_within_the_turn(
    message_history_session,
) -> None:
    client = AgentClient()
    user = _make_user()
    (incoming,) = _save_history(
        message_history_session, "Call me Luke Nuru, I teach Form 2 geography"
    )
    llm_responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": ToolName.update_my_classes.value,
                    "args": {
                        "action": "add",
                        "classes": [{"subject": "geography", "forms": ["Form 2"]}],
                    },
                    "id": "call_1",
                }
            ],
        ),
        AIMessage(content="You now teach Geography (Form 2)."),
    ]

    # api_messages is updated in place, so record what each call actually saw
    seen: list[tuple[str, list]] = []

    async def fake_llm_request(**kwargs):
        seen.append((kwargs["messages"][0].content, kwargs["tools"]))
        return llm_responses[len(seen) - 1]

    with (
        patch("app.clients.agent_client.async_llm_request", fake_llm_request),
        patch(
            "app.clients.agent_client.available_catalog",
            AsyncMock(return_value=_PROFILE_CATALOG),
        ),
        patch.object(
            client.tool_manager,
            "process_tool_calls",
            AsyncMock(
                return_value=[
                    Message(
                        user_id=1,
                        role=MessageRole.tool,
                        content='{"ok": true}',
                        tool_call_id="call_1",
                        tool_name=ToolName.update_my_classes.value,
                    )
                ]
            ),
        ),
        patch(
            "app.clients.agent_client.db.get_user_by_waid",
            AsyncMock(return_value=_geography_form_2_teacher()),
        ),
    ):
        response = await client.generate_response(user, incoming)

    assert isinstance(response, list)
    (first_prompt, first_tools), (second_prompt, second_tools) = seen
    assert "<teacher_name>Test User</teacher_name>" in first_prompt
    assert "<teacher_name>Luke Nuru</teacher_name>" in second_prompt
    assert "Geography" in second_prompt
    assert _class_id_enum(first_tools) == []
    assert _class_id_enum(second_tools) == [102]


@pytest.mark.asyncio
async def test_onboarding_mode_offers_only_profile_tools(
    message_history_session,
) -> None:
    client = AgentClient()
    (incoming,) = _save_history(message_history_session, "Hello")

    with (
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(return_value=AIMessage(content="What should I call you?")),
        ) as mock_request,
        patch(
            "app.clients.agent_client.available_catalog",
            AsyncMock(return_value=_PROFILE_CATALOG),
        ),
    ):
        await client.generate_response(
            _make_user(), incoming, mode=AgentMode.onboarding
        )

    request = mock_request.await_args
    assert _tool_names(request) == {tool.value for tool in PROFILE_TOOLS}
    assert "Still missing: classes" in request.kwargs["messages"][0].content
    assert request.kwargs["metadata"]["mode"] == "onboarding"


@pytest.mark.asyncio
async def test_catalog_failure_keeps_teaching_tools_and_drops_profile_tools(
    message_history_session,
) -> None:
    client = AgentClient()
    (incoming,) = _save_history(message_history_session, "Explain erosion")

    with (
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(return_value=AIMessage(content="Erosion is...")),
        ) as mock_request,
        patch(
            "app.clients.agent_client.available_catalog",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
    ):
        response = await client.generate_response(_make_user(), incoming)

    assert isinstance(response, list)
    assert _tool_names(mock_request.await_args) == {
        tool.value for tool in CURRICULUM_TOOLS
    }


@pytest.mark.asyncio
async def test_onboarding_mode_refuses_tools_recovered_from_free_text(
    message_history_session,
) -> None:
    """A curriculum tool smuggled in as text must not run during onboarding."""
    client = AgentClient()
    (incoming,) = _save_history(message_history_session, "Explain erosion")
    smuggled = AIMessage(
        content=json.dumps(
            {
                "name": ToolName.search_knowledge.value,
                "parameters": {"search_phrase": "erosion", "class_id": 1},
            }
        )
    )
    search_knowledge = AsyncMock()

    with (
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(side_effect=[smuggled, AIMessage(content="Which subjects?")]),
        ),
        patch(
            "app.clients.agent_client.available_catalog",
            AsyncMock(return_value=_PROFILE_CATALOG),
        ),
        patch(
            "app.tools.tool_manager.TOOL_FUNCTION_MAP",
            {ToolName.search_knowledge.value: search_knowledge},
        ),
    ):
        response = await client.generate_response(
            _make_user(), incoming, mode=AgentMode.onboarding
        )

    search_knowledge.assert_not_awaited()
    assert isinstance(response, list)
    tool_message = next(m for m in response if m.role == MessageRole.tool)
    assert json.loads(tool_message.content) == {"error": "tool_not_available"}
