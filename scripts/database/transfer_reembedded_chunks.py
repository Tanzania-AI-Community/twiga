"""Copy a verified Google snapshot between databases into a new staging table.

Never updates live chunks or calls an embedding API. The destination transaction
commits only after exact copy verification and comparison with its live corpus.
An interrupted/failed transfer rolls back the entire new table; rerun to retry.
"""

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.utils.google_embedder import DOCUMENT_MAX_BYTES
from scripts.database.reembed_chunks_in_db import (
    _quote_identifier,
    normalize_database_url,
    validate_table_name,
)
from scripts.database.reembedding_utils import read_env_value

logger = logging.getLogger(__name__)


def _table(name: str) -> str:
    if len(name.encode("utf-8")) > 63:
        raise ValueError("Table names must fit PostgreSQL's 63-byte identifier limit.")
    return _quote_identifier(validate_table_name(name))


async def transfer_embeddings(
    source_database_url: str,
    destination_database_url: str,
    *,
    source_table: str,
    target_table: str,
    live_table: str = "chunks",
    batch_size: int = 128,
    model: str = "gemini-embedding-001",
) -> int:
    """Return the verified row count; refuse existing or live-table targets."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    if target_table in {live_table, source_table, "chunks"}:
        raise ValueError(
            "Target must be a new staging table, separate from live/source tables."
        )
    source, target, live = map(_table, (source_table, target_table, live_table))
    source_engine = create_async_engine(
        normalize_database_url(source_database_url), hide_parameters=True
    )
    destination_engine = create_async_engine(
        normalize_database_url(destination_database_url), hide_parameters=True
    )
    try:
        async with source_engine.begin() as reader:
            await reader.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            comment = (
                await reader.execute(
                    text("SELECT obj_description(to_regclass(:name), 'pg_class')"),
                    {"name": source},
                )
            ).scalar_one()
            manifest = json.loads(comment or "null")
            expected = {
                "migration": "twiga-reembedding-v1",
                "source": live_table,
                "provider": "google",
                "model": model,
                "dimensions": 1024,
                "task_type": "RETRIEVAL_DOCUMENT",
                "document_max_bytes": DOCUMENT_MAX_BYTES,
                "max_token_estimate": None,
            }
            if not isinstance(manifest, dict) or any(
                manifest.get(key) != value for key, value in expected.items()
            ):
                raise ValueError(
                    "Source manifest does not match the Google configuration."
                )
            count, invalid = (
                await reader.execute(
                    text(
                        f"""SELECT count(*), count(*) FILTER (
                        WHERE embedding IS NULL OR vector_dims(embedding) <> 1024
                        OR (embedding <#> embedding) >= 0) FROM {source}"""
                    )
                )
            ).one()
            if not count or invalid:
                raise ValueError(
                    "Source snapshot is empty or contains invalid/incomplete vectors."
                )

            async with destination_engine.begin() as writer:
                locked = (
                    await writer.execute(
                        text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
                        {"name": target_table},
                    )
                ).scalar_one()
                if not locked:
                    raise ValueError("Another migration is using this staging table.")
                await writer.execute(text("SET LOCAL lock_timeout = '10s'"))
                if (
                    await writer.execute(
                        text("SELECT to_regclass(:name)"), {"name": target}
                    )
                ).scalar_one() is not None:
                    raise ValueError(
                        "Target already exists; it will not be overwritten."
                    )
                # No live vector index, sequence defaults, or foreign keys are copied.
                await writer.execute(
                    text(f"CREATE TABLE {target} (LIKE {live} INCLUDING CONSTRAINTS)")
                )
                await writer.execute(text(f"ALTER TABLE {target} ADD PRIMARY KEY (id)"))
                insert = text(
                    f"INSERT INTO {target} SELECT * FROM "
                    f"jsonb_populate_record(NULL::{target}, CAST(:row AS jsonb))"
                )
                source_digest = hashlib.sha256()
                copied = 0
                # PostgreSQL's JSON representation round-trips vector float32 values,
                # nullable fields and enum/JSON metadata without client-side coercion.
                stream = await reader.stream(
                    text(f"SELECT to_jsonb(s)::text FROM {source} s ORDER BY id"),
                    execution_options={"yield_per": batch_size},
                )
                async for batch in stream.partitions(batch_size):
                    records = []
                    for (row,) in batch:
                        source_digest.update(row.encode("utf-8") + b"\n")
                        records.append({"row": row})
                    await writer.execute(insert, records)
                    copied += len(records)
                    logger.info(
                        "Transferred %s/%s chunks to staging (not committed)",
                        copied,
                        count,
                    )

                destination_digest = hashlib.sha256()
                verified = 0
                stream = await writer.stream(
                    text(f"SELECT to_jsonb(t)::text FROM {target} t ORDER BY id"),
                    execution_options={"yield_per": batch_size},
                )
                async for batch in stream.partitions(batch_size):
                    for (row,) in batch:
                        destination_digest.update(row.encode("utf-8") + b"\n")
                        verified += 1
                if (
                    copied != count
                    or verified != count
                    or source_digest.digest() != destination_digest.digest()
                ):
                    raise ValueError(
                        "Destination copy differs from the source snapshot."
                    )
                mismatches = (
                    await writer.execute(
                        text(
                            f"""SELECT count(*) FROM {live} c
                            FULL JOIN {target} t USING (id)
                            WHERE c.id IS NULL OR t.id IS NULL
                            OR (to_jsonb(c) - 'embedding') IS DISTINCT FROM
                               (to_jsonb(t) - 'embedding')"""
                        )
                    )
                ).scalar_one()
                if mismatches:
                    raise ValueError(
                        f"{mismatches} live chunks are missing or changed; staging transfer rolled back."
                    )
                # Publish the recognized manifest only after all checks pass.
                literal = json.dumps(manifest, sort_keys=True).replace("'", "''")
                await writer.execute(text(f"COMMENT ON TABLE {target} IS '{literal}'"))
            logger.info(
                "Committed %s verified staging rows; live chunks are unchanged", count
            )
            return count
    finally:
        await source_engine.dispose()
        await destination_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--source-table-name", required=True)
    parser.add_argument("--target-table-name", required=True)
    parser.add_argument("--live-table-name", default="chunks")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    # Deliberately never fall back to the app's DATABASE_URL or EVAL_DATABASE_URL.
    source_url = read_env_value("SOURCE_DATABASE_URL", env_file=args.env_file)
    destination_url = read_env_value("DESTINATION_DATABASE_URL", env_file=args.env_file)
    if not source_url or not destination_url:
        parser.error("SOURCE_DATABASE_URL and DESTINATION_DATABASE_URL are required.")
    try:
        count = asyncio.run(
            transfer_embeddings(
                source_url,
                destination_url,
                source_table=args.source_table_name,
                target_table=args.target_table_name,
                live_table=args.live_table_name,
                batch_size=args.batch_size,
            )
        )
    except Exception as exc:
        # SQL/driver exceptions can contain credentials or full chunk text.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        parser.exit(1, f"Transfer failed; no live vectors were changed: {message}\n")
    print(f"Copied and verified {count} chunks. Live embeddings were not changed.")


if __name__ == "__main__":
    main()
