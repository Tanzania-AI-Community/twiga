# Migrations

You might run into some database troubles that require you to do database migrations. In the folder `migrations/versions/` you find the list of past database migrations. We're using [Alembic](https://alembic.sqlalchemy.org/en/latest/). They're docs aren't great so here's a beginner [article](https://medium.com/@kasperjuunge/how-to-get-started-with-alembic-and-sqlmodel-288700002543) on it.

By default, our Docker images use the alembic versioning system to initialize the database. If you want to rebuild the database to your needs, you can run new migrations and rebuild the Docker containers.

## Running migrations in Docker (preferred)

All commands run inside the `app` container so they use the container’s Python environment and see the `db` host on the Docker network.

- Start services (if not already): `make run`
- Generate a migration: `make generate-migration message="your message"`
- Apply latest migration: `make migrate-up`
- Downgrade to a revision: `make migrate-down version=<revision_id>`

Notes:
- The Makefile already injects `PYTHONPATH=/app` and `DATABASE_URL` from `.env`, so you don’t need to export them manually.
- Alembic auto-generation won’t detect new enum *values* for existing columns; add `ALTER TYPE ... ADD VALUE` statements to the generated revision when you change enum literals.

If you're not using Docker to run Twiga, then you can initialize the database and inject seed data with the command:

```
uv run python -m scripts.database.seed --create --sample-data --vector-data chunks_gemini.json
```

This will remove all tables in the database if they exist, create new ones, install pgvector and inject sample data and vector data so that the database is ready to accept new users.

## Conversation summary schema (Issue #92)

Migration `b7e2c9a4f610` follows `a1f4c7e2d3b9` and adds
`conversation_summary_state` and `conversation_summary_batches`. It performs no
backfill and retains the original `messages` rows. Batch coverage is an exact
list of source message IDs, including after a batch is archived by compaction.
Downgrading this migration removes summary state and batches while retaining
users and original messages. Apply it before using the summary persistence API
in `app/database/db.py`; the schema migration alone does not enable summarization.

Upgrade through the parent revision first. A fresh database must also satisfy the
prerequisites of the earlier migration chain, including pgvector. The downgrade
discards all stored summaries and coverage; restoring those requires a backup or
rebuilding them from retained messages. See the [persistence guide](CONVERSATION_SUMMARY_PERSISTENCE.md)
and [isolated test instructions](CONTRIBUTING.md#conversation-summary-persistence-checks).
