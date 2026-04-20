from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.clients.llm_client import LLMClient, _prepare_message_for_together
from app.config import Prompt
from app.database.enums import MessageRole
from app.database.models import Message, User


def _make_user() -> User:
    return User(id=1, name="Test User", wa_id="255700000001")


def _make_user_message(content: str) -> Message:
    return Message(user_id=1, role=MessageRole.user, content=content)


def test_prepare_message_for_together_without_tool_calls() -> None:
    message = AIMessage(content="hello")

    result = _prepare_message_for_together(message)

    assert isinstance(result, AIMessage)
    assert result.content == "hello"


def test_prepare_message_for_together_with_tool_calls() -> None:
    message = AIMessage(
        content="Find an answer",
        tool_calls=[
            {
                "id": "call_1",
                "name": "search_knowledge",
                "args": {"query": "What is the capital of Tanzania?"},
            }
        ],
    )

    result = _prepare_message_for_together(message)

    assert isinstance(result, HumanMessage)
    tool_calls = result.additional_kwargs["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["type"] == "tool_call"
    assert tool_calls[0]["function"]["name"] == "search_knowledge"
    assert (
        tool_calls[0]["function"]["arguments"]
        == '{"query": "What is the capital of Tanzania?"}'
    )


def test_format_messages_happy_path() -> None:
    llm_client = LLMClient()
    user = _make_user()

    database_messages = [
        Message(user_id=1, role=MessageRole.user, content="hello"),
        Message(user_id=1, role=MessageRole.assistant, content="hi"),
    ]
    new_messages = [Message(user_id=1, role=MessageRole.user, content="new question")]

    result = llm_client._format_messages(
        new_messages=new_messages,
        database_messages=database_messages,
        user=user,
        prompt=Prompt.TWIGA_SYSTEM,
    )

    assert result[0]["role"] == MessageRole.system
    assert isinstance(result[0]["content"], str)
    assert result[0]["content"]
    assert result[-1]["role"] == MessageRole.user.value
    assert result[-1]["content"] == "new question"


def test_format_messages_raises_when_history_shorter_than_new_messages() -> None:
    llm_client = LLMClient()
    user = _make_user()

    database_messages = [Message(user_id=1, role=MessageRole.user, content="only one")]
    new_messages = [
        Message(user_id=1, role=MessageRole.user, content="first"),
        Message(user_id=1, role=MessageRole.assistant, content="second"),
    ]

    with pytest.raises(Exception, match="Unusual message count scenario detected"):
        llm_client._format_messages(
            new_messages=new_messages,
            database_messages=database_messages,
            user=user,
            prompt=Prompt.TWIGA_SYSTEM,
        )


@pytest.mark.asyncio
async def test_generate_response_requires_user_id() -> None:
    llm_client = LLMClient()
    user = User(name="No ID User", wa_id="255700000002")

    with pytest.raises(ValueError, match="must have an ID"):
        await llm_client.generate_response(
            user=user,
            message=_make_user_message("hello"),
        )


@pytest.mark.asyncio
async def test_generate_response_without_tool_calls() -> None:
    llm_client = LLMClient()
    user = _make_user()
    incoming_message = _make_user_message("hello")

    with (
        patch.object(
            llm_client,
            "_preprocess_messages",
            AsyncMock(return_value=([HumanMessage(content="hello")], None)),
        ),
        patch.object(
            llm_client.tool_manager,
            "get_tools_metadata_from_registry",
            return_value=[],
        ),
        patch.object(
            llm_client.tool_manager,
            "extract_tool_calls",
            return_value=[],
        ),
        patch(
            "app.clients.llm_client.async_llm_request",
            new=AsyncMock(
                return_value=AIMessage(content="Totally real robot response")
            ),
        ) as mock_request,
    ):
        response = await llm_client.generate_response(
            user=user, message=incoming_message
        )

    assert response is not None
    assert len(response) == 1
    assert response[0].role == MessageRole.assistant
    assert response[0].content == "Totally real robot response"
    assert response[0].tool_calls is None
    assert mock_request.await_count == 1


@pytest.mark.asyncio
async def test_generate_response_with_tool_calls_adds_final_answer() -> None:
    llm_client = LLMClient()
    user = _make_user()
    incoming_message = _make_user_message("What is the capital of Tanzania?")

    initial_response = AIMessage(
        content="Tool call needed",
        tool_calls=[
            {
                "id": "call_123",
                "name": "search_knowledge",
                "args": {"query": "What is the capital of Tanzania?", "class_id": 1},
            }
        ],
    )
    final_response = AIMessage(content="The capital of Tanzania is Dodoma.")

    extracted_tool_calls = [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "arguments": '{"query": "What is the capital of Tanzania?", "class_id": 1}',
            },
        }
    ]

    tool_response = Message(
        user_id=1,
        role=MessageRole.tool,
        content="The capital of Tanzania is Dodoma.",
        tool_call_id="call_123",
        tool_name="search_knowledge",
        source_chunk_ids=[101, 101, 202],
    )

    with (
        patch.object(
            llm_client,
            "_preprocess_messages",
            AsyncMock(return_value=([HumanMessage(content="question")], None)),
        ),
        patch.object(
            llm_client.tool_manager,
            "get_tools_metadata_from_registry",
            return_value=[],
        ),
        patch.object(
            llm_client.tool_manager,
            "extract_tool_calls",
            return_value=extracted_tool_calls,
        ),
        patch.object(
            llm_client.tool_manager,
            "process_tool_calls",
            new=AsyncMock(return_value=[tool_response]),
        ),
        patch.object(
            llm_client,
            "_tool_call_notification",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.clients.llm_client.async_llm_request",
            new=AsyncMock(side_effect=[initial_response, final_response]),
        ) as mock_request,
    ):
        response = await llm_client.generate_response(
            user=user, message=incoming_message
        )

    assert response is not None
    assert len(response) == 3
    assert response[0].role == MessageRole.assistant
    assert response[0].content is None
    assert response[0].tool_calls is not None
    assert response[1].role == MessageRole.tool
    assert response[2].role == MessageRole.assistant
    assert response[2].content == "The capital of Tanzania is Dodoma."
    assert response[2].source_chunk_ids == [101, 202]
    assert mock_request.await_count == 2
