from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

import app.database.enums as enums
from app.database.models import Message, User
from app.services import request_service
from app.utils.whatsapp_utils import RequestType


class _DummyRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


@pytest.mark.asyncio
async def test_handle_request_awaits_flow_complete_handler() -> None:
    body = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    request = _DummyRequest(body)
    expected_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.get_request_type",
            return_value=RequestType.FLOW_COMPLETE,
        ),
        patch("app.services.request_service.record_whatsapp_event"),
        patch(
            "app.services.request_service.whatsapp_client.handle_flow_message_complete",
            AsyncMock(return_value=expected_response),
        ) as mock_flow_complete_handler,
    ):
        response = await request_service.handle_request(request)

    assert response is expected_response
    mock_flow_complete_handler.assert_awaited_once_with(body)


@pytest.mark.asyncio
async def test_handle_valid_message_routes_with_inbound_message_id() -> None:
    inbound_message_id = "wamid.ABC123"
    wa_id = "255700000009"
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": wa_id, "profile": {"name": "Teacher"}}
                            ],
                            "messages": [
                                {
                                    "id": inbound_message_id,
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    expected_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.handle_chat_message",
            AsyncMock(return_value=expected_response),
        ) as mock_handle_chat_message,
    ):
        response = await request_service.handle_valid_message(body)

    assert response is expected_response
    called_wa_id, called_message_info = mock_handle_chat_message.await_args.args
    assert called_wa_id == wa_id
    assert called_message_info["inbound_message_id"] == inbound_message_id
    assert called_message_info["extracted_content"] == "Hello"


@pytest.mark.asyncio
async def test_handle_valid_message_transcribes_audio_before_routing() -> None:
    wa_id = "255700000009"
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": wa_id, "profile": {"name": "Teacher"}}
                            ],
                            "messages": [
                                {
                                    "id": "wamid.AUDIO123",
                                    "timestamp": "1710000000",
                                    "type": "audio",
                                    "audio": {
                                        "id": "media-123",
                                        "mime_type": "audio/ogg; codecs=opus",
                                        "voice": True,
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    expected_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.whatsapp_client.download_media",
            AsyncMock(return_value=(b"audio bytes", "audio/ogg")),
        ) as mock_download_media,
        patch(
            "app.services.request_service.audio_transcription_service.transcribe",
            AsyncMock(return_value="Nisaidie kuelewa photosynthesis"),
        ) as mock_transcribe,
        patch(
            "app.services.request_service.handle_chat_message",
            AsyncMock(return_value=expected_response),
        ) as mock_handle_chat_message,
    ):
        response = await request_service.handle_valid_message(body)

    assert response is expected_response
    mock_download_media.assert_awaited_once_with("media-123")
    mock_transcribe.assert_awaited_once_with(b"audio bytes", "audio/ogg")
    called_wa_id, called_message_info = mock_handle_chat_message.await_args.args
    assert called_wa_id == wa_id
    assert called_message_info["extracted_content"] == (
        "Nisaidie kuelewa photosynthesis"
    )


@pytest.mark.asyncio
async def test_handle_valid_message_accepts_inline_audio_in_mock_mode() -> None:
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {
                                    "wa_id": "255700000009",
                                    "profile": {"name": "Teacher"},
                                }
                            ],
                            "messages": [
                                {
                                    "id": "wamid.MOCKAUDIO",
                                    "timestamp": "1710000000",
                                    "type": "audio",
                                    "audio": {
                                        "id": "mock-media-123",
                                        "mime_type": "audio/mp4",
                                        "data": "YXVkaW8=",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    expected_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch.object(request_service.settings, "mock_whatsapp", True),
        patch(
            "app.services.request_service.whatsapp_client.download_media",
            AsyncMock(),
        ) as mock_download_media,
        patch(
            "app.services.request_service.audio_transcription_service.transcribe",
            AsyncMock(return_value="Habari mwalimu"),
        ) as mock_transcribe,
        patch(
            "app.services.request_service.handle_chat_message",
            AsyncMock(return_value=expected_response),
        ) as mock_handle_chat_message,
    ):
        response = await request_service.handle_valid_message(body)

    assert response is expected_response
    mock_download_media.assert_not_awaited()
    mock_transcribe.assert_awaited_once_with(b"audio", "audio/mp4")
    assert mock_handle_chat_message.await_args.args[1]["extracted_content"] == (
        "Habari mwalimu"
    )


@pytest.mark.asyncio
async def test_handle_valid_message_acknowledges_audio_transcription_failure() -> None:
    wa_id = "255700000009"
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": wa_id, "profile": {"name": "Teacher"}}
                            ],
                            "messages": [
                                {
                                    "id": "wamid.AUDIO123",
                                    "timestamp": "1710000000",
                                    "type": "audio",
                                    "audio": {"id": "media-123"},
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
            "app.services.request_service.whatsapp_client.download_media",
            AsyncMock(side_effect=ValueError("download failed")),
        ),
        patch(
            "app.services.request_service.whatsapp_client.send_message",
            AsyncMock(return_value=True),
        ) as mock_send_message,
        patch(
            "app.services.request_service.handle_chat_message", AsyncMock()
        ) as mock_handle_chat_message,
    ):
        response = await request_service.handle_valid_message(body)

    assert response.status_code == 200
    mock_send_message.assert_awaited_once_with(
        wa_id,
        "Samahani, sikuweza kusoma ujumbe wako wa sauti. Tafadhali jaribu tena "
        "au utume ujumbe wa maandishi.",
    )
    mock_handle_chat_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_chat_message_persists_inbound_message_and_routes_active() -> None:
    user = User(
        id=7,
        wa_id="255700000000",
        name="Teacher",
        state=enums.UserState.active,
    )
    persisted_message = Message(
        user_id=user.id,
        role=enums.MessageRole.user,
        content="Hello",
        is_present_in_conversation=True,
    )

    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields",
            AsyncMock(return_value=persisted_message),
        ) as mock_create_new_message_by_fields,
        patch(
            "app.services.request_service.state_client._handle_rate_limiting",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.request_service.state_client.handle_active",
            AsyncMock(
                return_value=JSONResponse(content={"status": "ok"}, status_code=200)
            ),
        ) as mock_handle_active,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Hello"},
        )

    assert response.status_code == 200
    assert mock_create_new_message_by_fields.await_args.kwargs == {
        "user_id": user.id,
        "role": enums.MessageRole.user,
        "content": "Hello",
        "is_present_in_conversation": True,
    }
    mock_handle_active.assert_awaited_once_with(
        user,
        {"extracted_content": "Hello"},
        persisted_message,
    )


@pytest.mark.asyncio
async def test_handle_chat_message_persists_inbound_message_before_rate_limit_return() -> (
    None
):
    user = User(
        id=8,
        wa_id="255700000001",
        name="Teacher",
        state=enums.UserState.active,
    )
    rate_limit_response = JSONResponse(content={"status": "ok"}, status_code=200)

    with (
        patch(
            "app.services.request_service.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.services.request_service.db.create_new_message_by_fields",
            AsyncMock(
                return_value=Message(
                    user_id=user.id,
                    role=enums.MessageRole.user,
                    content="Hi",
                    is_present_in_conversation=True,
                )
            ),
        ) as mock_create_new_message_by_fields,
        patch(
            "app.services.request_service.state_client._handle_rate_limiting",
            AsyncMock(return_value=rate_limit_response),
        ),
        patch(
            "app.services.request_service.state_client.handle_active",
            AsyncMock(),
        ) as mock_handle_active,
    ):
        response = await request_service.handle_chat_message(
            phone_number=user.wa_id,
            message_info={"extracted_content": "Hi"},
        )

    assert response is rate_limit_response
    mock_create_new_message_by_fields.assert_awaited_once()
    mock_handle_active.assert_not_awaited()
