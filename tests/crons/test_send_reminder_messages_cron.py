from importlib import import_module
from unittest.mock import AsyncMock, patch

import pytest

from app.database.models import User


@pytest.mark.asyncio
async def test_send_reminder_messages_sends_template_and_persists_message() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    user = User(id=101, wa_id="255700001001", name="Teacher")
    selected_reminder_message = "👋 Quick reminder: I can help with lesson plans today."

    mock_whatsapp_client = AsyncMock()
    mock_whatsapp_context = AsyncMock()
    mock_whatsapp_context.__aenter__.return_value = mock_whatsapp_client
    mock_whatsapp_context.__aexit__.return_value = None

    with (
        patch(
            "scripts.crons.send_reminder_messages_cron.initialize_db"
        ) as mock_initialize_db,
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[user]),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_templates",
            return_value=[
                "First reminder",
                selected_reminder_message,
                "Third reminder",
            ],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=selected_reminder_message,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_message",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await reminder_cron.send_reminder_messages()

    mock_initialize_db.assert_called_once()
    mock_whatsapp_client.send_template_message.assert_awaited_once_with(
        user.wa_id,
        reminder_cron.REMINDER_TEMPLATE_ID,
        language_code=reminder_cron.REMINDER_TEMPLATE_LANGUAGE,
        body_text_params=[selected_reminder_message],
        include_image_header=False,
    )

    created_message = mock_create_message.await_args.args[0]
    assert created_message.user_id == user.id
    assert created_message.is_present_in_conversation is True
    assert created_message.content == selected_reminder_message
    assert created_message.tool_name == reminder_cron.REMINDER_MESSAGE_TOOL_NAME


@pytest.mark.asyncio
async def test_send_reminder_messages_skips_when_no_eligible_users() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_templates",
            return_value=["Reminder template"],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[]),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient"
        ) as mock_whatsapp_client_class,
        patch(
            "scripts.crons.send_reminder_messages_cron.create_message",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await reminder_cron.send_reminder_messages()

    mock_whatsapp_client_class.assert_not_called()
    mock_create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reminder_messages_exits_when_reminder_templates_config_is_invalid() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_templates",
            side_effect=ValueError("invalid reminder templates"),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.sys.exit",
            side_effect=SystemExit(1),
        ) as mock_sys_exit,
    ):
        with pytest.raises(SystemExit):
            await reminder_cron.send_reminder_messages()

    mock_sys_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_send_reminder_messages_exits_with_error_when_any_user_send_fails() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    users = [
        User(id=201, wa_id="255700002001", name="Teacher One"),
        User(id=202, wa_id="255700002002", name="Teacher Two"),
    ]

    mock_whatsapp_client = AsyncMock()
    mock_whatsapp_client.send_template_message = AsyncMock(
        side_effect=[RuntimeError("whatsapp down"), None]
    )
    mock_whatsapp_context = AsyncMock()
    mock_whatsapp_context.__aenter__.return_value = mock_whatsapp_client
    mock_whatsapp_context.__aexit__.return_value = None

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=users),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_templates",
            return_value=["Reminder A", "Reminder B"],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            side_effect=["Reminder A", "Reminder B"],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_message",
            AsyncMock(),
        ) as mock_create_message,
        patch(
            "scripts.crons.send_reminder_messages_cron.sys.exit",
            side_effect=SystemExit(1),
        ) as mock_sys_exit,
    ):
        with pytest.raises(SystemExit):
            await reminder_cron.send_reminder_messages()

    # One user fails send; one succeeds and gets persisted.
    assert mock_create_message.await_count == 1
    persisted_message = mock_create_message.await_args.args[0]
    assert persisted_message.user_id == users[1].id
    assert persisted_message.content == "Reminder B"
    mock_sys_exit.assert_called_once_with(1)
