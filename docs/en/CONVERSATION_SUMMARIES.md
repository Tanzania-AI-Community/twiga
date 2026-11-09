# Conversation summaries

Twiga stores summarized history separately from original messages. See the
[persistence guide](CONVERSATION_SUMMARY_PERSISTENCE.md) for the database contract
and [mock WhatsApp setup](MOCK_WHATSAPP_GETTING_STARTED.md) for local interaction.

## Runtime

Conversation summaries require the locked `tokenizers` dependency and both pinned
artifacts in `app/assets/tokenizers/`; see their [sources and licenses](../../app/assets/tokenizers/README.md).
The supported provider is Together, with `zai-org/GLM-5.3-Flash` and
`deepseek-ai/DeepSeek-V4.1-Flash` as supported primary/fallback models. Other
provider/model mappings fail explicitly. The runtime counts every complete stored
summary, including its wrapper and provenance, with both tokenizers and stores the
larger count regardless of which model answers. The artifacts are loaded locally;
no tokenizer files or model weights are downloaded during chat requests.

The existing policy uses 1,500-character chunks, soft summarization above 25
pending chunks and hard preparation above 30. These are chunk counts, not message
row limits. Stored active batch summaries have a combined 75,000-token budget;
the older-history rollup has a 25,000-token budget. Compaction preserves the latest
five batches and retains original messages and archived exact coverage records.

## Model context windows

Together's [serverless model catalog](https://docs.together.ai/docs/serverless/models),
checked on 2026-11-09, lists these exact context lengths for the configured IDs:

| Model ID | Published context length (tokens) |
| --- | ---: |
| `zai-org/GLM-5.3-Flash` | 1,048,575 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | 1,000,000 |

These are model context windows, not a guaranteed allowance for user-message text
alone. Input includes system instructions, history, tool definitions and tool
results, and the request must leave room for generated output. The smaller
DeepSeek window governs requests intended to work with either model. The stored
summary budgets do not bound the full request, and the runtime does not implement
a complete request-token budgeting system.

## Existing stored summaries

Before enabling this runtime with existing summaries, stop summary writers and
review/recount every active batch and rollup using the new count basis. Preserve
summary text, source messages and exact coverage. Loaded snapshots with mismatched
counts are rejected; if recounting exceeds either budget, resolve that state
before enabling the runtime rather than changing the budgets. No automatic count
migration is provided. A fresh database without existing summaries has no legacy
summary counts to transition.

## Summary deadlines

The summary operation retains its 60-second total deadline. Together attempts
are capped at 20 seconds and each router call at 50 seconds, also respecting
lower configured limits. Earlier database/model work reduces the time left for
later rollup or shortening calls. These summary-specific caps preserve the shared
router's default behavior for other callers.

## Tests

Set `ISSUE92_TEST_DATABASE_URL` explicitly to a disposable PostgreSQL database
whose name begins with `issue92_test`, with pgvector installed. The fixtures
create and remove per-test schemas and never fall back to the application URL.

Generic service tests inject counters and mock model calls; runtime tests use both
included real tokenizers. Run these and the client, delivery and router checks with:

```sh
.venv/bin/python -m pytest tests/services/test_conversation_summary_service.py tests/services/test_conversation_summary_runtime.py tests/clients/test_client_base.py tests/clients/test_agent_client.py tests/services/test_messaging_service.py tests/utils/test_llm_failover.py -q -m 'not integration'
```

For the real database, migration and persisted lifecycle checks, set the explicit
URL above and run:

```sh
.venv/bin/python -m pytest tests/database/test_conversation_summary_db.py tests/database/test_conversation_summary_migrations.py tests/services/test_conversation_summary_service.py tests/services/test_conversation_summary_lifecycle.py -q
```

Without the explicit URL, PostgreSQL cases skip; the migration round trip also
skips without pgvector. Skips leave required PostgreSQL validation outstanding.
