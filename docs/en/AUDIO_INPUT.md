# Audio input

Twiga accepts WhatsApp voice notes, converts them to text with a configured
speech-to-text provider, and processes the transcript through the same message
flow used for typed text.

## How it works

```text
WhatsApp or Mock WhatsApp
          |
          v
   Twiga webhook
          |
          +-- check blocked and rate-limited users
          |
          +-- load audio from Meta, or decode mock audio
          |
          v
 ElevenLabs or Groq
          |
          v
      transcript
          |
          v
 commands, onboarding, or normal chat flow
```

For real WhatsApp messages, Twiga resolves the media ID through Meta's Graph
API and downloads the audio from Meta's temporary media URL. Mock WhatsApp
sends the recording as base64 in the webhook payload. Both paths use the same
transcription service after the audio reaches Twiga.

Audio is limited to 16 MB. The mock interface limits a recording to two
minutes. If downloading or transcribing fails, Twiga asks the user in Swahili
to retry or send a text message.

## Configure a provider

Provider and model selection belongs to the Twiga backend environment. A
client cannot select or override them per message.

Use ElevenLabs for the simplest setup and for the strongest Swahili and mixed
Swahili-English results in our current tests. Use Groq to compare a hosted
Whisper model without downloading model files or running inference yourself.

### ElevenLabs

```env
AUDIO_TRANSCRIPTION_PROVIDER=elevenlabs
AUDIO_TRANSCRIPTION_MODEL=scribe_v2
ELEVENLABS_API_KEY=your-key
```

### Groq-hosted Whisper

```env
AUDIO_TRANSCRIPTION_PROVIDER=groq
AUDIO_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
GROQ_API_KEY=your-key
```

Restart Twiga after changing the environment. The provider key is read only
when an audio message is transcribed; typed messages do not require it.

The supported combinations are intentionally validated in
`app/config.py`. Adding another provider or model requires updating that
validation and `app/services/audio_transcription_service.py`.

## Try Whisper locally

Twiga does not yet support a custom transcription URL. You can still run and
evaluate Whisper as a separate service before adding that integration.

[Speaches](https://github.com/speaches-ai/speaches) provides an
OpenAI-compatible API backed by faster-whisper. Its CPU Docker image supports
ARM64 and AMD64, so the same setup works with Docker Desktop on macOS and
Windows and with Docker Engine on Linux.

Start the server:

```bash
docker run --rm --detach \
  --name twiga-local-whisper \
  --publish 8001:8000 \
  --volume twiga-whisper-models:/home/ubuntu/.cache/huggingface/hub \
  ghcr.io/speaches-ai/speaches:latest-cpu
```

Windows PowerShell users can run the same command on one line. The named
Docker volume keeps downloaded models when the container stops.

Download the multilingual `small` model:

```bash
curl --request POST \
  "http://localhost:8001/v1/models/Systran%2Ffaster-whisper-small"
```

PowerShell users can use `curl.exe` for the same request.

Transcribe an audio file:

```bash
curl http://localhost:8001/v1/audio/transcriptions \
  -F "file=@sample.m4a" \
  -F "model=Systran/faster-whisper-small" \
  -F "language=sw"
```

The language hint helps with short recordings. Use `en` for English and `sw`
for Swahili. Omit it when testing mixed-language speech, then inspect the
result because automatic language detection can fail on short clips.

The CPU image is about 1.6 GB before model downloads. In our Apple Silicon CPU
test, the `small` model used about 460 MB and the `medium` model increased the
combined model cache to about 1.9 GB. Download size and first-run latency vary
by model and platform.

The `small` and `medium` models did not match ElevenLabs on our Swahili sample.
Treat local Whisper as a development and evaluation option until your own
Swahili and mixed-language recordings meet the required accuracy. Larger
models need more disk, memory, and processing time.

Stop the server when you finish:

```bash
docker stop twiga-local-whisper
```

Remove the downloaded models if you need the disk space:

```bash
docker volume rm twiga-whisper-models
```

## Test with Mock WhatsApp

Follow [Quick Start with Mock WhatsApp](./MOCK_WHATSAPP_GETTING_STARTED.md),
then select the microphone in the message composer and allow browser microphone
access. Send a recording as you would send a WhatsApp voice note.

The sent message shows temporary audio playback and its transcript. In local
development, the mock also shows the provider and model returned by Twiga and
can export locally collected comparison results. The audio playback URL lasts
only for the current browser session.

For a useful provider comparison, record the same material for every backend
configuration:

1. Clear Swahili.
2. Clear English.
3. Mixed Swahili and English.
4. Speech with background noise.
5. Fast, quiet, or accent-varied speech.
6. Tanzanian names and education-specific terminology.

Change only `AUDIO_TRANSCRIPTION_PROVIDER` and
`AUDIO_TRANSCRIPTION_MODEL` between runs so the recordings remain comparable.

## Data handling

Twiga currently keeps the audio in memory only while downloading and
transcribing it. It does not save the audio to the database or object storage.
When the normal chat flow persists a user message, it stores the transcript
rather than the audio under the existing message-retention behavior.

The configured transcription provider receives the audio. Review that
provider's current privacy and retention terms before using voice input with
production or sensitive data. Provider retention is outside Twiga's control.

## Implementation map

- `app/clients/whatsapp_client.py` downloads Meta-hosted media.
- `app/services/request_service.py` validates, routes, and handles failures.
- `app/services/audio_transcription_service.py` calls the selected provider.
- `app/config.py` defines provider settings and supported models.
- `.env.template` lists the available environment variables.

The webhook response includes provider, model, and transcription latency in
the `X-Audio-Transcription-Provider`, `X-Audio-Transcription-Model`, and
`X-Audio-Transcription-Latency-Ms` headers. Mock WhatsApp uses these headers to
show which backend configuration produced a transcript.
