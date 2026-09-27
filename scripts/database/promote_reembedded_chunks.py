"""Validate staged embeddings and optionally apply them with an atomic backup.

Retrieval must be paused and the query provider coordinated before --apply.
Validation is read-only by default. No Google credentials or API calls are needed.
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.utils.google_embedder import DOCUMENT_MAX_BYTES
from scripts.database.reembed_chunks_in_db import (
    _quote_identifier,
    normalize_database_url,
    rewrite_container_hostname,
    validate_table_name,
)
from scripts.database.reembedding_utils import project_root, read_env_value


async def promote_embeddings(
    database_url: str,
    target_table: str,
    *,
    source_table: str = "chunks",
    backup_table: str = "chunks_embeddings_before_google",
    model: str = "gemini-embedding-001",
    apply: bool = False,
) -> int:
    names = [source_table, target_table, backup_table]
    if len(set(names)) != 3:
        raise ValueError("Source, staging and backup tables must be different.")
    source, target, backup = [
        _quote_identifier(validate_table_name(name)) for name in names
    ]
    engine = create_async_engine(
        normalize_database_url(rewrite_container_hostname(database_url))
    )
    try:
        async with engine.begin() as conn:
            if apply:
                locked = (
                    await conn.execute(
                        text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
                        {"name": target_table},
                    )
                ).scalar_one()
                if not locked:
                    raise ValueError("A migration is still using this staging table.")
                await conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                # Block ingestion/staging writes until validation, backup and update commit.
                await conn.execute(
                    text(f"LOCK TABLE {source}, {target} IN SHARE ROW EXCLUSIVE MODE")
                )
            else:
                await conn.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
            comment = (
                await conn.execute(
                    text("SELECT obj_description(to_regclass(:name), 'pg_class')"),
                    {"name": target},
                )
            ).scalar_one()
            manifest = json.loads(comment or "null")
            expected = {
                "migration": "twiga-reembedding-v1",
                "source": source_table,
                "provider": "google",
                "model": model,
                "dimensions": 1024,
                "task_type": "RETRIEVAL_DOCUMENT",
                "document_max_bytes": DOCUMENT_MAX_BYTES,
                "max_token_estimate": None,
            }
            if not isinstance(manifest, dict) or any(
                manifest.get(k) != v for k, v in expected.items()
            ):
                raise ValueError(
                    "Staging manifest does not match the requested Google embedding configuration."
                )
            count = (
                await conn.execute(text(f"SELECT count(*) FROM {source}"))
            ).scalar_one()
            if not count:
                raise ValueError("Refusing to promote an empty corpus.")
            mismatches = (
                await conn.execute(
                    text(
                        f"""
                SELECT count(*) FROM {source} s FULL JOIN {target} t USING (id)
                WHERE s.id IS NULL OR t.id IS NULL
                   OR (to_jsonb(s) - 'embedding') IS DISTINCT FROM (to_jsonb(t) - 'embedding')
                   OR t.embedding IS NULL OR vector_dims(t.embedding) <> 1024
                   OR (t.embedding <#> t.embedding) >= 0
            """
                    )
                )
            ).scalar_one()
            if mismatches:
                raise ValueError(
                    f"{mismatches} chunks are missing, changed or have invalid/incomplete embeddings."
                )
            if apply:
                # CREATE (without IF NOT EXISTS) prevents overwriting an earlier backup.
                await conn.execute(
                    text(f"CREATE TABLE {backup} AS SELECT id, embedding FROM {source}")
                )
                await conn.execute(text(f"ALTER TABLE {backup} ADD PRIMARY KEY (id)"))
                result = await conn.execute(
                    text(
                        f"UPDATE {source} s SET embedding = t.embedding FROM {target} t WHERE s.id = t.id"
                    )
                )
                if result.rowcount != count:
                    raise ValueError(
                        "Updated row count does not match the validated corpus."
                    )
            return count
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=project_root() / ".env")
    parser.add_argument("--target-table-name", default="chunks_tmp_reembed")
    parser.add_argument("--source-table-name", default="chunks")
    parser.add_argument(
        "--backup-table-name", default="chunks_embeddings_before_google"
    )
    parser.add_argument("--model", default="gemini-embedding-001")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply validated vectors and save old vectors. Requires coordinated retrieval downtime.",
    )
    args = parser.parse_args()
    database_url = read_env_value("DATABASE_URL", env_file=args.env_file)
    if not database_url:
        raise ValueError("DATABASE_URL is required.")
    count = asyncio.run(
        promote_embeddings(
            database_url,
            args.target_table_name,
            source_table=args.source_table_name,
            backup_table=args.backup_table_name,
            model=args.model,
            apply=args.apply,
        )
    )
    print(
        f"{'Applied and backed up' if args.apply else 'Validated'} {count} chunk embeddings."
    )


if __name__ == "__main__":
    main()
