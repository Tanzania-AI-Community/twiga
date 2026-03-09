from unittest.mock import AsyncMock, patch

import pytest

import app.database.enums as enums
from app.database.models import Message, User
from app.services.client_base import ClientBase


class DummyClient(ClientBase):
    async def generate_response(self, user: User, message: Message):
        return None


@pytest.mark.asyncio
async def test_tool_call_notification_persists_visible_message() -> None:
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.services.client_base.strings.get_string",
            return_value="Using search_knowledge...",
        ),
        patch(
            "app.services.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.client_base.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await client._tool_call_notification(user, "search_knowledge")

    mock_send_message.assert_awaited_once_with(user.wa_id, "Using search_knowledge...")
    assert mock_create_message.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Using search_knowledge...",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_tool_call_notification_skips_persistence_when_user_id_is_missing() -> (
    None
):
    client = DummyClient()
    user = User(id=None, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.services.client_base.strings.get_string",
            return_value="Using search_knowledge...",
        ),
        patch(
            "app.services.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.client_base.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await client._tool_call_notification(user, "search_knowledge")

    mock_send_message.assert_awaited_once()
    mock_create_message.assert_not_awaited()
