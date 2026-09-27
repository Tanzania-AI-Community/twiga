"""Opt-in PostgreSQL/pgvector tests; set TWIGA_MIGRATION_TEST_URL to a local test DB."""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.database.promote_reembedded_chunks import promote_embeddings
from scripts.database.reembed_chunks_in_db import (
    normalize_database_url,
    reembed_chunks_in_database,
)
from scripts.database.transfer_reembedded_chunks import transfer_embeddings


class FakeEmbedder:
    provider = "google"
    model = "gemini-embedding-001"
    dimensions = 1024
    document_max_bytes = 2048

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def embed_documents(self, texts):
        self.calls.extend(texts)
        if self.fail_on and self.fail_on in texts:
            raise RuntimeError("temporary provider failure")
        return [[float(len(t))] * 1024 for t in texts]


@pytest_asyncio.fixture
async def corpus():
    url = os.getenv("TWIGA_MIGRATION_TEST_URL")
    if not url:
        pytest.skip("Set TWIGA_MIGRATION_TEST_URL for local pgvector integration tests")
    engine = create_async_engine(normalize_database_url(url))
    prefix = "embedding_test_" + uuid4().hex[:10]
    source, target, backup = [
        prefix + suffix for suffix in ("_source", "_stage", "_backup")
    ]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE TABLE {source} (id integer PRIMARY KEY, resource_id integer, content text NOT NULL, page_number integer, embedding vector(1024))"
            )
        )
        for id_, content in [(2, "first"), (7, "second"), (40, "third")]:
            await conn.execute(
                text(
                    f"INSERT INTO {source} VALUES (:id, 1, :content, 3, CAST(:embedding AS vector))"
                ),
                {"id": id_, "content": content, "embedding": str([1.0] * 1024)},
            )
    yield url, engine, source, target, backup
    async with engine.begin() as conn:
        for name in (backup, target, source):
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    await engine.dispose()


async def scalar(engine, sql):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


async def run(corpus, client=None, **kwargs):
    url, _, source, target, _ = corpus
    return await reembed_chunks_in_database(
        url,
        client or FakeEmbedder(),
        source_table_name=source,
        target_table_name=target,
        **kwargs,
    )


async def promote(corpus, **kwargs):
    url, _, source, target, backup = corpus
    return await promote_embeddings(
        url, target, source_table=source, backup_table=backup, **kwargs
    )


async def test_dry_run_creates_no_tables_and_preserves_source(corpus):
    _, engine, source, target, _ = corpus
    stats = await run(corpus, dry_run=True, limit=2)
    assert stats.processed_chunks == 2
    assert await scalar(engine, f"SELECT to_regclass('{target}')") is None
    assert (
        await scalar(
            engine, f"SELECT count(*) FROM {source} WHERE embedding::text LIKE '[1,1,%'"
        )
        == 3
    )


async def test_partial_resume_validation_and_atomic_promotion(corpus):
    _, engine, source, target, backup = corpus
    await run(corpus, limit=1)
    assert (
        await scalar(engine, f"SELECT count(*) FROM {target} WHERE embedding IS NULL")
        == 2
    )
    with pytest.raises(ValueError, match="incomplete"):
        await promote(corpus, apply=True)
    assert await scalar(engine, f"SELECT to_regclass('{backup}')") is None
    client = FakeEmbedder()
    stats = await run(corpus, client)
    assert stats.processed_chunks == 2
    assert client.calls == ["second", "third"]
    assert await promote(corpus) == 3
    assert await scalar(engine, f"SELECT to_regclass('{backup}')") is None
    assert (
        await scalar(
            engine, f"SELECT count(*) FROM {source} WHERE embedding::text LIKE '[1,1,%'"
        )
        == 3
    )
    assert await promote(corpus, apply=True) == 3
    assert (
        await scalar(
            engine, f"SELECT count(*) FROM {backup} WHERE embedding::text LIKE '[1,1,%'"
        )
        == 3
    )
    assert (
        await scalar(
            engine,
            f"SELECT count(*) FROM {source} s JOIN {target} t USING (id) WHERE to_jsonb(s) = to_jsonb(t)",
        )
        == 3
    )
    # Running again makes no API calls and does not discard the completed vectors.
    client = FakeEmbedder()
    assert (await run(corpus, client)).processed_chunks == 0
    assert client.calls == []


async def test_interruption_resumes_after_committed_batches(corpus):
    _, engine, _, target, _ = corpus
    with pytest.raises(RuntimeError, match="temporary"):
        await run(corpus, FakeEmbedder(fail_on="second"), batch_size=1)
    assert (
        await scalar(
            engine, f"SELECT count(*) FROM {target} WHERE embedding IS NOT NULL"
        )
        == 1
    )
    assert (await run(corpus)).processed_chunks == 2
    assert await promote(corpus) == 3


async def test_model_mismatch_refuses_resume(corpus):
    await run(corpus, limit=1)
    client = FakeEmbedder()
    client.model = "different-model"
    with pytest.raises(ValueError, match="configuration differs"):
        await run(corpus, client)
    assert client.calls == []


@pytest.mark.parametrize("change", ["content = 'edited'", "page_number = 5"])
async def test_promotion_refuses_changed_source(corpus, change):
    _, engine, source, _, backup = corpus
    await run(corpus)
    async with engine.begin() as conn:
        await conn.execute(text(f"UPDATE {source} SET {change} WHERE id = 2"))
    with pytest.raises(ValueError, match="changed"):
        await promote(corpus, apply=True)
    assert await scalar(engine, f"SELECT to_regclass('{backup}')") is None


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM {source} WHERE id = 2",
        "INSERT INTO {source} SELECT 99, resource_id, content, page_number, embedding FROM {source} WHERE id = 2",
    ],
)
async def test_promotion_refuses_missing_or_added_rows(corpus, mutation):
    _, engine, source, _, _ = corpus
    await run(corpus)
    async with engine.begin() as conn:
        await conn.execute(text(mutation.format(source=source)))
    with pytest.raises(ValueError, match="missing"):
        await promote(corpus, apply=True)


async def test_refuses_unrecognized_existing_target_even_with_refresh(corpus):
    _, engine, _, target, _ = corpus
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {target} (valuable_data text)"))
    with pytest.raises(ValueError, match="not a recognized"):
        await run(corpus, refresh_target_table=True)
    assert (
        await scalar(
            engine,
            f"SELECT count(*) FROM information_schema.columns WHERE table_name = '{target}' AND column_name = 'valuable_data'",
        )
        == 1
    )


async def test_failure_does_not_commit_part_of_a_batch(corpus):
    _, engine, _, target, _ = corpus
    client = FakeEmbedder()
    client.embed_documents = lambda texts: [
        [2.0] * 1024,
        [float("nan")] * 1024,
        [3.0] * 1024,
    ]
    with pytest.raises(ValueError, match="finite"):
        await run(corpus, client)
    assert (
        await scalar(engine, f"SELECT count(*) FROM {target} WHERE embedding IS NULL")
        == 3
    )


async def test_existing_backup_prevents_overwrite(corpus):
    from sqlalchemy.exc import DBAPIError

    _, engine, _, _, backup = corpus
    await run(corpus)
    await promote(corpus, apply=True)
    with pytest.raises(DBAPIError):
        await promote(corpus, apply=True)
    assert (
        await scalar(
            engine, f"SELECT count(*) FROM {backup} WHERE embedding::text LIKE '[1,1,%'"
        )
        == 3
    )


async def test_concurrent_runner_is_rejected(corpus):
    _, engine, _, target, _ = corpus
    async with engine.connect() as conn:
        await conn.execute(
            text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": target}
        )
        try:
            with pytest.raises(ValueError, match="Another migration"):
                await run(corpus)
        finally:
            await conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": target}
            )


async def test_prefix_report_preserves_source_text(corpus):
    _, engine, source, _, _ = corpus
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE {source} SET content = :content WHERE id = 2"),
            {"content": "é" * 1200},
        )
    stats = await run(corpus)
    assert stats.truncated_chunk_ids == [2]
    assert (
        await scalar(engine, f"SELECT length(content) FROM {source} WHERE id = 2")
        == 1200
    )
    client = FakeEmbedder()
    client.document_max_bytes = 1024
    with pytest.raises(ValueError, match="configuration differs"):
        await run(corpus, client)


@pytest_asyncio.fixture
async def transfer_destination(corpus):
    """A separate disposable database exercises real cross-database serialization."""
    url, _, source, _, _ = corpus
    normalized = make_url(normalize_database_url(url))
    database = "transfer_test_" + uuid4().hex[:10]
    admin = create_async_engine(normalized, isolation_level="AUTOCOMMIT")
    destination_url = normalized.set(database=database).render_as_string(
        hide_password=False
    )
    destination = create_async_engine(destination_url)
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        async with destination.begin() as conn:
            await conn.execute(text("CREATE EXTENSION vector"))
            await conn.execute(
                text(
                    f"CREATE TABLE {source} (id integer PRIMARY KEY, resource_id integer, "
                    "content text NOT NULL, page_number integer, embedding vector(1024))"
                )
            )
            for id_, content in [(2, "first"), (7, "second"), (40, "third")]:
                await conn.execute(
                    text(
                        f"INSERT INTO {source} VALUES (:id, 1, :content, 3, CAST(:embedding AS vector))"
                    ),
                    {"id": id_, "content": content, "embedding": str([1.0] * 1024)},
                )
        yield destination_url, destination, "google_transfer_stage"
    finally:
        await destination.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await admin.dispose()


async def transfer(corpus, transfer_destination, **kwargs):
    url, _, live, snapshot, _ = corpus
    destination_url, _, target = transfer_destination
    return await transfer_embeddings(
        url,
        destination_url,
        source_table=snapshot,
        target_table=target,
        live_table=live,
        batch_size=1,
        **kwargs,
    )


async def test_transfer_between_databases_preserves_values_and_supports_promotion(
    corpus, transfer_destination
):
    _, source_engine, live, snapshot, _ = corpus
    destination_url, destination, target = transfer_destination
    content = "Mimea ya kijani 🌱 — farmer's text\n" + "é" * 4000
    for engine in (source_engine, destination):
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER TABLE {live} ADD COLUMN metadata jsonb"))
            await conn.execute(
                text(
                    f"UPDATE {live} SET content=:content, page_number=NULL, "
                    "metadata=CAST(:metadata AS jsonb) WHERE id=2"
                ),
                {
                    "content": content,
                    "metadata": '{"title":"mmea", "tags":[1,null,"🌱"]}',
                },
            )
    await run(corpus)
    async with source_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE {snapshot} SET embedding=CAST(:v AS vector) WHERE id=2"),
            {"v": str([0.123456789, -0.987654321] * 512)},
        )
    assert await transfer(corpus, transfer_destination) == 3
    assert (
        await scalar(
            destination,
            f"SELECT count(*) FROM {live} WHERE embedding::text LIKE '[1,1,%'",
        )
        == 3
    )
    assert await scalar(
        destination, f"SELECT to_jsonb(t)::text FROM {target} t WHERE id=2"
    ) == await scalar(
        source_engine, f"SELECT to_jsonb(t)::text FROM {snapshot} t WHERE id=2"
    )
    assert (
        await promote_embeddings(
            destination_url, target, source_table=live, backup_table="old_vectors"
        )
        == 3
    )
    assert (
        await promote_embeddings(
            destination_url,
            target,
            source_table=live,
            backup_table="old_vectors",
            apply=True,
        )
        == 3
    )
    assert (
        await scalar(
            destination,
            "SELECT count(*) FROM old_vectors WHERE embedding::text LIKE '[1,1,%'",
        )
        == 3
    )


@pytest.mark.parametrize("change", ["content", "missing", "extra"])
async def test_transfer_rolls_back_on_production_drift(
    corpus, transfer_destination, change
):
    _, _, live, _, _ = corpus
    _, destination, target = transfer_destination
    await run(corpus)
    async with destination.begin() as conn:
        if change == "content":
            await conn.execute(text(f"UPDATE {live} SET content='changed' WHERE id=7"))
        elif change == "missing":
            await conn.execute(text(f"DELETE FROM {live} WHERE id=7"))
        else:
            await conn.execute(
                text(
                    f"INSERT INTO {live} SELECT 99, resource_id, content, page_number, embedding FROM {live} WHERE id=7"
                )
            )
    with pytest.raises(ValueError, match="missing or changed"):
        await transfer(corpus, transfer_destination)
    assert await scalar(destination, f"SELECT to_regclass('{target}')") is None
    assert (
        await scalar(
            destination,
            f"SELECT count(*) FROM {live} WHERE embedding::text NOT LIKE '[1,1,%'",
        )
        == 0
    )


async def test_transfer_refuses_existing_target(corpus, transfer_destination):
    _, destination, target = transfer_destination
    await run(corpus)
    assert await transfer(corpus, transfer_destination) == 3
    with pytest.raises(ValueError, match="already exists"):
        await transfer(corpus, transfer_destination)
    assert await scalar(destination, f"SELECT count(*) FROM {target}") == 3


@pytest.mark.parametrize("invalid", ["manifest", "incomplete", "zero"])
async def test_transfer_rejects_unusable_source(corpus, transfer_destination, invalid):
    _, engine, _, snapshot, _ = corpus
    _, destination, target = transfer_destination
    await run(corpus)
    async with engine.begin() as conn:
        if invalid == "manifest":
            await conn.execute(text(f"COMMENT ON TABLE {snapshot} IS '{{}}'"))
        elif invalid == "incomplete":
            await conn.execute(text(f"UPDATE {snapshot} SET embedding=NULL WHERE id=7"))
        else:
            await conn.execute(
                text(f"UPDATE {snapshot} SET embedding=CAST(:v AS vector) WHERE id=7"),
                {"v": str([0.0] * 1024)},
            )
    with pytest.raises(ValueError, match="manifest|invalid/incomplete"):
        await transfer(corpus, transfer_destination)
    assert await scalar(destination, f"SELECT to_regclass('{target}')") is None


async def test_transfer_interruption_rolls_back_and_can_retry(
    corpus, transfer_destination, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncConnection

    _, destination, target = transfer_destination
    await run(corpus)
    original = AsyncConnection.execute
    inserted = 0

    async def interrupted(self, statement, *args, **kwargs):
        nonlocal inserted
        if str(statement).startswith(f'INSERT INTO "{target}"'):
            inserted += 1
            if inserted == 2:
                raise RuntimeError("simulated lost connection")
        return await original(self, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "execute", interrupted)
        with pytest.raises(RuntimeError, match="lost connection"):
            await transfer(corpus, transfer_destination)
    assert await scalar(destination, f"SELECT to_regclass('{target}')") is None
    assert await transfer(corpus, transfer_destination) == 3


async def test_transfer_detects_copy_coercion(corpus, transfer_destination):
    _, _, live, _, _ = corpus
    _, destination, target = transfer_destination
    await run(corpus)
    # A mismatched destination schema must not silently drop source fields.
    async with destination.begin() as conn:
        await conn.execute(text(f"ALTER TABLE {live} DROP COLUMN page_number"))
    with pytest.raises(ValueError, match="differs from the source"):
        await transfer(corpus, transfer_destination)
    assert await scalar(destination, f"SELECT to_regclass('{target}')") is None


async def test_transfer_rejects_live_target_before_connecting():
    with pytest.raises(ValueError, match="new staging"):
        await transfer_embeddings(
            "unused", "unused", source_table="snapshot", target_table="chunks"
        )
