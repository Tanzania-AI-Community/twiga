import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

from app.clients.whatsapp_client import DocumentType, ImageType, WhatsAppClient
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


async def test_media_and_interactive_with_local_mock(monkeypatch, tmp_path):
    origin = os.environ["MOCK_WHATSAPP_TEST_URL"].rstrip("/")
    assert urlsplit(origin).hostname in ("127.0.0.1", "localhost", "::1")
    recipient = f"2557{int(uuid4().hex[:8], 16):010d}"
    monkeypatch.setattr(settings, "mock_whatsapp", True)
    monkeypatch.setattr(settings, "mock_whatsapp_api_url", f"{origin}/api/whatsapp")
    client = WhatsAppClient()
    # A real 1x1 RGB PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
    )
    try:
        image = tmp_path / "twiga_latex_1.png"
        image.write_bytes(png)
        assert await client.send_image_message(recipient, str(image), ImageType.PNG)
        assert not image.exists()

        exam = tmp_path / "exam_1.pdf"
        exam.write_bytes(b"%PDF-1.4\n%%EOF")
        assert await client.send_document_message(
            recipient, str(exam), DocumentType.PDF, filename="exam_1.pdf"
        )
        assert exam.exists()

        # The download path that inbound media support would use
        media_id = await client.upload_media(
            str(exam), "application/pdf", 100 * 1024 * 1024
        )
        assert media_id and media_id.isdigit()
        info = await client.client.get(
            client.media_url(media_id), headers=client.headers
        )
        info.raise_for_status()
        download = await client.client.get(info.json()["url"], headers=client.headers)
        assert download.content == exam.read_bytes()
        await client.delete_media(media_id, str(exam), delete_local_file=False)
        gone = await client.client.get(
            client.media_url(media_id), headers=client.headers
        )
        assert gone.status_code == 404

        assert await client.send_message(recipient, "Menu", ["Profile", "Classes"])
        assert not await client.send_message(recipient, "Menu", ["x" * 21])

        async with httpx.AsyncClient(base_url=origin, trust_env=False) as mock:
            response = await mock.get("/api/events", params={"recipientId": recipient})
            response.raise_for_status()
            events = [
                event
                for event in response.json()["events"]
                if event["recipientId"] == recipient
            ]
    finally:
        await client.client.aclose()
    outgoing = [event["payload"] for event in events if event["kind"] == "outgoing"]
    assert [payload["type"] for payload in outgoing] == [
        "image",
        "document",
        "interactive",
    ]
    assert outgoing[1]["document"]["filename"] == "exam_1.pdf"
    deleted = {event["mediaId"] for event in events if event["kind"] == "media_deleted"}
    assert {outgoing[0]["image"]["id"], outgoing[1]["document"]["id"]} <= deleted
    assert any(
        event["kind"] == "rejected" and "title" in event["error"] for event in events
    )
