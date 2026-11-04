# Transfer existing Google embeddings between Neon branches

`scripts/database/transfer_reembedded_chunks.py` copies an already re-embedded
snapshot into a **new destination staging table**. It does not call Google, update
live chunks, create an old-vector backup, or promote vectors. Promotion remains a
separate operation in `promote_reembedded_chunks.py`.

## Connections and invocation

Run from the Twiga repository with the locked dependencies installed. Put the two
connections in a private file outside the repository, for example
`/tmp/twiga-transfer.env`, with permissions `0600`:

```dotenv
SOURCE_DATABASE_URL=<confirmed dev/adria connection>
DESTINATION_DATABASE_URL=<confirmed production connection used by Render>
```

The source value is the development connection currently stored in
`EVAL_DATABASE_URL`; verify the destination endpoint against Render's production
`DATABASE_URL`. Never paste credentials into chat or commit this file. The script
deliberately does not fall back to `DATABASE_URL` or `EVAL_DATABASE_URL`.

```sh
env -u SOURCE_DATABASE_URL -u DESTINATION_DATABASE_URL \
  uv run python -m scripts.database.transfer_reembedded_chunks \
  --env-file /tmp/twiga-transfer.env \
  --source-table-name chunks_gemini_001_dev_20260918 \
  --target-table-name chunks_gemini_001_prod_20260919 \
  --batch-size 128
```

The `env -u` options ensure exported shell values cannot override the selected
file. Neon pooled URLs are resolved to their corresponding direct endpoint by
the existing migration utility. Neither the app's `.env` nor Render's connection
configuration is changed.

## Guarantees and failure handling

- Reads the source in a repeatable-read, read-only transaction, requiring the
  existing Google migration manifest and complete nonzero 1024-dimensional vectors.
- Creates staging with the live destination table's columns and an ID primary
  key. Does not copy its vector index, sequence defaults or foreign keys.
- Streams all fields in bounded batches using PostgreSQL JSON serialization,
  avoiding client-side rounding or type conversion of vectors and metadata.
- Verifies row counts and a SHA-256 digest of every ordered record by reading
  destination staging back from PostgreSQL. This includes vectors and all metadata.
- Compares staging IDs and all non-embedding fields against the destination's
  current live corpus. Missing, extra or changed chunks abort the transfer.
- Publishes the source manifest and commits staging only after every check passes.
- Uses the same advisory-lock key as the migration/promotion scripts. Refuses an
  existing target and refuses live/source table names as the destination target.

Progress messages describe uncommitted rows. Unlike the API re-embedding runner,
this transfer uses **one atomic destination transaction**, not resumable batch
commits. Failure before commit removes the entire new table; fix the cause and
rerun. If a connection is lost during commit, inspect whether staging exists before
retrying; an existing table is always protected from overwrite.

The source snapshot and live destination data must correspond. This tool stops
on drift; it does not silently skip or re-embed changed records. Freeze textbook
ingestion during the migration window. Other production tables are untouched.

## After the copy

Successful output is `Copied and verified N chunks. Live embeddings were not
changed.` For the unchanged audited corpus, N should be 72,807.

Use a separate private production migration file containing `DATABASE_URL` and
the existing promotion script to validate the staging table again:

```sh
env -u DATABASE_URL uv run python \
  -m scripts.database.promote_reembedded_chunks \
  --env-file /tmp/twiga-production-migration.env \
  --target-table-name chunks_gemini_001_prod_20260919 \
  --backup-table-name chunks_e5_backup_prod_20260919
```

This command is read-only. Only a separately coordinated invocation with
`--apply` backs up old vectors and replaces live embeddings. Do not assume the
successful transfer has fixed production retrieval: it still reads `chunks`.

## Tests

```sh
TWIGA_MIGRATION_TEST_URL=postgresql://user@localhost:55432/postgres \
  uv run pytest tests/test_reembedding_database.py -q
```

Use an isolated local test cluster with pgvector available and permission to
create databases. Transfer tests create and remove uniquely named disposable
databases. Coverage includes real cross-database copying, float32/Unicode/JSON/NULL
preservation, compatibility with promotion and backup, drift, incomplete vectors,
invalid manifests, existing targets, schema coercion and interruption/retry.
