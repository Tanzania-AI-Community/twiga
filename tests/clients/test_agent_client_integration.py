import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE
from app.database.enums import MessageRole
from app.database.models import Message, User


def _make_user() -> User:
    return User(id=7, name="Integration User", wa_id="255700000007")


def _make_user_message(content: str) -> Message:
    return Message(user_id=7, role=MessageRole.user, content=content)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_generate_response_buffers_without_overlapping_llm_calls() -> (
    None
):
    client = AgentClient()
    user = _make_user()
    llm_call_count = 0

    async def slow_llm_request(*_args, **_kwargs) -> AIMessage:
        nonlocal llm_call_count
        llm_call_count += 1
        if llm_call_count == 1:
            await asyncio.sleep(0.05)
        return AIMessage(content=f"answer-{llm_call_count}")

    with (
        patch(
            "app.clients.client_base.get_user_message_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.clients.agent_client.async_llm_request",
            AsyncMock(side_effect=slow_llm_request),
        ),
    ):
        first_task = asyncio.create_task(
            client.generate_response(user, _make_user_message("first message"))
        )
        await asyncio.sleep(0.01)
        buffered = await client.generate_response(
            user, _make_user_message("second message while busy")
        )
        first_result = await first_task

    assert buffered is BUFFERED_RESPONSE
    assert first_result is not None
    assert llm_call_count >= 1
    assert all(message.role == MessageRole.assistant for message in first_result)
