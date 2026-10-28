from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.clients.whatsapp_client import WhatsAppClient
from app.database.enums import MessageRole
from app.database.models import User


@pytest.mark.asyncio
async def test_flow_complete_event_persists_visible_user_interaction() -> None:
    client = WhatsAppClient()
    user = User(id=51, wa_id="255700000444", name="Teacher")
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": user.wa_id}],
                            "messages": [
                                {
                                    "interactive": {
                                        "nfm_reply": {
                                            "response_json": {
                                                "flow_token": "token-1",
                                                "field_1": "value-1",
                                            }
                                        }
                                    }
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
            "app.clients.whatsapp_client.db.get_user_by_waid",
            AsyncMock(return_value=user),
        ),
        patch(
            "app.clients.whatsapp_client.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await client.handle_flow_message_complete(body)

    assert response.status_code == 200
    persisted_kwargs = mock_create_message_by_fields.await_args.kwargs
    assert persisted_kwargs["user_id"] == user.id
    assert persisted_kwargs["role"] == MessageRole.user
    assert persisted_kwargs["is_present_in_conversation"] is True
    assert persisted_kwargs["content"].startswith("[FLOW_COMPLETED]")
    assert '"field_1": "value-1"' in persisted_kwargs["content"]

    await client.client.aclose()


@pytest.mark.asyncio
async def test_send_read_receipt_with_typing_indicator_posts_expected_payload() -> None:
    client = WhatsAppClient()
    inbound_message_id = "wamid.ABC123"

    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        patch.object(client.client, "post", AsyncMock()) as mock_post,
        patch("app.clients.whatsapp_client.log_httpx_response"),
    ):
        await client.send_read_receipt_with_typing_indicator(inbound_message_id)

    mock_post.assert_awaited_once_with(
        "/messages",
        json={
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": inbound_message_id,
            "typing_indicator": {"type": "text"},
        },
        headers=client.headers,
    )

    await client.client.aclose()


@pytest.mark.asyncio
async def test_flow_complete_event_parses_string_payload_and_skips_unknown_user() -> (
    None
):
    client = WhatsAppClient()
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "255700000445"}],
                            "messages": [
                                {
                                    "interactive": {
                                        "nfm_reply": {
                                            "response_json": '{"flow_token":"token-2","field_2":"value-2"}'
                                        }
                                    }
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
            "app.clients.whatsapp_client.db.get_user_by_waid",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.clients.whatsapp_client.db.create_new_message_by_fields",
            AsyncMock(),
        ) as mock_create_message_by_fields,
    ):
        response = await client.handle_flow_message_complete(body)

    assert response.status_code == 200
    mock_create_message_by_fields.assert_not_awaited()

    await client.client.aclose()


@pytest.mark.asyncio
async def test_send_read_receipt_with_typing_indicator_skips_empty_message_id() -> None:
    client = WhatsAppClient()

    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        patch.object(client.client, "post", AsyncMock()) as mock_post,
    ):
        await client.send_read_receipt_with_typing_indicator("")

    mock_post.assert_not_awaited()

    await client.client.aclose()


@pytest.mark.asyncio
async def test_download_media_fetches_metadata_then_audio() -> None:
    client = WhatsAppClient()
    metadata_response = httpx.Response(
        200,
        json={
            "url": "https://lookaside.fbsbx.com/whatsapp/media-123",
            "mime_type": "audio/ogg; codecs=opus",
            "file_size": 5,
        },
        request=httpx.Request("GET", "https://graph.facebook.com/media-123"),
    )
    audio_response = httpx.Response(
        200,
        content=b"audio",
        request=httpx.Request("GET", "https://lookaside.fbsbx.com/whatsapp/media-123"),
    )

    with patch.object(
        client.client,
        "get",
        AsyncMock(side_effect=[metadata_response, audio_response]),
    ) as mock_get:
        content, mime_type = await client.download_media("media-123")

    assert content == b"audio"
    assert mime_type == "audio/ogg; codecs=opus"
    assert mock_get.await_count == 2
    assert mock_get.await_args_list[0].args == (
        f"https://graph.facebook.com/{client.api_version}/media-123",
    )
    assert mock_get.await_args_list[1].args == (
        "https://lookaside.fbsbx.com/whatsapp/media-123",
    )

    await client.client.aclose()
