from importlib import import_module
from unittest.mock import AsyncMock, patch

import pytest

from app.database.enums import UserState
from app.database.models import User

WITH_NAME_TEMPLATE_BODY = (
    "👋 Hi {{1}}! Twiga 🦒 is here whenever you need quick lesson support, "
    "activities, or class explanations."
)
WITHOUT_NAME_TEMPLATE_BODY = (
    "📚 Friendly reminder from Twiga 🦒: if you're planning lessons this week, "
    "I can help you prepare in minutes."
)


def _reminder_templates(reminder_cron):
    return {
        reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID: {
            "language_code": reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
            "body_text": WITH_NAME_TEMPLATE_BODY,
            "requires_user_name": True,
        },
        reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID: {
            "language_code": reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
            "body_text": WITHOUT_NAME_TEMPLATE_BODY,
            "requires_user_name": False,
        },
    }


@pytest.mark.asyncio
async def test_send_reminder_messages_sends_with_name_template_and_persists_message() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")
    user = User(id=101, wa_id="255700001001", name="Teacher")

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
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID,
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

    mock_initialize_db.assert_called_once()
    mock_whatsapp_client.send_template_message.assert_awaited_once_with(
        wa_id=user.wa_id,
        template_name=reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID,
        language_code=reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
        body_text_params=["Teacher"],
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    created_message = created_messages[0]
    assert created_message.user_id == user.id
    assert created_message.is_present_in_conversation is True
    assert created_message.content == WITH_NAME_TEMPLATE_BODY
    assert (
        created_message.cron_name
        == reminder_cron.MessageCronName.send_reminder_messages_cron
    )


@pytest.mark.asyncio
async def test_send_reminder_messages_sends_without_name_template_for_static_copy() -> (
    None
):
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")
    user = User(id=404, wa_id="255700004004", name="Teacher")

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
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID,
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
        template_name=reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID,
        language_code=reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
        body_text_params=None,
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    assert created_messages[0].content == WITHOUT_NAME_TEMPLATE_BODY


@pytest.mark.asyncio
async def test_send_reminder_messages_processes_onboarding_user() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")
    user = User(
        id=505,
        wa_id="255700005005",
        name="Onboarding Teacher",
        state=UserState.onboarding,
    )

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
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            return_value=reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID,
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
        template_name=reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID,
        language_code=reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
        body_text_params=["Onboarding Teacher"],
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    persisted_message = created_messages[0]
    assert persisted_message.user_id == user.id
    assert persisted_message.content == WITH_NAME_TEMPLATE_BODY


@pytest.mark.asyncio
async def test_send_reminder_messages_without_name_uses_static_template() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")
    user = User(id=303, wa_id="255700003003", name=None)

    mock_whatsapp_client = AsyncMock()
    mock_whatsapp_context = AsyncMock()
    mock_whatsapp_context.__aenter__.return_value = mock_whatsapp_client
    mock_whatsapp_context.__aexit__.return_value = None

    def _pick_first(items):
        assert items == [reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID]
        return items[0]

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[user]),
        ),
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            side_effect=_pick_first,
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
        template_name=reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID,
        language_code=reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
        body_text_params=None,
        include_image_header=False,
    )

    created_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(created_messages) == 1
    assert created_messages[0].content == WITHOUT_NAME_TEMPLATE_BODY


@pytest.mark.asyncio
async def test_send_reminder_messages_skips_when_no_eligible_users() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
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
async def test_send_reminder_messages_exits_when_template_mapping_is_invalid() -> None:
    reminder_cron = import_module("scripts.crons.send_reminder_messages_cron")
    user = User(id=909, wa_id="255700009009", name=None)

    with (
        patch("scripts.crons.send_reminder_messages_cron.initialize_db"),
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            {
                reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID: {
                    "language_code": reminder_cron.REMINDER_TEMPLATES_LANGUAGE,
                    "body_text": WITH_NAME_TEMPLATE_BODY,
                    "requires_user_name": True,
                }
            },
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=[user]),
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
        patch.dict(
            "scripts.crons.send_reminder_messages_cron.REMINDER_TEMPLATES",
            _reminder_templates(reminder_cron),
            clear=True,
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.get_users_for_reminder",
            AsyncMock(return_value=users),
        ),
        patch(
            "scripts.crons.send_reminder_messages_cron.random.choice",
            side_effect=[
                reminder_cron.REMINDER_TEMPLATE_WITH_NAME_ID,
                reminder_cron.REMINDER_TEMPLATE_WITHOUT_NAME_ID,
            ],
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

    assert mock_create_messages.await_count == 1
    persisted_messages = mock_create_messages.await_args.kwargs["messages"]
    assert len(persisted_messages) == 1
    persisted_message = persisted_messages[0]
    assert persisted_message.user_id == users[1].id
    assert persisted_message.content == WITHOUT_NAME_TEMPLATE_BODY
    mock_sys_exit.assert_called_once_with(1)
