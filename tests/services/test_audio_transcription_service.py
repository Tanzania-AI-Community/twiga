from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.config import AudioTranscriptionProvider
from app.services.audio_transcription_service import AudioTranscriptionService


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://example.test/transcribe"),
    )


@pytest.mark.asyncio
async def test_transcribe_with_elevenlabs() -> None:
    service = AudioTranscriptionService()

    with (
        patch.object(
            service.settings,
            "audio_transcription_provider",
            AudioTranscriptionProvider.ELEVENLABS,
        ),
        patch.object(service.settings, "audio_transcription_model", "scribe_v2"),
        patch(
            "app.services.audio_transcription_service.time.perf_counter",
            side_effect=[1.0, 1.125],
        ),
        patch.object(
            service.settings, "elevenlabs_api_key", SecretStr("elevenlabs-key")
        ),
        patch.object(
            service.client,
            "post",
            AsyncMock(return_value=_response({"text": "Habari mwalimu"})),
        ) as mock_post,
    ):
        result = await service.transcribe(b"audio", "audio/ogg")

    assert result.text == "Habari mwalimu"
    assert result.provider == AudioTranscriptionProvider.ELEVENLABS
    assert result.model == "scribe_v2"
    assert result.latency_ms == 125
    assert mock_post.await_args.args[0].endswith("/v1/speech-to-text")
    assert mock_post.await_args.kwargs["headers"] == {"xi-api-key": "elevenlabs-key"}
    assert mock_post.await_args.kwargs["data"] == {"model_id": "scribe_v2"}


@pytest.mark.asyncio
async def test_transcribe_with_groq_whisper() -> None:
    service = AudioTranscriptionService()

    with (
        patch.object(
            service.settings,
            "audio_transcription_provider",
            AudioTranscriptionProvider.GROQ,
        ),
        patch.object(
            service.settings, "audio_transcription_model", "whisper-large-v3-turbo"
        ),
        patch.object(service.settings, "groq_api_key", SecretStr("groq-key")),
        patch.object(
            service.client,
            "post",
            AsyncMock(return_value=_response({"text": "Hello teacher"})),
        ) as mock_post,
    ):
        result = await service.transcribe(b"audio", "audio/mp4")

    assert result.text == "Hello teacher"
    assert result.provider == AudioTranscriptionProvider.GROQ
    assert result.model == "whisper-large-v3-turbo"
    assert mock_post.await_args.args[0].endswith("/audio/transcriptions")
    assert mock_post.await_args.kwargs["headers"] == {
        "Authorization": "Bearer groq-key"
    }
    assert mock_post.await_args.kwargs["data"] == {"model": "whisper-large-v3-turbo"}


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_provider_response() -> None:
    service = AudioTranscriptionService()

    with (
        patch.object(
            service.settings,
            "audio_transcription_provider",
            AudioTranscriptionProvider.ELEVENLABS,
        ),
        patch.object(
            service.settings, "elevenlabs_api_key", SecretStr("elevenlabs-key")
        ),
        patch.object(
            service.client,
            "post",
            AsyncMock(return_value=_response({"text": "  "})),
        ),
        pytest.raises(ValueError, match="empty transcript"),
    ):
        await service.transcribe(b"audio", "audio/ogg")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_transcribe_rejects_unsupported_provider_model_pair() -> None:
    service = AudioTranscriptionService()

    with (
        patch.object(
            service.settings,
            "audio_transcription_provider",
            AudioTranscriptionProvider.ELEVENLABS,
        ),
        patch.object(service.settings, "audio_transcription_model", "whisper-large-v3"),
        pytest.raises(ValueError, match="Unsupported audio transcription model"),
    ):
        await service.transcribe(b"audio", "audio/ogg")
