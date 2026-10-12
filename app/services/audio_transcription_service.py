import httpx

from app.config import AudioTranscriptionProvider, Settings, settings


class AudioTranscriptionService:
    def __init__(self, service_settings: Settings = settings) -> None:
        self.settings = service_settings
        self.client = httpx.AsyncClient(
            timeout=service_settings.audio_transcription_timeout_seconds
        )

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        provider = self.settings.audio_transcription_provider

        if provider == AudioTranscriptionProvider.ELEVENLABS:
            response = await self._transcribe_with_elevenlabs(audio, mime_type)
        elif provider == AudioTranscriptionProvider.GROQ:
            response = await self._transcribe_with_groq(audio, mime_type)
        else:
            raise ValueError(f"Unsupported audio transcription provider: {provider}")

        transcript = response.get("text", "").strip()
        if not transcript:
            raise ValueError(
                "Audio transcription provider returned an empty transcript"
            )
        return transcript

    async def _transcribe_with_elevenlabs(self, audio: bytes, mime_type: str) -> dict:
        api_key = self._required_key("elevenlabs_api_key")
        response = await self.client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            data={"model_id": self.settings.audio_transcription_model},
            files={"file": (self._filename(mime_type), audio, mime_type)},
        )
        response.raise_for_status()
        return response.json()

    async def _transcribe_with_groq(self, audio: bytes, mime_type: str) -> dict:
        api_key = self._required_key("groq_api_key")
        response = await self.client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": self.settings.audio_transcription_model},
            files={"file": (self._filename(mime_type), audio, mime_type)},
        )
        response.raise_for_status()
        return response.json()

    def _required_key(self, field_name: str) -> str:
        secret = getattr(self.settings, field_name)
        if not secret or not secret.get_secret_value().strip():
            raise ValueError(f"{field_name.upper()} is required")
        return secret.get_secret_value()

    @staticmethod
    def _filename(mime_type: str) -> str:
        normalized = mime_type.split(";", 1)[0].strip().lower()
        extension = {
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/ogg": "ogg",
            "audio/wav": "wav",
            "audio/webm": "webm",
        }.get(normalized, "audio")
        return f"voice-note.{extension}"


audio_transcription_service = AudioTranscriptionService()
