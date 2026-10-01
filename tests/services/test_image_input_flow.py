from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.clients.client_base import ClientBase
from app.config import Prompt
from app.database import db
from app.database.enums import MessageRole, UserState
from app.database.models import Message, User
from app.models.image_models import (
    DownloadedImage,
    ImageInputError,
    ImageInterpretation,
)
from app.services import request_service
from app.services.messaging_service import MessagingService
from app.services.state_service import StateHandler
from app.utils.prompt_manager import prompt_manager
from app.utils.whatsapp_utils import (
    RequestType,
    ValidMessageType,
    extract_message,
    extract_message_info,
    get_valid_message_type,
    split_message_payloads,
)


def image_message(caption=None, sender="255700000000", identifier="wamid.test"):
    image = {"id": "12345", "mime_type": "image/png"}
    if caption is not None:
        image["caption"] = caption
    return {
        "id": identifier,
        "from": sender,
        "timestamp": "1710000000",
        "type": "image",
        "image": image,
    }


def webhook(messages):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": messages,
                            "contacts": [
                                {
                                    "wa_id": m["from"],
                                    "profile": {"name": f"Teacher {i}"},
                                }
                                for i, m in enumerate(messages)
                            ],
                        }
                    }
                ]
            }
        ],
    }


def clear_interpretation():
    return ImageInterpretation(
        transcription="1. x + 2 = 3\n2. y + 1 = 4",
        visual_details="",
        readability="clear",
        clarification_reason="",
    )


@pytest.mark.parametrize("caption", [None, "", "Solve both", "help"])
def test_image_caption_is_preserved_and_not_a_command(caption):
    message = image_message(caption)
    assert get_valid_message_type({"message": message}) is ValidMessageType.IMAGE
    assert "Source: teacher image" in extract_message(message)
    assert f"Teacher instruction: {caption or 'none'}" in extract_message(message)


def test_batch_preserves_each_sender_and_does_not_mutate_payload():
    body = webhook([image_message(), image_message(sender="255700000001")])
    payloads = split_message_payloads(body)
    assert len(payloads) == 2
    assert len(body["entry"][0]["changes"][0]["value"]["messages"]) == 2
    assert [extract_message_info(p)["wa_id"] for p in payloads] == [
        "255700000000",
        "255700000001",
    ]
    assert [extract_message_info(p)["name"] for p in payloads] == [
        "Teacher 0",
        "Teacher 1",
    ]


def test_batch_covers_all_entries_and_changes():
    body = webhook([image_message()])
    change = webhook([image_message(sender="255700000001")])["entry"][0]["changes"][0]
    body["entry"][0]["changes"].append(change)
    body["entry"].append(webhook([image_message(sender="255700000002")])["entry"][0])
    assert [extract_message_info(p)["wa_id"] for p in split_message_payloads(body)] == [
        "255700000000",
        "255700000001",
        "255700000002",
    ]


async def test_batch_classifies_all_messages_before_slow_processing():
    request = MagicMock(
        json=AsyncMock(
            return_value=webhook(
                [image_message(), image_message(identifier="wamid.second")]
            )
        )
    )
    events = []

    def classify(body):
        events.append("classify")
        return RequestType.VALID_MESSAGE

    async def handle(body):
        events.append("handle")
        return JSONResponse({"status": "ok"})

    with (
        patch("app.services.request_service.get_request_type", side_effect=classify),
        patch(
            "app.services.request_service.handle_valid_message", side_effect=handle
        ) as handler,
    ):
        response = await request_service.handle_request(request)
    assert response.status_code == 200
    assert events == ["classify", "classify", "handle", "handle"]
    assert handler.await_count == 2


async def test_batch_continues_after_one_message_fails():
    request = MagicMock(
        json=AsyncMock(
            return_value=webhook(
                [image_message(), image_message(identifier="wamid.second")]
            )
        )
    )
    with (
        patch(
            "app.services.request_service.get_request_type",
            return_value=RequestType.VALID_MESSAGE,
        ),
        patch(
            "app.services.request_service.handle_valid_message",
            AsyncMock(
                side_effect=[RuntimeError("failure"), JSONResponse({"status": "ok"})]
            ),
        ) as handler,
    ):
        response = await request_service.handle_request(request)
    assert response.status_code == 500
    assert handler.await_count == 2


@pytest.mark.parametrize(
    "state,handler",
    [
        (UserState.blocked, "handle_blocked"),
        (UserState.onboarding, "handle_onboarding"),
        (UserState.in_review, "handle_in_review_user"),
        (UserState.approved, "handle_new_approved_user"),
    ],
)
async def test_user_state_gate_prevents_image_processing(state, handler):
    user = User(id=7, wa_id="255700000000", state=state)
    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields", AsyncMock()
        ),
        patch.object(
            request_service.state_client,
            "_handle_rate_limiting",
            AsyncMock(return_value=None),
        ),
        patch.object(
            request_service.state_client,
            handler,
            AsyncMock(return_value=JSONResponse({"status": "ok"})),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.download_image", AsyncMock()
        ) as download,
        patch(
            "app.services.messaging_service.image_interpreter.interpret", AsyncMock()
        ) as interpret,
    ):
        response = await request_service.handle_valid_message(
            webhook([image_message()])
        )
    assert response.status_code == 200
    download.assert_not_awaited()
    interpret.assert_not_awaited()


async def test_rate_limit_gate_prevents_image_processing():
    user = User(id=7, wa_id="255700000000", state=UserState.active)
    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields", AsyncMock()
        ),
        patch.object(
            request_service.state_client,
            "_handle_rate_limiting",
            AsyncMock(return_value=JSONResponse({"status": "ok"})),
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.download_image", AsyncMock()
        ) as download,
        patch(
            "app.services.messaging_service.image_interpreter.interpret", AsyncMock()
        ) as interpret,
    ):
        await request_service.handle_valid_message(webhook([image_message()]))
    download.assert_not_awaited()
    interpret.assert_not_awaited()


async def test_active_state_routes_image_after_read_receipt():
    message = image_message()
    user = User(id=7, wa_id=message["from"])
    persisted = Message(
        id=9, user_id=7, role=MessageRole.user, content=extract_message(message)
    )
    with (
        patch(
            "app.services.state_service.whatsapp_client.send_read_receipt_with_typing_indicator",
            AsyncMock(),
        ) as receipt,
        patch(
            "app.services.state_service.messaging_client.handle_image_message",
            AsyncMock(return_value=JSONResponse({"status": "ok"})),
        ) as handler,
    ):
        await StateHandler().handle_active(
            user, {"inbound_message_id": message["id"], "message": message}, persisted
        )
    receipt.assert_awaited_once_with(message["id"])
    handler.assert_awaited_once_with(user, persisted, message["image"])


@pytest.fixture
def flow():
    service = MessagingService()
    user = User(id=7, wa_id="255700000000")
    message = Message(
        id=9,
        user_id=7,
        role=MessageRole.user,
        content="Source: teacher image",
        is_present_in_conversation=True,
    )

    async def update(message, content):
        message.content = content

    with (
        patch(
            "app.services.messaging_service.image_input_settings.image_input_enabled",
            True,
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.download_image",
            AsyncMock(return_value=DownloadedImage(b"pixels", "image/png")),
        ) as download,
        patch(
            "app.services.messaging_service.image_interpreter.interpret",
            AsyncMock(return_value=clear_interpretation()),
        ) as interpret,
        patch(
            "app.services.messaging_service.db.update_message_content",
            AsyncMock(side_effect=update),
        ) as persist,
        patch.object(
            service, "_persist_visible_assistant_message", AsyncMock()
        ) as visible,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message", AsyncMock()
        ) as send,
    ):
        yield service, user, message, download, interpret, persist, visible, send


@pytest.mark.parametrize("latex", [False, True])
async def test_image_reuses_agent_citations_and_delivery_even_in_basic_mode(
    flow, latex
):
    service, user, message, download, interpret, persist, visible, send = flow
    answer = Message(
        user_id=7,
        role=MessageRole.assistant,
        content="Two solutions",
        source_chunk_ids=[3],
    )

    async def generate(**kwargs):
        assert message.id == 9
        assert "Teacher instruction: Solve both" in message.content
        assert "2. y + 1 = 4" in message.content
        persist.assert_awaited_once()
        return [answer]

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.agent_client.generate_response",
            AsyncMock(side_effect=generate),
        ) as agent,
        patch(
            "app.services.messaging_service.llm_client.generate_response", AsyncMock()
        ) as basic,
        patch("app.services.messaging_service.db.create_new_messages", AsyncMock()),
        patch.object(
            service, "_handle_citations", AsyncMock(return_value="Rendered answer")
        ) as citations,
        patch.object(service, "_is_response_in_latex", return_value=latex),
        patch.object(service, "_send_latex_response", AsyncMock()) as send_latex,
    ):
        response = await service.handle_image_message(
            user, message, image_message("Solve both")["image"]
        )
    assert response.status_code == 200
    download.assert_awaited_once_with("12345")
    interpret.assert_awaited_once()
    agent.assert_awaited_once_with(user=user, message=message)
    basic.assert_not_awaited()
    citations.assert_awaited_once_with(llm_content="Two solutions")
    if latex:
        send_latex.assert_awaited_once_with(
            user=user, llm_content="Rendered answer", source_chunk_ids=[3]
        )
    else:
        send.assert_awaited_once_with(user.wa_id, "Rendered answer")
        visible.assert_awaited_once_with(
            user=user, content="Rendered answer", source_chunk_ids=[3]
        )


@pytest.mark.parametrize(
    "failure",
    [
        "disabled",
        "bad_id",
        "download",
        "provider",
        "partial",
        "unreadable",
        "too_long",
        "database",
    ],
)
async def test_image_failure_is_visible_persisted_and_does_not_call_agent(
    flow, failure, caplog
):
    service, user, message, download, interpret, persist, visible, send = flow
    payload = image_message()["image"]
    if failure == "bad_id":
        payload.pop("id")
    elif failure == "download":
        download.side_effect = ImageInputError()
    elif failure == "provider":
        interpret.side_effect = RuntimeError("PRIVATE-PAYLOAD")
    elif failure in ("partial", "unreadable"):
        interpret.return_value = clear_interpretation().model_copy(
            update={"readability": failure, "clarification_reason": "Unclear sign"}
        )
    elif failure == "too_long":
        interpret.return_value = clear_interpretation().model_copy(
            update={"transcription": "x" * 66000}
        )
    elif failure == "database":
        persist.side_effect = RuntimeError("PRIVATE-PAYLOAD")
    with (
        patch(
            "app.services.messaging_service.image_input_settings.image_input_enabled",
            failure != "disabled",
        ),
        patch(
            "app.services.messaging_service.agent_client.generate_response", AsyncMock()
        ) as agent,
    ):
        response = await service.handle_image_message(user, message, payload)
    assert response.status_code == 200
    agent.assert_not_awaited()
    visible.assert_awaited_once()
    send.assert_awaited_once_with(user.wa_id, visible.await_args.args[1])
    if failure in ("disabled", "bad_id"):
        download.assert_not_awaited()
        interpret.assert_not_awaited()
    assert "PRIVATE-PAYLOAD" not in caplog.text


async def test_db_update_changes_same_row_only_after_success():
    message = Message(id=9, user_id=7, role=MessageRole.user, content="placeholder")
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=1)

    @asynccontextmanager
    async def context():
        yield session

    with patch("app.database.db.get_session", context):
        await db.update_message_content(message, "normalized")
    statement = session.execute.await_args.args[0]
    assert statement.compile().params == {
        "content": "normalized",
        "id_1": 9,
        "user_id_1": 7,
    }
    assert message.content == "normalized"
    assert message.id == 9
    session.add.assert_not_called()


def test_followup_history_reuses_extraction_as_text():
    user = User(id=7, wa_id="255700000000")
    image = Message(
        id=9,
        user_id=7,
        role=MessageRole.user,
        content=clear_interpretation().to_request_text("Solve both"),
    )
    followup = Message(
        id=10, user_id=7, role=MessageRole.user, content="Explain the second solution"
    )
    result = ClientBase._format_messages(
        [followup], [image, followup], user, Prompt.TWIGA_AGENT_SYSTEM
    )
    assert result[1]["content"] == image.content
    assert result[2]["content"] == followup.content
    assert all(isinstance(m["content"], str) for m in result)


def test_image_prompt_preserves_search_first_policy_and_multi_question_support():
    prompt = prompt_manager.format_prompt(
        Prompt.TWIGA_AGENT_SYSTEM, user_name="Teacher", class_info="Math"
    )
    assert "Source: teacher image" in prompt
    assert "Multiple readable questions may be answered in one response" in prompt
    assert "You MUST call `search_knowledge` before answering" in prompt
    assert "Always respond in English" in prompt
