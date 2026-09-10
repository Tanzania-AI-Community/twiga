from unittest.mock import AsyncMock, patch

import pytest

from app.database.enums import UserState
from app.database.models import User
from scripts.crons import approve_users_cron


@pytest.mark.asyncio
async def test_approve_users_persists_welcome_with_shared_message_writer() -> None:
    user = User(
        id=101,
        wa_id="255700001001",
        state=UserState.approved,
    )
    whatsapp_client = AsyncMock()
    whatsapp_context = AsyncMock()
    whatsapp_context.__aenter__.return_value = whatsapp_client
    whatsapp_context.__aexit__.return_value = None

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
        patch.object(approve_users_cron, "update_user", AsyncMock()),
        patch.object(
            approve_users_cron,
            "create_new_messages",
            AsyncMock(),
        ) as create_new_messages,
    ):
        await approve_users_cron.approve_and_welcome_users()

    persisted_messages = create_new_messages.await_args.args[0]
    assert (
        len(persisted_messages) == 1
        and persisted_messages[0].user_id == user.id
        and "Welcome template sent" in persisted_messages[0].content
    )
    assert persisted_messages[0].is_present_in_conversation is True
