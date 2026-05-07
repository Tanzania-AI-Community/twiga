from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import db, enums
from app.database.models import Message


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_new_message_by_fields_builds_message_and_delegates() -> None:
    async def _echo_message(message: Message) -> Message:
        return message

    with patch(
        "app.database.db.create_new_message",
        AsyncMock(side_effect=_echo_message),
    ) as mock_create_new_message:
        created_message = await db.create_new_message_by_fields(
            user_id=17,
            role=enums.MessageRole.assistant,
            content="Visible text",
            is_present_in_conversation=True,
            tool_calls=[{"id": "call-1"}],
            tool_call_id="call-1",
            tool_name="search_knowledge",
            cron_name=enums.MessageCronName.send_reminder_messages_cron,
        )

    persisted_message = mock_create_new_message.await_args.args[0]
    assert persisted_message.user_id == 17
    assert persisted_message.role == enums.MessageRole.assistant
    assert persisted_message.content == "Visible text"
    assert persisted_message.is_present_in_conversation is True
    assert persisted_message.tool_calls == [{"id": "call-1"}]
    assert persisted_message.tool_call_id == "call-1"
    assert persisted_message.tool_name == "search_knowledge"
    assert (
        persisted_message.cron_name == enums.MessageCronName.send_reminder_messages_cron
    )
    assert created_message is persisted_message


@pytest.mark.asyncio
async def test_create_new_message_by_fields_defaults_is_present_to_false() -> None:
    async def _echo_message(message: Message) -> Message:
        return message

    with patch(
        "app.database.db.create_new_message",
        AsyncMock(side_effect=_echo_message),
    ) as mock_create_new_message:
        created_message = await db.create_new_message_by_fields(
            user_id=99,
            role=enums.MessageRole.user,
            content="Hello",
        )

    persisted_message = mock_create_new_message.await_args.args[0]
    assert persisted_message.is_present_in_conversation is False
    assert created_message.is_present_in_conversation is False


@pytest.mark.asyncio
async def test_get_latest_user_message_by_role_returns_scalar_first_message() -> None:
    expected_message = Message(
        user_id=7,
        role=enums.MessageRole.assistant,
        content="latest",
    )
    result = MagicMock()
    result.scalars.return_value.first.return_value = expected_message
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    with patch(
        "app.database.db.get_session",
        return_value=_SessionContext(session),
    ):
        latest_message = await db.get_latest_user_message_by_role(
            user_id=7,
            role=enums.MessageRole.assistant,
        )

    session.execute.assert_awaited_once()
    assert latest_message is expected_message


def test_message_model_defaults_is_present_in_conversation_to_false() -> None:
    message = Message(
        user_id=5,
        role=enums.MessageRole.user,
        content="Incoming text",
    )
    assert message.is_present_in_conversation is False
