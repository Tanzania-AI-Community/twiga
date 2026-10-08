from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.database.enums import UserState
from app.database.models import User
from app.utils.string_manager import StringCategory, strings
from scripts.crons import approve_users_cron
from scripts.crons.helpers.whatsapp import WhatsAppClient


def _approved_user() -> User:
    return User(
        id=101,
        wa_id="255700001001",
        state=UserState.approved,
    )


def _whatsapp_context(send_message_result: bool) -> tuple[AsyncMock, AsyncMock]:
    whatsapp_client = AsyncMock()
    whatsapp_client.send_message = AsyncMock(return_value=send_message_result)
    whatsapp_context = AsyncMock()
    whatsapp_context.__aenter__.return_value = whatsapp_client
    whatsapp_context.__aexit__.return_value = None
    return whatsapp_client, whatsapp_context


@pytest.mark.asyncio
async def test_approve_users_persists_welcome_with_shared_message_writer() -> None:
    user = _approved_user()
    ask_name_message = strings.get_string(StringCategory.ONBOARDING, "ask_name")
    whatsapp_client, whatsapp_context = _whatsapp_context(True)

    with (
        patch.object(
            approve_users_cron,
            "get_users_by_state",
            AsyncMock(return_value=[user]),
        ),
        patch.object(
            approve_users_cron,
            "WhatsAppClient",
            return_value=whatsapp_context,
        ),
        patch.object(approve_users_cron, "update_user", AsyncMock()) as update_user,
        patch.object(
            approve_users_cron,
            "create_new_messages",
            AsyncMock(),
        ) as create_new_messages,
    ):
        await approve_users_cron.approve_and_welcome_users()

    assert user.state == UserState.onboarding
    update_user.assert_awaited_once_with(user)
    whatsapp_client.send_message.assert_awaited_once_with(user.wa_id, ask_name_message)
    persisted_messages = create_new_messages.await_args.args[0]
    assert len(persisted_messages) == 2
    assert persisted_messages[0].user_id == user.id
    assert "Welcome template sent" in persisted_messages[0].content
    assert persisted_messages[0].is_present_in_conversation is True
    assert persisted_messages[1].user_id == user.id
    assert persisted_messages[1].content == ask_name_message
    assert persisted_messages[1].is_present_in_conversation is True


@pytest.mark.asyncio
async def test_approve_users_records_only_the_template_when_name_question_fails() -> (
    None
):
    user = _approved_user()
    whatsapp_client, whatsapp_context = _whatsapp_context(False)

    with (
        patch.object(
            approve_users_cron,
            "get_users_by_state",
            AsyncMock(return_value=[user]),
        ),
        patch.object(
            approve_users_cron,
            "WhatsAppClient",
            return_value=whatsapp_context,
        ),
        patch.object(approve_users_cron, "update_user", AsyncMock()) as update_user,
        patch.object(
            approve_users_cron,
            "create_new_messages",
            AsyncMock(),
        ) as create_new_messages,
    ):
        await approve_users_cron.approve_and_welcome_users()

    assert user.state == UserState.onboarding
    update_user.assert_awaited_once_with(user)
    whatsapp_client.send_template_message.assert_awaited_once()
    persisted_messages = create_new_messages.await_args.args[0]
    assert len(persisted_messages) == 1
    assert persisted_messages[0].user_id == user.id
    assert "Welcome template sent" in persisted_messages[0].content
    assert persisted_messages[0].is_present_in_conversation is True


@pytest.mark.asyncio
async def test_cron_send_message_returns_true_for_a_mock_client() -> None:
    client = WhatsAppClient(mock=True)

    try:
        assert await client.send_message("255700001001", "What should I call you?")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cron_send_message_returns_false_when_the_request_fails() -> None:
    client = WhatsAppClient(
        api_token="token",
        phone_number_id="123",
        api_version="v22.0",
        mock=False,
    )
    client.mock = False
    request = httpx.Request("POST", "https://graph.facebook.com/v22.0/123/messages")
    response = httpx.Response(400, request=request, text="bad request")
    client.client.post = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "bad request",
            request=request,
            response=response,
        )
    )

    try:
        assert (
            await client.send_message("255700001001", "What should I call you?")
            is False
        )
    finally:
        await client.close()
