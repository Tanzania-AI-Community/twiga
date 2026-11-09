from unittest.mock import AsyncMock, patch

import pytest

import app.database.enums as enums
from app.clients.client_base import ClientBase
from app.config import Prompt
from app.database.models import Message, User


class DummyClient(ClientBase):
    async def generate_response(self, user: User, message: Message):
        return None


@pytest.mark.asyncio
async def test_tool_call_notification_persists_message_outside_llm_context() -> None:
    """Tools with a defined string (e.g. generate_exercise) send a WhatsApp message."""
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.clients.client_base.strings.get_category",
            return_value={"generate_exercise": "Generating exercises..."},
        ),
        patch(
            "app.clients.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.clients.client_base.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await client._tool_call_notification(user, "generate_exercise")

    mock_send_message.assert_awaited_once_with(user.wa_id, "Generating exercises...")
    assert mock_create_message.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": "Generating exercises...",
        "is_present_in_conversation": False,
    }


@pytest.mark.asyncio
async def test_tool_call_notification_uses_notification_field_when_tool_string_is_dict() -> (
    None
):
    """Dict-style tool strings should use the `notification` field for the sent message."""
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")

    with (
        patch(
            "app.clients.client_base.strings.get_category",
            return_value={
                "generate_necta_style_exam": {
                    "notification": "📝 Generating a NECTA-style exam, please hold...",
                    "delivery_success": "Here is your practice exam.",
                }
            },
        ),
        patch(
            "app.clients.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.clients.client_base.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message,
    ):
        await client._tool_call_notification(user, "generate_necta_style_exam")

    expected_notification = "📝 Generating a NECTA-style exam, please hold..."
    mock_send_message.assert_awaited_once_with(user.wa_id, expected_notification)
    assert mock_create_message.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.assistant,
        "content": expected_notification,
        "is_present_in_conversation": False,
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
            "app.clients.client_base.strings.get_category",
            return_value={"generate_exercise": "Generating exercises..."},
        ),
        patch(
            "app.clients.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.clients.client_base.create_new_message_by_fields",
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
            "app.clients.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.clients.client_base.create_new_message_by_fields",
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
            "app.clients.client_base.strings.get_category",
            return_value={
                "generate_exercise": "Generating exercises...",
                "search_knowledge": "📚 Searching the course content, please hold...",
                "solve_equation": "Solving the equation...",
            },
        ),
        patch(
            "app.clients.client_base.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch(
            "app.clients.client_base.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message,
    ):
        with patch.object(client.logger, "warning") as mock_warning:
            await client._tool_call_notification(user, "some_new_unregistered_tool")
            mock_warning.assert_called_once()

    mock_send_message.assert_not_awaited()
    mock_create_message.assert_not_awaited()


def test_format_messages_happy_path() -> None:
    client = DummyClient()
    user = User(id=1, name="Test User", wa_id="255700000001")

    database_messages = [
        Message(user_id=1, role=enums.MessageRole.user, content="hello"),
        Message(user_id=1, role=enums.MessageRole.assistant, content="hi"),
    ]
    new_messages = [
        Message(user_id=1, role=enums.MessageRole.user, content="new question")
    ]

    result = client._format_messages(
        new_messages=new_messages,
        database_messages=database_messages,
        user=user,
        prompt=Prompt.TWIGA_AGENT_SYSTEM,
    )

    assert result[0]["role"] == enums.MessageRole.system
    assert isinstance(result[0]["content"], str)
    assert result[0]["content"]
    assert result[-1]["role"] == enums.MessageRole.user.value
    assert result[-1]["content"] == "new question"


def test_format_messages_keeps_short_history_and_unsaved_inputs() -> None:
    client = DummyClient()
    user = User(id=1, name="Test User", wa_id="255700000001")

    database_messages = [
        Message(user_id=1, role=enums.MessageRole.user, content="only one")
    ]
    new_messages = [
        Message(user_id=1, role=enums.MessageRole.user, content="first"),
        Message(user_id=1, role=enums.MessageRole.assistant, content="second"),
    ]

    result = client._format_messages(
        new_messages=new_messages,
        database_messages=database_messages,
        user=user,
        prompt=Prompt.TWIGA_AGENT_SYSTEM,
    )
    assert [m["content"] for m in result[1:]] == ["only one", "first", "second"]


@pytest.mark.parametrize(
    "rollup,batches", [(False, False), (True, False), (False, True), (True, True)]
)
def test_summary_order_identity_and_visibility(rollup, batches):
    from app.services.conversation_summary_service import (
        PreparedConversation,
        SummaryRequestContext,
    )
    from tests.services.test_conversation_summary_service import (
        batch,
        current,
        snapshot,
        source,
    )

    user = User(id=1, name="Teacher", wa_id="one")
    first, second = source(10, "same text"), source(11, "same text")
    prepared = PreparedConversation(
        snapshot(
            (first, second),
            (batch(1), batch(2)) if batches else (),
            rollup="older rollup" if rollup else "",
            covered=(9,) if rollup else (),
        ),
        SummaryRequestContext(1, (10, 11), (11,)),
    )
    result = DummyClient._format_messages(
        [current(second)], None, user, Prompt.TWIGA_AGENT_SYSTEM, prepared
    )
    contents = [m["content"] for m in result[1:]]
    assert contents == (["older rollup"] if rollup else []) + (
        ["batch-1", "batch-2"] if batches else []
    ) + ["same text", "same text"]
    hidden = current(source(3, "hidden"))
    hidden.is_present_in_conversation = False
    flow = current(source(4, "[FLOW_SENT] form"))
    tool = current(source(5, "tool", enums.MessageRole.tool))
    scaffold = current(source(6, "scaffold", enums.MessageRole.assistant))
    scaffold.tool_calls = [{"id": "call"}]
    result = DummyClient._format_messages(
        [current(second)],
        [current(first), hidden, flow, tool, scaffold],
        user,
        Prompt.TWIGA_AGENT_SYSTEM,
    )
    assert [m["content"] for m in result[1:]] == ["same text", "same text"]


@pytest.mark.parametrize("covered_id", [1, 2])
def test_formatter_rejects_summary_overlap_with_any_raw_or_current_source(covered_id):
    from app.services.conversation_summary_service import (
        PreparedConversation,
        SummaryError,
        SummaryRequestContext,
    )
    from tests.services.test_conversation_summary_service import (
        current,
        snapshot,
        source,
    )

    prepared = PreparedConversation(
        snapshot(
            (source(1), source(2)), version=1, rollup="older", covered=(covered_id,)
        ),
        SummaryRequestContext(1, (1, 2), (2,)),
    )
    with pytest.raises(SummaryError, match="already covered"):
        DummyClient._format_messages(
            [current(source(2))],
            None,
            User(id=1, name="Teacher", wa_id="one"),
            Prompt.TWIGA_AGENT_SYSTEM,
            prepared,
        )


@pytest.mark.asyncio
async def test_preprocess_requires_snapshot_and_preserves_explicit_empty():
    client = DummyClient()
    user = User(id=11, wa_id="255700000000", name="Teacher")
    with patch.object(client, "_build_api_messages", new_callable=AsyncMock) as build:
        assert await client._preprocess_messages(user, ()) == (None, None)
        build.assert_not_awaited()
        with pytest.raises(TypeError):
            await client._preprocess_messages(user)
