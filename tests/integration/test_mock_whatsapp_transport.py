import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

from app.clients.whatsapp_client import WhatsAppClient
from app.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("MOCK_WHATSAPP_TEST_URL"),
        reason="Start the local mock and set MOCK_WHATSAPP_TEST_URL",
    ),
]


async def test_text_transport_with_local_mock(monkeypatch):
    origin = os.environ["MOCK_WHATSAPP_TEST_URL"].rstrip("/")
    url = urlsplit(origin)
    assert url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
    assert not url.username and not url.password and not url.query and not url.fragment
    assert settings.mock_whatsapp_token
    recipient = f"2557{int(uuid4().hex[:8], 16):010d}"
    message_id = f"wamid.integration.{uuid4().hex}"
    monkeypatch.setattr(settings, "mock_whatsapp", True)
    monkeypatch.setattr(settings, "mock_whatsapp_api_url", f"{origin}/api/whatsapp")
    client = WhatsAppClient()
    token = settings.mock_whatsapp_token.get_secret_value()
    try:
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as mock:
            seeded = await mock.post(
                "/api/inbound",
                headers={"Origin": origin},
                json={
                    "body": "help",
                    "recipientId": recipient,
                    "messageId": message_id,
                },
            )
            assert (
                seeded.status_code == 502
            ), "Run the mock with CHATBOT_CALLBACK_URL=http://127.0.0.1:1/devhooks"
            await client.send_read_receipt_with_typing_indicator(message_id)
            assert await client.send_message(recipient, "Working...")
            assert await client.send_message(recipient, "x" * 9001)
            configured = await mock.put(
                "/api/whatsapp/faults",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "rule": {
                        "target": "text",
                        "recipientId": recipient,
                        "skip": 1,
                        "status": 429,
                    }
                },
            )
            configured.raise_for_status()
            assert not await client.send_message(recipient, "y" * 9001)
            assert all(
                await asyncio.gather(
                    client.send_message(recipient, "first"),
                    client.send_message(recipient, "second"),
                )
            )
            response = await mock.get("/api/events", params={"recipientId": recipient})
            response.raise_for_status()
            events = response.json()["events"]
    finally:
        await client.client.aclose()
    outgoing = [event for event in events if event["kind"] == "outgoing"]
    bodies = [event["payload"]["text"]["body"] for event in outgoing]
    assert bodies[:5] == ["Working...", "x" * 4000, "x" * 4000, "x" * 1001, "y" * 4000]
    assert set(bodies[5:]) == {"first", "second"}
    assert len({event["messageId"] for event in outgoing}) == len(outgoing)
    assert len([event for event in events if event["kind"] == "rejected"]) == 1
    assert any(
        event["kind"] == "action" and event["payload"]["message_id"] == message_id
        for event in events
    )
