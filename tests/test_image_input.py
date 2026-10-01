"""Deterministic image-boundary tests; real Meta acceptance is documented separately."""

import logging
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.clients.image_interpreter import ImageInterpreter
from app.clients.whatsapp_client import WhatsAppClient
from app.config import ImageInputSettings
from app.models.image_models import (
    DownloadedImage,
    ImageInputError,
    ImageInterpretation,
)
from app.utils.image_utils import MAX_IMAGE_BYTES, validate_image
from app.utils.logging_utils import log_httpx_response, private_media_logging


def image_bytes(format="PNG", orientation=None):
    output = BytesIO()
    image = Image.new("RGB", (12, 8), "white")
    kwargs = {}
    if orientation:
        exif = image.getexif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(output, format=format, **kwargs)
    return output.getvalue()


def interpretation(**overrides):
    return ImageInterpretation(
        **{
            "transcription": "1. Solve x + 2 = 3.\n2. Solve y + 1 = 4.",
            "visual_details": "",
            "readability": "clear",
            "clarification_reason": "",
            **overrides,
        }
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_vision_configuration_is_only_required_when_enabled(enabled):
    kwargs = dict(
        _env_file=None,
        image_input_enabled=enabled,
        vision_base_url="",
        vision_model="",
        vision_api_key="",
    )
    if enabled:
        with pytest.raises(ValidationError):
            ImageInputSettings(**kwargs)
    else:
        assert not ImageInputSettings(**kwargs).image_input_enabled


def test_vision_configuration_is_independent_and_secret_is_masked():
    config = ImageInputSettings(
        _env_file=None,
        image_input_enabled=True,
        vision_base_url="https://vision.example/v1",
        vision_model="vision-test",
        vision_api_key="secret-test-key",
    )
    assert config.vision_model == "vision-test"
    assert "secret-test-key" not in repr(config)


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_image_validation_orients_and_removes_metadata(format, mime):
    result = validate_image(image_bytes(format, orientation=6), mime)
    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (8, 12)
        assert not image.getexif()
    assert result.mime_type == mime
    assert "data=" not in repr(result)


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"not an image", "image/png"),
        (b"", "image/png"),
        (image_bytes("PNG"), "image/jpeg"),
        (image_bytes("GIF"), "image/gif"),
        (b"x" * (MAX_IMAGE_BYTES + 1), "image/png"),
    ],
)
def test_invalid_images_are_rejected(data, mime):
    with pytest.raises(ImageInputError, match="image_invalid"):
        validate_image(data, mime)


def test_decompression_bomb_is_rejected():
    with patch("PIL.Image.MAX_IMAGE_PIXELS", 60):
        with pytest.raises(ImageInputError, match="image_invalid"):
            validate_image(image_bytes(), "image/png")


def test_decoded_pixel_limit_is_enforced():
    with patch("app.utils.image_utils.MAX_IMAGE_PIXELS", 60):
        with pytest.raises(ImageInputError, match="image_invalid"):
            validate_image(image_bytes(), "image/png")


def test_animated_png_is_rejected():
    data = BytesIO()
    Image.new("RGB", (12, 8), "white").save(
        data,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (12, 8), "black")],
    )
    with pytest.raises(ImageInputError, match="image_invalid"):
        validate_image(data.getvalue(), "image/png")


@pytest.fixture
async def whatsapp_client():
    client = WhatsAppClient()
    await client.client.aclose()
    yield client
    await client.client.aclose()


def attach_transport(client, handler):
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_download_uses_two_authenticated_requests(whatsapp_client, caplog):
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
    assert len(requests) == 2
    assert all(r.headers["authorization"].startswith("Bearer ") for r in requests)
    assert requests[0].url.path.endswith("/12345")
    assert "SECRET" not in caplog.text
    assert "lookaside.fbsbx" not in caplog.text


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


@pytest.mark.parametrize(
    "status,expected_calls", [(401, 1), (404, 1), (429, 2), (500, 2)]
)
async def test_download_retries_only_transient_errors(
    whatsapp_client, status, expected_calls
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status)

    attach_transport(whatsapp_client, respond)
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        pytest.raises(ImageInputError),
    ):
        await whatsapp_client.download_image("12345")
    assert len(requests) == expected_calls


async def test_download_rejects_redirect_without_following(whatsapp_client):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example"})

    attach_transport(whatsapp_client, respond)
    with (
        patch("app.clients.whatsapp_client.settings.mock_whatsapp", False),
        pytest.raises(ImageInputError),
    ):
        await whatsapp_client.download_image("12345")
    assert len(requests) == 1


class OversizedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.reads = 0

    async def __aiter__(self):
        for _ in range(1000):
            self.reads += 1
            yield b"x" * (64 * 1024)


async def test_download_stops_stream_without_trusting_content_length(whatsapp_client):
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
    assert stream.reads == MAX_IMAGE_BYTES // (64 * 1024) + 1


@pytest.fixture
def vision_config():
    config = ImageInputSettings(
        _env_file=None,
        image_input_enabled=True,
        vision_base_url="https://vision.example/v1",
        vision_model="vision-test",
        vision_api_key="secret-test-key",
    )
    with patch("app.clients.image_interpreter.image_input_settings", config):
        yield config


def completion_response(content=None, finish_reason="stop"):
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
                    "finish_reason": finish_reason,
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
def vision_transport():
    """Exercise the actual SDK serialization against a controlled HTTP boundary."""
    clients = []

    def install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return patch(
            "app.clients.image_interpreter.httpx",
            SimpleNamespace(AsyncClient=MagicMock(return_value=client)),
        )

    yield install
    assert all(client.is_closed for client in clients)


async def test_interpreter_uses_explicit_config_without_langchain_callbacks(
    vision_config, vision_transport, caplog, monkeypatch
):
    import base64
    import json

    from langchain_core.tracers.context import tracing_v2_callback_var
    from langsmith import get_tracing_context

    captured = []

    def respond(request):
        assert get_tracing_context()["enabled"] is False
        assert request.url == "https://vision.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-test-key"
        captured.append(json.loads(request.content))
        return completion_response()

    # A parent LangChain tracer must not receive this direct SDK request.
    tracer = MagicMock()
    token = tracing_v2_callback_var.set(tracer)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    try:
        with vision_transport(respond), caplog.at_level(logging.DEBUG):
            result = await ImageInterpreter().interpret(
                DownloadedImage(b"private-image-payload", "image/png"), "Solve both"
            )
    finally:
        tracing_v2_callback_var.reset(token)
    assert result == interpretation()
    assert "2. Solve" in result.to_request_text("Solve both")
    assert len(captured) == 1
    payload = captured[0]
    assert payload["model"] == vision_config.vision_model
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 8192
    encoded = base64.b64encode(b"private-image-payload").decode("ascii")
    assert (
        payload["messages"][1]["content"][1]["image_url"]["url"]
        == "data:image/png;base64," + encoded
    )
    assert encoded not in caplog.text
    assert "secret-test-key" not in caplog.text
    assert "Solve both" not in caplog.text
    assert not tracer.mock_calls


@pytest.mark.parametrize("bad_response", ["not json", '{"readability":"clear"}'])
async def test_interpreter_retries_bad_json_once(
    vision_config, vision_transport, bad_response
):
    requests = []

    def respond(request):
        requests.append(request)
        return completion_response(bad_response if len(requests) == 1 else None)

    with vision_transport(respond):
        assert (
            await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
            == interpretation()
        )
    assert len(requests) == 2


async def test_interpreter_stops_after_two_failures(
    vision_config, vision_transport, caplog
):
    requests = []

    def respond(request):
        requests.append(request)
        return completion_response("SECRET-invalid-json")

    with vision_transport(respond), pytest.raises(ImageInputError):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == 2
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "status,expected_calls", [(400, 1), (401, 1), (429, 2), (500, 2)]
)
async def test_vision_http_retry_budget(
    vision_config, vision_transport, status, expected_calls
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, json={"error": {"message": "PRIVATE-PROVIDER-ERROR"}}
        )

    with vision_transport(respond), pytest.raises(ImageInputError):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == expected_calls


async def test_vision_network_retry_budget(vision_config, vision_transport):
    requests = []

    def respond(request):
        requests.append(request)
        raise httpx.ConnectError("PRIVATE-ERROR", request=request)

    with vision_transport(respond), pytest.raises(ImageInputError):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == 2


async def test_vision_total_attempt_timeout(vision_config, vision_transport):
    import asyncio

    vision_config.vision_timeout_seconds = 0.01
    requests = []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(1)
        return completion_response()

    with vision_transport(respond), pytest.raises(ImageInputError):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == 2


async def test_truncated_extraction_requests_smaller_crop(
    vision_config, vision_transport
):
    requests = []

    def respond(request):
        requests.append(request)
        return completion_response("{}", finish_reason="length")

    with (
        vision_transport(respond),
        pytest.raises(ImageInputError, match="image_too_complex"),
    ):
        await ImageInterpreter().interpret(DownloadedImage(b"x", "image/png"), "")
    assert len(requests) == 1


def test_readability_schema_rejects_empty_or_invented_confidence():
    with pytest.raises(ValidationError):
        interpretation(transcription="", visual_details="")
    with pytest.raises(ValidationError):
        interpretation(readability=0.97)
    with pytest.raises(ValidationError):
        interpretation(readability="partial")


def test_response_logger_does_not_log_secrets_or_body(caplog):
    with caplog.at_level(logging.DEBUG):
        log_httpx_response(
            httpx.Response(
                400,
                request=httpx.Request("GET", "https://example.com?token=SECRET"),
                text="BASE64-PRIVATE",
            )
        )
    assert "status=400" in caplog.text
    assert "SECRET" not in caplog.text
    assert "BASE64-PRIVATE" not in caplog.text


def test_private_sdk_logging_restores_normal_logging(caplog):
    sdk_logger = logging.getLogger("openai._base_client")
    with caplog.at_level(logging.DEBUG):
        with private_media_logging():
            sdk_logger.debug("BASE64-PRIVATE")
            logging.getLogger("openai.lazily_created_child").debug("LATE-PRIVATE")
            logging.getLogger("app.clients.image_interpreter").info("safe stage log")
        sdk_logger.debug("normal diagnostics")
    assert "BASE64-PRIVATE" not in caplog.text
    assert "normal diagnostics" in caplog.text
    assert "LATE-PRIVATE" not in caplog.text
    assert "safe stage log" in caplog.text
