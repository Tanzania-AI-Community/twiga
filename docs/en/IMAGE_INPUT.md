# Teacher image input (prototype)

Teachers can send a WhatsApp photo with an optional caption. A vision model reads
the text and relevant diagrams/tables. The existing agent then uses its normal
textbook search, equation solver, citations and LaTeX output.

## Setup

The feature is disabled by default. Complete the normal [WhatsApp setup](GETTING_STARTED.md)
with a nonproduction Meta sender, `MOCK_WHATSAPP=False`, and an active tester user
with subjects/classes configured. Textbook search also needs the usual textbook data.

Add these settings to the test environment, replace the placeholders, and restart Twiga:

```dotenv
IMAGE_INPUT_ENABLED=True
VISION_BASE_URL=https://<provider-host>/v1
VISION_MODEL=<vision-capable model>
VISION_API_KEY=<provider key>
VISION_TIMEOUT_SECONDS=30
```

The provider must support base64 JPEG/PNG input and JSON-object output through an
OpenAI-compatible Chat Completions API. Vision settings are separate from chat
settings. To change providers, update the URL, model and key, then restart.
Missing vision settings prevent startup only when image input is enabled.

## Behaviour and limits

- Accepts static JPEG/PNG images up to 5 MiB and 20 megapixels. Twiga corrects
  EXIF orientation and removes image metadata before sending the photo to vision.
- Photos remain in memory; Twiga does not save the original files. Extracted text,
  the caption and visual details replace the photo placeholder in the same
  `Message.content` row. Normal conversation history can reuse this text.
- Image requests always use the agent, even when text chat uses the basic client.
  Several questions in one photo are allowed, without a fixed question-count limit.
  Separate photos are processed independently, not combined into a shared request.
- Unreadable content prompts a request for a clearer photo. Processing failures
  prompt a retry; oversized requests prompt a smaller crop.
- Download attempts have a 30-second timeout; vision uses `VISION_TIMEOUT_SECONDS`.
  Each stage permits one retry for recoverable errors.
- Setting `IMAGE_INPUT_ENABLED=False` stops new image downloads and vision calls.
  Teachers receive a request to type their question instead.

The configured vision provider receives the photo. The vision call suppresses
LangSmith tracing and SDK request logs. Extracted text enters normal conversation
history and can appear in downstream traces. Use non-sensitive test photos.

## Test

Run the feature tests:

```sh
uv run pytest -q tests/test_image_input.py tests/services/test_image_input_flow.py
```

These tests do not measure transcription accuracy. Check real WhatsApp photos too:

- A printed exercise, with and without a caption: a relevant answer and readable maths.
- A multi-question photo: follow captions such as “solve all” or “only question 2”.
- A concept question: textbook search and a cited explanation.
- Handwriting or a labelled diagram: preserve important symbols, labels and values.
- A blurry or cropped question: ask for a clearer photo instead of guessing.

The existing webhook still waits for processing before responding and ignores
messages at least 10 seconds old when mock mode is off. Batch timestamps are checked
before processing. There is no durable queue or duplicate-message protection;
check slow responses and redeliveries before a wider rollout.
