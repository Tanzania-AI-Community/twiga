"""Core image routing, answering, and teacher-facing failure behaviour."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.database.enums import MessageRole
from app.database.models import Message, User
from app.models.image_models import (
    DownloadedImage,
    ImageInputError,
    ImageInterpretation,
)
from app.services import messaging_service, state_service
from app.utils.whatsapp_utils import (
    ValidMessageType,
    extract_message,
    extract_message_info,
    get_valid_message_type,
    split_message_payloads,
)


def image_message(caption=None, sender="255700000000"):
    message = {
        "id": f"wamid.{sender}",
        "from": sender,
        "timestamp": "1710000000",
        "type": "image",
        "image": {"id": "12345", "mime_type": "image/png"},
    }
    if caption is not None:
        message["image"]["caption"] = caption
    return message


@pytest.mark.parametrize("caption", [None, "help"])
def test_image_caption_is_preserved_and_not_a_command(caption):
    message = image_message(caption)
    assert get_valid_message_type({"message": message}) is ValidMessageType.IMAGE
    assert f"Teacher instruction: {caption or 'none'}" in extract_message(message)


def test_batch_preserves_each_message_and_sender():
    messages = [image_message(), image_message(sender="255700000001")]
    value = {
        "messages": messages,
        "contacts": [
            {"wa_id": message["from"], "profile": {"name": f"Teacher {i}"}}
            for i, message in enumerate(messages)
        ],
    }
    body = {"entry": [{"changes": [{"value": value}]}]}

    results = [extract_message_info(p) for p in split_message_payloads(body)]

    assert [result["message"] for result in results] == messages
    assert [(result["wa_id"], result["name"]) for result in results] == [
        ("255700000000", "Teacher 0"),
        ("255700000001", "Teacher 1"),
    ]
    assert len(value["messages"]) == 2


async def test_active_state_routes_to_image_handler(monkeypatch):
    user = User(id=7, wa_id="255700000000")
    message = Message(id=9, user_id=7, role=MessageRole.user, content="photo")
    incoming = image_message()
    handler = AsyncMock(return_value=JSONResponse({"status": "ok"}))
    monkeypatch.setattr(
        state_service.whatsapp_client,
        "send_read_receipt_with_typing_indicator",
        AsyncMock(),
    )
    monkeypatch.setattr(state_service.messaging_client, "handle_image_message", handler)

    await state_service.StateHandler().handle_active(
        user, {"inbound_message_id": incoming["id"], "message": incoming}, message
    )

    handler.assert_awaited_once_with(user, message, incoming["image"])


@pytest.fixture
def flow(monkeypatch):
    service = messaging_service.MessagingService()
    context = SimpleNamespace(
        service=service,
        user=User(id=7, wa_id="255700000000"),
        message=Message(id=9, user_id=7, role=MessageRole.user, content="photo"),
        download=AsyncMock(return_value=DownloadedImage(b"pixels", "image/png")),
        interpret=AsyncMock(
            return_value=ImageInterpretation(
                transcription="1. x + 2 = 3\n2. y + 1 = 4",
                visual_details="A triangle labelled ABC",
                readability="clear",
                clarification_reason="",
            )
        ),
        agent=AsyncMock(),
        send=AsyncMock(return_value=True),
        visible=AsyncMock(),
    )

    async def update(message, content):
        message.content = content

    context.persist = AsyncMock(side_effect=update)
    monkeypatch.setattr(
        messaging_service.image_input_settings, "image_input_enabled", True
    )
    monkeypatch.setattr(
        messaging_service.whatsapp_client, "download_image", context.download
    )
    monkeypatch.setattr(
        messaging_service.image_interpreter, "interpret", context.interpret
    )
    monkeypatch.setattr(
        messaging_service.agent_client, "generate_response", context.agent
    )
    monkeypatch.setattr(messaging_service.db, "update_message_content", context.persist)
    monkeypatch.setattr(messaging_service.db, "create_new_messages", AsyncMock())
    monkeypatch.setattr(messaging_service.whatsapp_client, "send_message", context.send)
    monkeypatch.setattr(service, "_persist_visible_assistant_message", context.visible)
    return context


@pytest.mark.parametrize("latex", [False, True])
async def test_image_extraction_reaches_agent_and_existing_delivery(flow, latex):
    async def generate(user, message):
        flow.persist.assert_awaited_once()
        assert message.id == 9
        assert "Teacher instruction: Solve both" in message.content
        assert "1. x + 2 = 3\n2. y + 1 = 4" in message.content
        assert "Relevant visual details: A triangle labelled ABC" in message.content
        return [
            Message(user_id=user.id, role=MessageRole.assistant, content="Solutions")
        ]

    flow.agent.side_effect = generate
    with (
        patch.object(messaging_service.llm_settings, "agentic_mode", False),
        patch.object(
            messaging_service.llm_client, "generate_response", AsyncMock()
        ) as basic,
        patch.object(flow.service, "_is_response_in_latex", return_value=latex),
        patch.object(flow.service, "_send_latex_response", AsyncMock()) as send_latex,
    ):
        response = await flow.service.handle_image_message(
            flow.user, flow.message, image_message("Solve both")["image"]
        )

    assert response.status_code == 200
    flow.download.assert_awaited_once_with("12345")
    flow.interpret.assert_awaited_once_with(flow.download.return_value, "Solve both")
    flow.agent.assert_awaited_once_with(user=flow.user, message=flow.message)
    basic.assert_not_awaited()
    if latex:
        send_latex.assert_awaited_once_with(
            user=flow.user, llm_content="Solutions", source_chunk_ids=None
        )
        flow.send.assert_not_awaited()
    else:
        flow.send.assert_awaited_once_with(flow.user.wa_id, "Solutions")
        flow.visible.assert_awaited_once_with(
            user=flow.user, content="Solutions", source_chunk_ids=None
        )


@pytest.mark.parametrize(
    "failure,error_key",
    [
        ("disabled", "image_disabled"),
        ("bad_id", "image_invalid"),
        ("unreadable", "image_unreadable"),
        ("provider", "image_processing_failed"),
    ],
)
async def test_image_failure_sends_feedback_instead_of_answering(
    flow, failure, error_key
):
    payload = image_message()["image"]
    if failure == "disabled":
        messaging_service.image_input_settings.image_input_enabled = False
    elif failure == "bad_id":
        payload.pop("id")
    elif failure == "unreadable":
        flow.interpret.return_value = ImageInterpretation(
            transcription="",
            visual_details="",
            readability="unreadable",
            clarification_reason="The equation is blurred",
        )
    else:
        flow.interpret.side_effect = ImageInputError()

    response = await flow.service.handle_image_message(flow.user, flow.message, payload)

    expected = messaging_service.strings.get_string(
        messaging_service.StringCategory.ERROR, error_key
    )
    assert response.status_code == 200
    flow.agent.assert_not_awaited()
    flow.persist.assert_not_awaited()
    flow.send.assert_awaited_once_with(flow.user.wa_id, expected)
    flow.visible.assert_awaited_once_with(flow.user, expected)
    if failure in ("disabled", "bad_id"):
        flow.download.assert_not_awaited()
        flow.interpret.assert_not_awaited()
