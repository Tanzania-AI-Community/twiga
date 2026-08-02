import pytest

from app.clients.agent_client import AgentClient
from app.clients.client_base import BUFFERED_RESPONSE
from app.database.enums import MessageRole
from app.database.models import Message, User


def _make_user() -> User:
    return User(id=1, name="Test User", wa_id="255700000001")


def _make_user_message(content: str) -> Message:
    return Message(user_id=1, role=MessageRole.user, content=content)


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
