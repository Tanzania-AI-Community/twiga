from importlib import import_module
from unittest.mock import AsyncMock, patch

import pytest

from app.database.models import User


@pytest.mark.asyncio
async def test_send_reminder_messages_sends_template_and_persists_message() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    user = User(id=101, wa_id="255700001001", name="Teacher")
    selected_template = "👋 Hi{user_name}! Twiga is ready to help."

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
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
            return_value=[selected_template],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=selected_template,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_messages",
            AsyncMock(),
        ) as mock_create_messages,
    ):
        await reminder_cron.send_reminder_messages()

    expected_message = "👋 Hi Teacher! Twiga is ready to help."

    mock_initialize_db.assert_called_once()
    mock_whatsapp_client.send_template_message.assert_awaited_once_with(
        wa_id=user.wa_id,
        template_name=reminder_cron.REMINDER_TEMPLATE_ID,
        language_code=reminder_cron.REMINDER_TEMPLATE_LANGUAGE,
        body_text_params=[expected_message],
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    created_message = created_messages[0]
    assert created_message.user_id == user.id
    assert created_message.is_present_in_conversation is True
    assert created_message.content == expected_message
    assert (
        created_message.cron_name
        == reminder_cron.MessageCronName.send_reminder_messages_cron
    )


@pytest.mark.asyncio
async def test_send_reminder_messages_keeps_template_without_user_name_placeholder() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    user = User(id=404, wa_id="255700004004", name="Teacher")
    selected_template = "📚 Friendly reminder from Twiga 🦒."

    mock_whatsapp_client = AsyncMock()
    mock_whatsapp_context = AsyncMock()
    mock_whatsapp_context.__aenter__.return_value = mock_whatsapp_client
    mock_whatsapp_context.__aexit__.return_value = None

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[user]),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
            return_value=[selected_template],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=selected_template,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_messages",
            AsyncMock(),
        ) as mock_create_messages,
    ):
        await reminder_cron.send_reminder_messages()

    mock_whatsapp_client.send_template_message.assert_awaited_once_with(
        wa_id=user.wa_id,
        template_name=reminder_cron.REMINDER_TEMPLATE_ID,
        language_code=reminder_cron.REMINDER_TEMPLATE_LANGUAGE,
        body_text_params=[selected_template],
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    assert created_messages[0].content == selected_template


@pytest.mark.asyncio
async def test_send_reminder_messages_formats_empty_user_name_without_extra_space() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    user = User(id=303, wa_id="255700003003", name=None)
    selected_template = "✨ Still teaching{user_name}? I can help now."

    mock_whatsapp_client = AsyncMock()
    mock_whatsapp_context = AsyncMock()
    mock_whatsapp_context.__aenter__.return_value = mock_whatsapp_client
    mock_whatsapp_context.__aexit__.return_value = None

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[user]),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
            return_value=[selected_template],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=selected_template,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_messages",
            AsyncMock(),
        ) as mock_create_messages,
    ):
        await reminder_cron.send_reminder_messages()

    expected_message = "✨ Still teaching? I can help now."

    mock_whatsapp_client.send_template_message.assert_awaited_once_with(
        wa_id=user.wa_id,
        template_name=reminder_cron.REMINDER_TEMPLATE_ID,
        language_code=reminder_cron.REMINDER_TEMPLATE_LANGUAGE,
        body_text_params=[expected_message],
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    created_message = created_messages[0]
    assert created_message.content == expected_message


@pytest.mark.asyncio
async def test_send_reminder_messages_skips_when_no_eligible_users() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
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
            "scripts.crons.send_reminder_messages_cron.create_messages",
            AsyncMock(),
        ) as mock_create_messages,
    ):
        await reminder_cron.send_reminder_messages()

    mock_whatsapp_client_class.assert_not_called()
    mock_create_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reminder_messages_exits_when_reminder_strings_config_is_invalid() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
            side_effect=ValueError("invalid reminder strings"),
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
            "scripts.crons.send_reminder_messages_cron._get_reminder_strings",
            return_value=["Reminder A{user_name}", "Reminder B{user_name}"],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            side_effect=["Reminder A{user_name}", "Reminder B{user_name}"],
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.WhatsAppClient",
            return_value=mock_whatsapp_context,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.create_messages",
            AsyncMock(),
        ) as mock_create_messages,
        patch(
            "scripts.crons.send_reminder_messages_cron.sys.exit",
            side_effect=SystemExit(1),
        ) as mock_sys_exit,
    ):
        with pytest.raises(SystemExit):
            await reminder_cron.send_reminder_messages()

    # One user fails send; one succeeds and gets persisted.
    assert mock_create_messages.await_count == 1
    persisted_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(persisted_messages) == 1
    persisted_message = persisted_messages[0]
    assert persisted_message.user_id == users[1].id
    assert persisted_message.content == "Reminder B Teacher Two"
    mock_sys_exit.assert_called_once_with(1)
