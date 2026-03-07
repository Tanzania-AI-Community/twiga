from fastapi.responses import JSONResponse
import pytest
from unittest.mock import AsyncMock, patch

import app.database.enums as enums
from app.database.models import Message, User
from app.services.client_base import ClientBase
from app.services.messaging_service import MessagingService
from app.services import request_service


class DummyClient(ClientBase):
    async def generate_response(self, user: User, message: Message):
        return None


@pytest.mark.asyncio
async def test_request_service_marks_inbound_user_message_as_present_in_conversation() -> None:
    user = User(
        id=7,
        wa_id="255700000000",
        name="Teacher",
        state=enums.UserState.active,
    )

    async def _echo_message(message: Message) -> Message:
        return message

    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.state_client._handle_rate_limiting",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.request_service.db.create_new_message",
            AsyncMock(side_effect=_echo_message),
        ),
        patch(
            "app.services.request_service.state_client.handle_active",
            AsyncMock(return_value=JSONResponse(content={"status": "ok"}, status_code=200)),
        ) as mock_handle_active,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Hello"},
        )

    assert response.status_code == 200
    created_message = mock_handle_active.await_args.args[2]
    assert created_message.role == enums.MessageRole.user
    assert created_message.content == "Hello"
    assert created_message.is_present_in_conversation is True


@pytest.mark.asyncio
async def test_tool_call_notification_persists_message_present_in_conversation() -> None:
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    async def _echo_message(message: Message) -> Message:
        return message

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
            "app.services.client_base.create_new_message",
            AsyncMock(side_effect=_echo_message),
        ) as mock_create_new_message,
    ):
        await client._tool_call_notification(user, "search_knowledge")

    mock_send_message.assert_awaited_once_with(user.wa_id, "Using search_knowledge...")

    persisted_message = mock_create_new_message.await_args.args[0]
    assert persisted_message.user_id == user.id
    assert persisted_message.role == enums.MessageRole.assistant
    assert persisted_message.content == "Using search_knowledge..."
    assert persisted_message.is_present_in_conversation is True


@pytest.mark.asyncio
async def test_handle_chat_message_marks_final_response_as_present_in_conversation() -> None:
    service = MessagingService()
    user = User(id=1, wa_id="255700000000", name="Teacher")
    user_message = Message(
        user_id=1,
        role=enums.MessageRole.user,
        content="What is photosynthesis?",
    )
    final_message = Message(
        user_id=1,
        role=enums.MessageRole.assistant,
        content="Photosynthesis is how plants make food.",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[final_message]),
        ),
        patch("app.services.messaging_service.db.create_new_messages", AsyncMock()) as mock_create_messages,
        patch("app.services.messaging_service.whatsapp_client.send_message", AsyncMock()) as mock_send_message,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(user=user, user_message=user_message)

    assert response.status_code == 200
    assert final_message.is_present_in_conversation is True
    mock_create_messages.assert_awaited_once_with([final_message])
    mock_send_message.assert_awaited_once_with(user.wa_id, final_message.content)


@pytest.mark.asyncio
async def test_handle_chat_message_persists_general_error_when_llm_returns_none() -> None:
    service = MessagingService()
    user = User(id=3, wa_id="255700000000", name="Teacher")
    user_message = Message(
        user_id=3,
        role=enums.MessageRole.user,
        content="Hi",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Something went wrong.",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.messaging_service.db.create_new_message",
            AsyncMock(),
        ) as mock_create_new_message,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(user=user, user_message=user_message)

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(user.wa_id, "Something went wrong.")

    persisted_message = mock_create_new_message.await_args.args[0]
    assert persisted_message.user_id == user.id
    assert persisted_message.role == enums.MessageRole.assistant
    assert persisted_message.content == "Something went wrong."
    assert persisted_message.is_present_in_conversation is True
