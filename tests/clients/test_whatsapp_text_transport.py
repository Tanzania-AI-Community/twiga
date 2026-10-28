import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.whatsapp_client import WhatsAppClient
from app.config import settings
from app.utils.whatsapp_utils import generate_payload


def use_mock(monkeypatch, enabled=True):
    monkeypatch.setattr(settings, "mock_whatsapp", enabled)
    monkeypatch.setattr(
        settings, "mock_whatsapp_api_url", "http://127.0.0.1:3100/api/whatsapp"
    )
    monkeypatch.setattr(settings, "mock_whatsapp_token", SecretStr("local-token"))


async def send_with(client, receive, *args):
    await client.client.aclose()
    async with httpx.AsyncClient(
        base_url=client.url, transport=httpx.MockTransport(receive)
    ) as transport:
        client.client = transport
        return await client.send_message(*args)


async def test_production_keeps_meta_destination_and_form_encoding(monkeypatch):
    use_mock(monkeypatch, enabled=False)
    client = WhatsAppClient()
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200)

    assert await send_with(client, receive, "255700000001", "Hello 🦒")
    request = requests[0]
    expected = httpx.Request(
        "POST", "https://x", data=generate_payload("255700000001", "Hello 🦒")
    )
    assert request.content == expected.content
    assert request.url.host == "graph.facebook.com"
    assert (
        request.url.path
        == f"/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}/messages"
    )
    assert (
        request.headers["authorization"]
        == f"Bearer {settings.whatsapp_api_token.get_secret_value()}"
    )


async def test_mock_sends_json_to_the_local_receiver(monkeypatch):
    use_mock(monkeypatch)
    client = WhatsAppClient()
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.test"}]})

    assert await send_with(client, receive, "255700000001", "Hello 🦒")
    assert await send_with(client, receive, "1", "Select", ["a", "b", "c", "d"])
    request = requests[0]
    assert str(request.url) == "http://127.0.0.1:3100/api/whatsapp/messages"
    assert request.headers["authorization"] == "Bearer local-token"
    assert json.loads(request.content) == generate_payload("255700000001", "Hello 🦒")
    assert json.loads(requests[1].content)["type"] == "interactive"


@pytest.mark.parametrize("reject_second", [False, True])
async def test_long_text_preserves_chunks_and_stops_on_rejection(
    monkeypatch, reject_second
):
    use_mock(monkeypatch)
    client = WhatsAppClient()
    chunks = []

    def receive(request):
        chunks.append(json.loads(request.content)["text"]["body"])
        return httpx.Response(429 if reject_second and len(chunks) == 2 else 200)

    sent = await send_with(client, receive, "255700000001", "x" * 9001)
    assert sent is not reject_second
    assert [len(chunk) for chunk in chunks] == (
        [4000, 4000] if reject_second else [4000, 4000, 1001]
    )


async def test_mock_read_receipt_and_typing_use_the_same_transport(monkeypatch):
    use_mock(monkeypatch)
    client = WhatsAppClient()
    await client.client.aclose()
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(
        base_url=client.url, transport=httpx.MockTransport(receive)
    ) as transport:
        client.client = transport
        await client.send_read_receipt_with_typing_indicator("wamid.inbound")
        await client.send_read_receipt_with_typing_indicator("")
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.inbound",
        "typing_indicator": {"type": "text"},
    }


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_transport_errors_return_false_without_retry(monkeypatch, failure):
    use_mock(monkeypatch)
    client = WhatsAppClient()
    attempts = 0

    def receive(request):
        nonlocal attempts
        attempts += 1
        raise failure("Simulated local failure", request=request)

    assert not await send_with(client, receive, "255700000001", "Hello")
    assert attempts == 1
