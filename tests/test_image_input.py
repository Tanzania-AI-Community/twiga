"""Core image validation and HTTP-boundary tests; no live API calls."""

import base64
import json
import logging
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from app.clients.image_interpreter import ImageInterpreter
from app.clients.whatsapp_client import WhatsAppClient
from app.config import ImageInputSettings
from app.models.image_models import (
    DownloadedImage,
    ImageInputError,
    ImageInterpretation,
)
from app.utils.image_utils import MAX_IMAGE_BYTES, validate_image
from app.utils.logging_utils import private_media_logging


def image_bytes(format="PNG"):
    output = BytesIO()
    image = Image.new("RGB", (12, 8), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(output, format=format, exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_image_validation_orients_and_removes_metadata(format, mime):
    result = validate_image(image_bytes(format), mime)
    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (8, 12)
        assert not image.getexif()
    assert result.mime_type == mime


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"not an image", "image/png"),
        (image_bytes("PNG"), "image/jpeg"),
        (b"x" * (MAX_IMAGE_BYTES + 1), "image/png"),
    ],
    ids=["corrupt", "wrong-format", "oversized"],
)
def test_invalid_images_are_rejected(data, mime):
    with pytest.raises(ImageInputError, match="image_invalid"):
        validate_image(data, mime)


def test_decoded_pixel_limit_is_enforced():
    with patch("app.utils.image_utils.MAX_IMAGE_PIXELS", 60):
        with pytest.raises(ImageInputError, match="image_invalid"):
            validate_image(image_bytes(), "image/png")


@pytest.fixture
async def whatsapp_client():
    client = WhatsAppClient()
    await client.client.aclose()
    yield client
    await client.client.aclose()


def attach_transport(client, handler):
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_download_fetches_metadata_then_authenticated_image(
    whatsapp_client, caplog
):
    requests = []
    data = image_bytes()

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/photo?token=SECRET",
                    "mime_type": "image/png",
                    "file_size": len(data),
                },
            )
        return httpx.Response(200, content=data)

    attach_transport(whatsapp_client, respond)
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        caplog.at_level(logging.DEBUG),
    ):
        result = await whatsapp_client.download_image("12345")

    assert result.mime_type == "image/png"
    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (8, 12)
    assert len(requests) == 2
    assert requests[0].url.path.endswith("/12345")
    assert all(r.headers["authorization"].startswith("Bearer ") for r in requests)
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://lookaside.fbsbx.com/image",
        "https://evil.example/image",
        "https://fbsbx.com.evil.example/image",
        "https://user:password@lookaside.fbsbx.com/image",
    ],
)
async def test_download_does_not_send_token_to_untrusted_url(whatsapp_client, url):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"url": url, "mime_type": "image/png"})

    attach_transport(whatsapp_client, respond)
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        pytest.raises(ImageInputError),
    ):
        await whatsapp_client.download_image("12345")
    assert len(requests) == 1


async def test_download_handles_meta_error(whatsapp_client):
    attach_transport(whatsapp_client, lambda request: httpx.Response(401))
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        pytest.raises(ImageInputError),
    ):
        await whatsapp_client.download_image("12345")


async def test_download_stops_oversized_stream(whatsapp_client):
    class OversizedStream(httpx.AsyncByteStream):
        reads = 0

        async def __aiter__(self):
            for _ in range(1000):
                self.reads += 1
                yield b"x" * (64 * 1024)

    stream = OversizedStream()

    def respond(request):
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/photo",
                    "mime_type": "image/png",
                },
            )
        return httpx.Response(200, stream=stream)

    attach_transport(whatsapp_client, respond)
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        pytest.raises(ImageInputError, match="image_invalid"),
    ):
        await whatsapp_client.download_image("12345")
    assert stream.reads < 1000


def interpretation():
    return ImageInterpretation(
        transcription="1. Solve x + 2 = 3.\n2. Solve y + 1 = 4.",
        visual_details="A triangle labelled ABC",
        readability="clear",
        clarification_reason="",
    )


def completion_response(content=None):
    return httpx.Response(
        200,
        json={
            "id": "completion-test",
            "object": "chat.completion",
            "created": 1,
            "model": "vision-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": (
                            interpretation().model_dump_json()
                            if content is None
                            else content
                        ),
                    },
                }
            ],
        },
    )


@pytest.fixture
def vision_transport(monkeypatch):
    """Use the real SDK with an in-memory HTTP transport."""
    config = ImageInputSettings(
        _env_file=None,
        image_input_enabled=True,
        vision_base_url="https://vision.example/v1",
        vision_model="vision-test",
        vision_api_key="secret-test-key",
    )
    monkeypatch.setattr("app.clients.image_interpreter.image_input_settings", config)

    def install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return patch(
            "app.clients.image_interpreter.httpx",
            SimpleNamespace(AsyncClient=MagicMock(return_value=client)),
        )

    return install


async def test_interpreter_sends_image_and_caption_and_returns_extraction(
    vision_transport, caplog
):
    captured = []

    def respond(request):
        assert request.url == "https://vision.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-test-key"
        captured.append(json.loads(request.content))
        return completion_response()

    with vision_transport(respond), caplog.at_level(logging.DEBUG):
        result = await ImageInterpreter().interpret(
            DownloadedImage(b"private-image-payload", "image/png"), "Solve both"
        )

    assert result == interpretation()
    assert len(captured) == 1
    payload = captured[0]
    assert payload["model"] == "vision-test"
    content = payload["messages"][1]["content"]
    assert "Solve both" in content[0]["text"]
    encoded = base64.b64encode(b"private-image-payload").decode("ascii")
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + encoded
    assert encoded not in caplog.text
    assert "secret-test-key" not in caplog.text


async def test_interpreter_recovers_from_invalid_json(vision_transport):
    requests = []

    def respond(request):
        requests.append(request)
        return completion_response("not json" if len(requests) == 1 else None)

    with vision_transport(respond):
        result = await ImageInterpreter().interpret(
            DownloadedImage(b"x", "image/png"), ""
        )

    assert result == interpretation()
    assert len(requests) == 2


@pytest.mark.parametrize("status,expected_calls", [(401, 1), (500, 2)])
async def test_vision_failure_has_bounded_retries(
    vision_transport, status, expected_calls
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "provider error"}})

    with vision_transport(respond), pytest.raises(ImageInputError):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == expected_calls


def test_private_sdk_logging_restores_normal_logging(caplog):
    sdk_logger = logging.getLogger("openai._base_client")
    with caplog.at_level(logging.DEBUG):
        with private_media_logging():
            sdk_logger.debug("PRIVATE-PHOTO")
        sdk_logger.debug("normal diagnostics")
    assert "PRIVATE-PHOTO" not in caplog.text
    assert "normal diagnostics" in caplog.text
