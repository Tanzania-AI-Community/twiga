from fastapi.responses import JSONResponse
import pytest
from unittest.mock import AsyncMock, patch

import app.database.enums as enums
from app.database.models import Message, User
from app.services.client_base import ClientBase
from app.services.messaging_service import MessagingService
from app.services import request_service
from app.services.flow_service import FlowService
from app.services.whatsapp_service import WhatsAppClient


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


@pytest.mark.asyncio
async def test_request_service_persists_inbound_message_for_in_review_users() -> None:
    user = User(
        id=17,
        wa_id="255700000111",
        name="Teacher",
        state=enums.UserState.in_review,
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
        ) as mock_create_message,
        patch(
            "app.services.request_service.state_client.handle_in_review_user",
            AsyncMock(return_value=JSONResponse(content={"status": "ok"}, status_code=200)),
        ) as mock_in_review_handler,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Please approve me"},
        )

    assert response.status_code == 200
    mock_in_review_handler.assert_awaited_once_with(user)
    created_message = mock_create_message.await_args.args[0]
    assert created_message.role == enums.MessageRole.user
    assert created_message.is_present_in_conversation is True


@pytest.mark.asyncio
async def test_command_help_persists_visible_message() -> None:
    service = MessagingService()
    user = User(id=31, wa_id="255700000222", name="Teacher")

    with (
        patch(
            "app.services.messaging_service.strings.get_string",
            return_value="Help text",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.services.messaging_service.db.create_new_message",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await service._command_help(user)

    mock_send_message.assert_awaited_once_with(user.wa_id, "Help text")
    persisted_message = mock_create_message.await_args.args[0]
    assert persisted_message.role == enums.MessageRole.assistant
    assert persisted_message.content == "Help text"
    assert persisted_message.is_present_in_conversation is True


@pytest.mark.asyncio
async def test_send_personal_flow_persists_flow_message() -> None:
    user = User(id=41, wa_id="255700000333", name="Teacher")

    flow_strings = {
        "start_onboarding_header": "Welcome",
        "start_onboarding_body": "Please complete your profile",
        "start_onboarding_cta": "Start",
    }

    with (
        patch(
            "app.services.flow_service.settings.onboarding_flow_id",
            "flow-123",
        ),
        patch(
            "app.services.flow_service.settings.subjects_classes_flow_id",
            "flow-classes-123",
        ),
        patch(
            "app.services.flow_service.strings.get_category",
            return_value=flow_strings,
        ),
        patch(
            "app.services.flow_service.futil.send_whatsapp_flow_message",
            AsyncMock(),
        ),
        patch(
            "app.services.flow_service.db.create_new_message",
            AsyncMock(),
        ) as mock_create_message,
    ):
        service = FlowService()
        await service.send_personal_and_school_info_flow(user)

    persisted_message = mock_create_message.await_args.args[0]
    assert persisted_message.role == enums.MessageRole.assistant
    assert persisted_message.is_present_in_conversation is True
    assert persisted_message.content is not None
    assert persisted_message.content.startswith("[FLOW_SENT] id=flow-123")


@pytest.mark.asyncio
async def test_flow_complete_event_persists_user_interaction() -> None:
    client = WhatsAppClient()
    user = User(id=51, wa_id="255700000444", name="Teacher")
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": user.wa_id}],
                            "messages": [
                                {
                                    "interactive": {
                                        "nfm_reply": {
                                            "response_json": {
                                                "flow_token": "token-1",
                                                "field_1": "value-1",
                                            }
                                        }
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with (
        patch(
            "app.services.whatsapp_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.whatsapp_service.db.create_new_message",
            AsyncMock(),
        ) as mock_create_message,
    ):
        response = await client.handle_flow_message_complete(body)

    assert response.status_code == 200
    persisted_message = mock_create_message.await_args.args[0]
    assert persisted_message.role == enums.MessageRole.user
    assert persisted_message.is_present_in_conversation is True
    assert persisted_message.content is not None
    assert persisted_message.content.startswith("[FLOW_COMPLETED]")

    await client.client.aclose()
