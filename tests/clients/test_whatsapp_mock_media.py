import json
from functools import partial

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

import app.clients.whatsapp_client as whatsapp_module
from app.clients.whatsapp_client import (
    DocumentType,
    ImageType,
    MockRoutingError,
    WhatsAppClient,
)
from app.config import settings
from app.database.models import User

MOCK_API = "http://127.0.0.1:3100/api/whatsapp"


def use_mock(monkeypatch, receive, enabled=True):
    monkeypatch.setattr(settings, "mock_whatsapp", enabled)
    monkeypatch.setattr(settings, "mock_whatsapp_api_url", MOCK_API)
    monkeypatch.setattr(settings, "mock_whatsapp_token", SecretStr("local-token"))
    monkeypatch.setattr(
        whatsapp_module.httpx,
        "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(receive)),
    )
    return WhatsAppClient()


def mock_meta(requests, media_id="1000000000000001", fail=None):
    def receive(request):
        requests.append(request)
        if fail and fail(request):
            return httpx.Response(500, json={"error": {"code": 131053}})
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": media_id})
        if request.method == "DELETE":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"messages": [{"id": "wamid.mock.1"}]})

    return receive


async def test_mock_image_uploads_sends_and_deletes_locally(monkeypatch, tmp_path):
    requests = []
    client = use_mock(monkeypatch, mock_meta(requests))
    image = tmp_path / "twiga_latex_1.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")

    assert await client.send_image_message("255700000001", str(image), ImageType.PNG)

    upload, send, delete = requests
    assert str(upload.url) == f"{MOCK_API}/media"
    assert upload.headers["authorization"] == "Bearer local-token"
    assert b'name="messaging_product"\r\n\r\nwhatsapp' in upload.content
    assert b'filename="twiga_latex_1.png"' in upload.content
    assert b"Content-Type: image/png" in upload.content
    assert str(send.url) == f"{MOCK_API}/messages"
    assert json.loads(send.content)["image"] == {"id": "1000000000000001"}
    assert (delete.method, str(delete.url)) == (
        "DELETE",
        f"{MOCK_API}/1000000000000001",
    )
    assert not image.exists()


async def test_mock_upload_rejection_returns_false_and_cleans_up(monkeypatch, tmp_path):
    requests = []
    client = use_mock(
        monkeypatch,
        mock_meta(requests, fail=lambda r: r.url.path.endswith("/media")),
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"png")

    assert not await client.send_image_message("1", str(image), ImageType.PNG)
    assert len(requests) == 1
    assert not image.exists()


async def test_mock_document_keeps_cached_exam_files(monkeypatch, tmp_path):
    requests = []
    client = use_mock(monkeypatch, mock_meta(requests))
    exam = tmp_path / "exam_42.pdf"
    exam.write_bytes(b"%PDF-1.7")

    assert await client.send_document_message(
        "1", str(exam), DocumentType.PDF, filename=exam.name
    )
    assert json.loads(requests[1].content)["document"] == {
        "id": "1000000000000001",
        "filename": "exam_42.pdf",
    }
    assert exam.exists()


async def test_mock_flow_message_reaches_the_simulator(monkeypatch):
    requests = []
    client = use_mock(monkeypatch, mock_meta(requests))
    monkeypatch.setattr(
        settings,
        "flow_token_encryption_key",
        SecretStr(Fernet.generate_key().decode()),
    )
    user = User(id=1, wa_id="255700000001", name="Teacher")

    await client.send_whatsapp_flow_message(
        user=user,
        flow_id="1000000000000001",
        header_text="Header",
        body_text="Body",
        action_payload={"screen": "select_subject", "data": {}},
        flow_cta="Select",
    )

    parameters = json.loads(requests[0].content)["interactive"]["action"]["parameters"]
    assert str(requests[0].url) == f"{MOCK_API}/messages"
    assert parameters["flow_id"] == "1000000000000001"
    assert parameters["flow_token"]


@pytest.mark.parametrize(
    "url",
    [
        "https://graph.facebook.com/v22.0/1000000000000001",
        "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
        "http://127.0.0.1:3101/api/whatsapp/messages",
    ],
)
async def test_mock_mode_fails_closed_for_any_other_destination(monkeypatch, url):
    requests = []
    client = use_mock(monkeypatch, mock_meta(requests))

    with pytest.raises(MockRoutingError):
        await client.client.get(url, headers=client.headers)
    with pytest.raises(MockRoutingError):
        await client.client.delete(url)
    assert requests == []


async def test_production_media_routing_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "meta_api_version", "v22.0")
    monkeypatch.setattr(settings, "whatsapp_cloud_number_id", "123456789")
    monkeypatch.setattr(settings, "whatsapp_api_token", SecretStr("meta-token"))
    requests = []
    client = use_mock(monkeypatch, mock_meta(requests), enabled=False)
    image = tmp_path / "image.png"
    image.write_bytes(b"png")

    assert client.client.event_hooks["request"] == []
    assert await client.send_image_message("1", str(image), ImageType.PNG)

    assert [(r.method, str(r.url)) for r in requests] == [
        ("POST", "https://graph.facebook.com/v22.0/123456789/media"),
        ("POST", "https://graph.facebook.com/v22.0/123456789/messages"),
        ("DELETE", "https://graph.facebook.com/v22.0/1000000000000001"),
    ]
    assert requests[0].headers["authorization"] == "Bearer meta-token"


async def test_mock_requests_ignore_environment_proxy(monkeypatch):
    import asyncio

    async def respond(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nlocal"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(settings, "mock_whatsapp", True)
    monkeypatch.setattr(
        settings, "mock_whatsapp_api_url", f"http://127.0.0.1:{port}/api/whatsapp"
    )
    monkeypatch.setattr(settings, "mock_whatsapp_token", SecretStr("local-token"))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    client = WhatsAppClient()
    try:
        response = await client.client.get(client.media_url("1000000000000001"))
        assert response.text == "local"
    finally:
        await client.client.aclose()
        server.close()
        await server.wait_closed()
