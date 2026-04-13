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
    """Tools with a defined string (e.g. generate_exercise) send a WhatsApp message."""
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.services.client_base.strings.get_category",
            return_value={"generate_exercise": "Generating exercises..."},
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
        await client._tool_call_notification(user, "generate_exercise")

    mock_send_message.assert_awaited_once_with(user.wa_id, "Generating exercises...")
    assert mock_create_message.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Generating exercises...",
        "is_present_in_conversation": True,
    }


@pytest.mark.asyncio
async def test_tool_call_notification_skips_persistence_when_user_id_is_missing() -> (
    None
):
    """Tools with a defined string still skip DB persistence when user has no ID."""
    client = DummyClient()
    user = User(id=None, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.services.client_base.strings.get_category",
            return_value={"generate_exercise": "Generating exercises..."},
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
        await client._tool_call_notification(user, "generate_exercise")

    mock_send_message.assert_awaited_once()
    mock_create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_call_notification_silent_for_search_knowledge() -> None:
    """search_knowledge notification is supressed, so no message is sent."""
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
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

    mock_send_message.assert_not_awaited()
    mock_create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_call_notification_warns_for_unknown_tool() -> None:
    """A tool absent from the YAML entirely logs a warning and sends nothing."""
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.services.client_base.strings.get_category",
            return_value={
                "generate_exercise": "Generating exercises...",
                "search_knowledge": "📚 Searching the course content, please hold...",
                "solve_equation": "Solving the equation...",
            },
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
        with patch.object(client.logger, "warning") as mock_warning:
            await client._tool_call_notification(user, "some_new_unregistered_tool")
            mock_warning.assert_called_once()

    mock_send_message.assert_not_awaited()
    mock_create_message.assert_not_awaited()

