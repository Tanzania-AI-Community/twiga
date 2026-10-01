# Teacher image input (PoC)

Teachers can send a WhatsApp photo, optionally with a caption. Twiga downloads it
into memory, extracts text and relevant visual details with a vision model, and
passes that text to the existing agent. The agent retains its search-first policy,
textbook citations, equation solver and LaTeX image output. Multiple questions in
one readable image are supported; there is no fixed question-count limit.

## Configuration

The feature is **disabled by default**. Set these in the nonproduction environment:

```dotenv
IMAGE_INPUT_ENABLED=True
VISION_BASE_URL=https://api.together.ai/v1
VISION_MODEL=<vision-capable model available to your account>
VISION_API_KEY=<provider key>
VISION_TIMEOUT_SECONDS=30
```

The URL follows [Together's compatibility documentation](https://docs.together.ai/docs/inference/openai-compatibility),
not an enforced provider. Use the current endpoint supplied by your provider.
The model must accept base64 JPEG/PNG images through an
OpenAI-compatible Chat Completions API and support JSON-object response mode.
Confirm the chosen model's support with a real test before enabling the feature.
To switch to Nebius later, change the endpoint, model and key, then restart Twiga;
no chat-model settings or provider-specific code changes should be needed if those
API capabilities match. The main chat and tool models keep their existing settings.

Missing vision settings fail startup only when image input is enabled. Turning the
flag off stops new downloads/vision calls and sends a text-only fallback to teachers.

## Processing and storage

- Existing registration, user-state checks and configured rate limits run before
  downloading or invoking vision. This feature does not introduce new rate limits.
- Resolve Meta's media ID, then download its temporary URL with authentication.
  Only HTTPS Meta media hosts are accepted, with redirects disabled.
- Accept JPEG/PNG only, at most 5 MiB and 20 megapixels (to bound decoded memory).
  Validate the decoded image, reject corrupt,
  animated and decompression-bomb images, orient it from EXIF and remove metadata.
  The normalized image must also fit the size limit.
- The image bytes exist only in process memory. No bucket, disk copy, attachment
  table or migration is introduced. Restarting loses any in-flight image work.
- Initially store a photo marker and caption in the existing `Message.content`.
  On successful extraction, replace that same row with:

  ```text
  Source: teacher image
  Teacher instruction: <caption, or none>
  Transcription: <faithful text/math>
  Relevant visual details: <diagram/table description, or none>
  ```

- Partial/unreadable extractions ask for a clearer photo or the full typed question;
  they do not invoke the agent or save an unreliable transcription as usable content.
  Download/provider failures send a retry message. These replies use existing
  assistant-message persistence.
- Images always use the existing agent, even if text chat is configured for the
  basic client. Subsequent text messages retain normal text routing and can use the
  saved extraction through existing conversation history. They do not redownload it.
- Each image is independent. There is no photo grouping, attachment reference
  resolver, 24-hour pending context, or inference about page ordering.
- Download attempts have a 30-second deadline; vision attempts use the configured
  deadline. Each stage retries at most once for transient errors; vision also retries
  malformed JSON once. Authentication/invalid-image errors are not retried. Vision
  uses an 8,192-token extraction budget; detected truncation requests a smaller crop.
- Do not silently discard questions: overlong extraction requests a smaller crop;
  the agent is instructed to explain when normal tool/context limits prevent completion.

## Privacy and diagnostics

Vision uses the existing OpenAI-compatible SDK directly, without LangChain callbacks
or caching, inside a disabled tracing context. SDK logs are suppressed within image
processing. Application logs record stage, result, elapsed time and model, not
base64, temporary URLs, API keys or image bytes. The WhatsApp response logger no
longer logs secrets or response bodies. Vision calls are recorded in existing LLM
metrics with provider label `vision` (duration includes the single retry, if any).

Extracted text **is** saved to the normal conversation database and can appear in
normal downstream chat/tool traces. The configured vision provider receives image
content; its retention policies still apply. Use non-sensitive sample photos in
testing, not identifiable student work. Debugging original images requires the
tester to keep their own consented fixture; Twiga does not retain them.

## Verification without production WhatsApp

Unit tests exercise deterministic failures and the HTTP/vision boundaries locally:

```sh
uv run pytest -q
```

These tests do **not** establish photo-reading accuracy or real Meta compatibility.
Live acceptance is pending a test environment and a selected accessible vision model.

Coordinate the following with the tech lead:

1. Use a dedicated nonproduction Meta app/test sender and tester accounts. Keep its
   webhook and credentials separate from the production app/number.
2. Point it at a publicly reachable HTTPS Twiga test instance (or an approved local
   tunnel). Configure the normal `/webhooks` verification and message subscription.
   Keep webhook signature verification enabled.
3. Use a separate test database with textbook content and an active tester user
   whose subject/class is configured. This isolates image acceptance from onboarding.
4. Set `MOCK_WHATSAPP=False` for this test instance, supply the test sender's Meta
   settings, and enable/configure vision as above. Do not change production `.env`.
5. Send actual photos from an authorized tester's WhatsApp account to the test sender.
   Verify the real webhook, media resolution/download, extraction, tool use and reply.

Record selected model/version, case, expected transcription, observed answer,
latency, provider usage/cost and pass/fail for a small consented sample set:

| Case | Expected result |
| --- | --- |
| Printed exercise, no caption | Understand existing exercise; search relevant topic, then solve |
| Photo with “explain this concept” caption | Textbook lookup and cited explanation |
| Handwritten equations | Correct signs, fractions and exponents; rendered maths answer |
| Two or more questions; “solve all” | Preserve numbering and address each, or explicitly explain a limit |
| “Only question 2” caption | Focus on question 2 and needed context |
| Labelled diagram/table | Preserve relevant labels/relationships/values |
| Rotated photo | Correct orientation and extraction |
| Blurry, cropped or unreadable symbols | Ask for a clearer crop; do not guess |
| Several photos sent together | Handle each; no assumed shared order or combined request |
| Text follow-up about extracted content | Use history without a second download/vision call |
| Feature disabled | Text-only fallback; no vision usage |
| Unavailable vision provider | Safe retry message; no raw error payload in logs |

Check the database contains one user row per image, updated with extracted text on
success, plus normal assistant/tool records. Check logs/tracing contain no image
bytes, signed media URLs or credentials.

### Existing limitations to observe during acceptance

The existing webhook waits for processing before acknowledging Meta and ignores
messages at least 10 seconds old when mock mode is off. Images add latency; measure
timeouts/redeliveries carefully before wider rollout. Batched messages are classified
on arrival so the first photo's processing time does not age out later photos.
This PoC does not add a durable queue or webhook idempotency. Existing per-client
message buffering and history limits also remain unchanged; concurrent photo/text
requests and large photo bursts need explicit testing. Fix observed delivery issues
before production rollout, rather than treating unit tests as sufficient acceptance.
