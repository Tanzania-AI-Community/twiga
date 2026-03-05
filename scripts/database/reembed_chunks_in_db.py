import argparse
import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
import tiktoken
from scripts.database.reembedding_utils import (
    TogetherEmbeddingClient,
    project_root,
    read_env_value,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 8
DEFAULT_MODEL = "intfloat/multilingual-e5-large-instruct"
DEFAULT_MAX_TOKEN_ESTIMATE = 500
DEFAULT_TOKEN_CHAR_RATIO = 4
DEFAULT_TOKEN_SAFETY_FACTOR = 1.2
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ReembeddingStats:
    processed_chunks: int = 0
    processed_batches: int = 0
    over_token_limit_chunks: int = 0
    last_chunk_id: int | None = None


def normalize_database_url(database_url: str) -> str:
    """Ensure DATABASE_URL can be consumed by SQLAlchemy async engine."""
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("DATABASE_URL cannot be empty.")

    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql://", 1)

    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+asyncpg://", 1)

    if not normalized.startswith("postgresql+asyncpg://"):
        raise ValueError(
            "DATABASE_URL must start with postgres://, postgresql://, or postgresql+asyncpg://."
        )

    parsed = urlparse(normalized)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_query_params: list[tuple[str, str]] = []
    sslmode_value: str | None = None
    has_ssl = False

    for key, value in query_params:
        normalized_key = key.lower()
        if normalized_key == "sslmode":
            sslmode_value = value
            continue
        if normalized_key == "channel_binding":
            continue
        if normalized_key == "ssl":
            has_ssl = True
        normalized_query_params.append((key, value))

    if not has_ssl and sslmode_value is not None:
        normalized_query_params.append(("ssl", _map_sslmode_to_ssl(sslmode_value)))
        has_ssl = True

    if parsed.hostname and "neon.tech" in parsed.hostname and not has_ssl:
        normalized_query_params.append(("ssl", "require"))

    normalized = parsed._replace(query=urlencode(normalized_query_params)).geturl()

    return normalized


def _map_sslmode_to_ssl(sslmode: str) -> str:
    lowered = sslmode.strip().lower()
    if lowered in {"disable", "false", "off", "0"}:
        return "false"
    return "require"


def rewrite_container_hostname(
    database_url: str,
    docker_db_host: str = "db",
    host_db_host: str = "localhost",
) -> str:
    """Rewrite docker network hostname for host-side script execution."""
    if not docker_db_host or not host_db_host:
        return database_url

    parsed = urlparse(database_url)
    if parsed.hostname != docker_db_host:
        return database_url

    user_info = ""
    if parsed.username:
        user_info = parsed.username
        if parsed.password:
            user_info += f":{parsed.password}"
        user_info += "@"

    port = f":{parsed.port}" if parsed.port else ""
    rewritten = parsed._replace(netloc=f"{user_info}{host_db_host}{port}")
    return rewritten.geturl()


def validate_table_name(table_name: str) -> str:
    if not table_name or not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(
            "Invalid table name. Use letters, numbers, and underscores only."
        )
    return table_name


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier}"'


def _to_pgvector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".15g") for value in values) + "]"


@lru_cache(maxsize=1)
def _get_default_tokenizer():
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens_with_tiktoken(content: str) -> int | None:
    try:
        tokenizer = _get_default_tokenizer()
        return len(tokenizer.encode(content, disallowed_special=()))
    except Exception:
        return None


def estimate_tokens_from_content(
    content: str,
    token_char_ratio: int = DEFAULT_TOKEN_CHAR_RATIO,
    token_safety_factor: float = DEFAULT_TOKEN_SAFETY_FACTOR,
) -> int:
    tiktoken_count = _count_tokens_with_tiktoken(content)
    if tiktoken_count is not None:
        return int(math.ceil(tiktoken_count * token_safety_factor))

    char_estimate = len(content) / token_char_ratio
    return int(math.ceil(char_estimate * token_safety_factor))


def prepare_content_for_embedding(
    content: str,
    max_token_estimate: int = DEFAULT_MAX_TOKEN_ESTIMATE,
    token_char_ratio: int = DEFAULT_TOKEN_CHAR_RATIO,
    token_safety_factor: float = DEFAULT_TOKEN_SAFETY_FACTOR,
) -> tuple[str, bool]:
    token_estimate = estimate_tokens_from_content(
        content=content,
        token_char_ratio=token_char_ratio,
        token_safety_factor=token_safety_factor,
    )
    if token_estimate <= max_token_estimate:
        return content, False

    # Iteratively truncate by the estimated overflow ratio to keep more useful context.
    clipped_content = content
    for _ in range(8):
        estimated_tokens = estimate_tokens_from_content(
            content=clipped_content,
            token_char_ratio=token_char_ratio,
            token_safety_factor=token_safety_factor,
        )
        if estimated_tokens <= max_token_estimate:
            return clipped_content, True

        keep_chars = max(
            1,
            int(len(clipped_content) * (max_token_estimate / estimated_tokens) * 0.95),
        )
        if keep_chars >= len(clipped_content):
            keep_chars = len(clipped_content) - 1
        clipped_content = clipped_content[:keep_chars]

    max_chars_fallback = max_token_estimate * token_char_ratio
    return clipped_content[:max_chars_fallback], True


async def prepare_target_table(
    session: AsyncSession,
    source_table_name: str,
    target_table_name: str,
    refresh_target_table: bool,
) -> None:
    source_table = validate_table_name(source_table_name)
    target_table = validate_table_name(target_table_name)
    if source_table == target_table:
        raise ValueError("source_table_name and target_table_name must be different.")

    source_sql = _quote_identifier(source_table)
    target_sql = _quote_identifier(target_table)

    if refresh_target_table:
        await session.execute(text(f"DROP TABLE IF EXISTS {target_sql}"))
        await session.execute(
            text(f"CREATE TABLE {target_sql} (LIKE {source_sql} INCLUDING ALL)")
        )
        await session.execute(
            text(f"INSERT INTO {target_sql} SELECT * FROM {source_sql}")
        )
    else:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {target_sql} "
                f"(LIKE {source_sql} INCLUDING ALL)"
            )
        )
        result = await session.execute(text(f"SELECT COUNT(*) FROM {target_sql}"))
        row_count = int(result.scalar_one())
        if row_count == 0:
            await session.execute(
                text(f"INSERT INTO {target_sql} SELECT * FROM {source_sql}")
            )

    await session.commit()
    logger.info(
        "Prepared target table '%s' from source table '%s' (refresh=%s)",
        target_table_name,
        source_table_name,
        refresh_target_table,
    )


async def _fetch_chunk_batch(
    session: AsyncSession,
    table_name: str,
    start_after_id: int,
    batch_size: int,
    resource_id: int | None = None,
) -> list[tuple[int, str]]:
    table_sql = _quote_identifier(validate_table_name(table_name))
    base_query = (
        f"SELECT id, content FROM {table_sql} WHERE id > :start_after_id "
        f"{'AND resource_id = :resource_id' if resource_id is not None else ''} "
        "ORDER BY id LIMIT :batch_size"
    )
    params = {
        "start_after_id": start_after_id,
        "batch_size": batch_size,
    }
    if resource_id is not None:
        params["resource_id"] = resource_id

    result = await session.execute(text(base_query), params)
    return [(row[0], row[1]) for row in result.all()]


async def _update_chunk_embedding(
    session: AsyncSession,
    table_name: str,
    chunk_id: int,
    embedding: list[float],
) -> None:
    table_sql = _quote_identifier(validate_table_name(table_name))
    statement = text(
        f"UPDATE {table_sql} "
        "SET embedding = CAST(:embedding AS vector) "
        "WHERE id = :chunk_id"
    )
    await session.execute(
        statement,
        {"chunk_id": chunk_id, "embedding": _to_pgvector_literal(embedding)},
    )


async def reembed_chunks_in_database(
    database_url: str,
    embedding_client: TogetherEmbeddingClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_token_estimate: int = DEFAULT_MAX_TOKEN_ESTIMATE,
    token_char_ratio: int = DEFAULT_TOKEN_CHAR_RATIO,
    token_safety_factor: float = DEFAULT_TOKEN_SAFETY_FACTOR,
    limit: int | None = None,
    start_after_id: int = 0,
    resource_id: int | None = None,
    source_table_name: str = "chunks",
    target_table_name: str = "chunks_tmp_reembed",
    refresh_target_table: bool = True,
    docker_db_host: str = "db",
    host_db_host: str = "localhost",
    dry_run: bool = False,
) -> ReembeddingStats:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")
    if max_token_estimate <= 0:
        raise ValueError("max_token_estimate must be greater than 0.")
    if token_char_ratio <= 0:
        raise ValueError("token_char_ratio must be greater than 0.")
    if token_safety_factor <= 0:
        raise ValueError("token_safety_factor must be greater than 0.")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than 0 when provided.")
    if start_after_id < 0:
        raise ValueError("start_after_id cannot be negative.")

    rewritten_database_url = rewrite_container_hostname(
        database_url=database_url,
        docker_db_host=docker_db_host,
        host_db_host=host_db_host,
    )
    engine = create_async_engine(
        normalize_database_url(rewritten_database_url),
        echo=False,
    )
    stats = ReembeddingStats(last_chunk_id=start_after_id or None)

    remaining = limit
    current_id = start_after_id

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await prepare_target_table(
                session=session,
                source_table_name=source_table_name,
                target_table_name=target_table_name,
                refresh_target_table=refresh_target_table,
            )

            while True:
                current_batch_size = (
                    min(batch_size, remaining) if remaining is not None else batch_size
                )
                if current_batch_size <= 0:
                    break

                batch_rows = await _fetch_chunk_batch(
                    session=session,
                    table_name=target_table_name,
                    start_after_id=current_id,
                    batch_size=current_batch_size,
                    resource_id=resource_id,
                )
                if not batch_rows:
                    break

                chunk_ids = [chunk_id for chunk_id, _ in batch_rows]
                chunk_texts: list[str] = []
                over_limit_in_batch = 0
                for _, content in batch_rows:
                    clipped_content, is_over_limit = prepare_content_for_embedding(
                        content=content,
                        max_token_estimate=max_token_estimate,
                        token_char_ratio=token_char_ratio,
                        token_safety_factor=token_safety_factor,
                    )
                    if is_over_limit:
                        over_limit_in_batch += 1
                    chunk_texts.append(clipped_content)

                stats.over_token_limit_chunks += over_limit_in_batch
                if over_limit_in_batch > 0:
                    logger.info(
                        "Batch %s has %s chunks above the estimated %s token limit. Truncating inputs before embedding.",
                        stats.processed_batches + 1,
                        over_limit_in_batch,
                        max_token_estimate,
                    )

                embeddings = embedding_client.embed_documents(chunk_texts)

                if len(embeddings) != len(batch_rows):
                    raise ValueError(
                        "Together returned an unexpected number of embeddings."
                    )

                if not dry_run:
                    for chunk_id, embedding in zip(chunk_ids, embeddings):
                        await _update_chunk_embedding(
                            session=session,
                            table_name=target_table_name,
                            chunk_id=chunk_id,
                            embedding=embedding,
                        )
                    await session.commit()

                current_id = chunk_ids[-1]
                stats.last_chunk_id = current_id
                stats.processed_batches += 1
                stats.processed_chunks += len(chunk_ids)

                if remaining is not None:
                    remaining -= len(chunk_ids)

                logger.info(
                    "Processed batch %s: chunk IDs %s-%s (%s chunks total)",
                    stats.processed_batches,
                    chunk_ids[0],
                    chunk_ids[-1],
                    stats.processed_chunks,
                )

        return stats
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    default_env_file = project_root() / ".env"
    parser = argparse.ArgumentParser(
        description=(
            "Re-embed existing chunks in the database using Together's batched "
            "embeddings endpoint."
        )
    )
    parser.add_argument(
        "--env-file",
        default=str(default_env_file),
        help="Path to .env file used as fallback for DATABASE_URL and EMBEDDING_API_KEY.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Falls back to DATABASE_URL from env/.env.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Together API key. Falls back to EMBEDDING_API_KEY from env/.env.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Together embedding model. Defaults to {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Embedding batch size. Defaults to {DEFAULT_BATCH_SIZE}.",
    )
    parser.add_argument(
        "--max-token-estimate",
        type=int,
        default=DEFAULT_MAX_TOKEN_ESTIMATE,
        help=(
            "Maximum estimated tokens per chunk before truncation. "
            f"Defaults to {DEFAULT_MAX_TOKEN_ESTIMATE}."
        ),
    )
    parser.add_argument(
        "--token-char-ratio",
        type=int,
        default=DEFAULT_TOKEN_CHAR_RATIO,
        help=(
            "Character-per-token ratio for estimation. "
            f"Defaults to {DEFAULT_TOKEN_CHAR_RATIO}."
        ),
    )
    parser.add_argument(
        "--token-safety-factor",
        type=float,
        default=DEFAULT_TOKEN_SAFETY_FACTOR,
        help=(
            "Safety multiplier applied on estimated token counts to avoid "
            f"underestimation. Defaults to {DEFAULT_TOKEN_SAFETY_FACTOR}."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of chunks to process.",
    )
    parser.add_argument(
        "--start-after-id",
        type=int,
        default=0,
        help="Resume processing after this chunk ID.",
    )
    parser.add_argument(
        "--resource-id",
        type=int,
        default=None,
        help="Optional resource_id filter to re-embed only chunks from one resource.",
    )
    parser.add_argument(
        "--source-table-name",
        default="chunks",
        help="Source table to copy from before re-embedding. Defaults to chunks.",
    )
    parser.add_argument(
        "--target-table-name",
        default="chunks_tmp_reembed",
        help=(
            "Target table where embeddings are updated. "
            "Defaults to chunks_tmp_reembed."
        ),
    )
    parser.add_argument(
        "--no-refresh-target-table",
        action="store_true",
        help=(
            "Do not drop/recreate target table. If empty, it will be backfilled once "
            "from source table."
        ),
    )
    parser.add_argument(
        "--docker-db-host",
        default="db",
        help="Database hostname used inside Docker network. Defaults to db.",
    )
    parser.add_argument(
        "--host-db-host",
        default="localhost",
        help="Hostname to use when docker DB host needs host-machine access.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Together API base URL.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout for Together requests.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute embeddings without writing updates to the database.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    env_file = Path(args.env_file).expanduser()
    if not env_file.is_absolute():
        env_file = project_root() / env_file

    database_url = args.database_url or read_env_value(
        "DATABASE_URL",
        env_file=env_file,
    )
    if not database_url:
        raise ValueError(
            "DATABASE_URL is required. Pass --database-url or set DATABASE_URL."
        )

    api_key = args.api_key or read_env_value(
        "EMBEDDING_API_KEY",
        env_file=env_file,
    )
    if not api_key:
        raise ValueError(
            "EMBEDDING_API_KEY is required. Pass --api-key or set EMBEDDING_API_KEY."
        )

    model = args.model or read_env_value(
        "EMBEDDING_MODEL",
        env_file=env_file,
        default=DEFAULT_MODEL,
    )
    base_url = args.base_url or read_env_value(
        "TOGETHER_BASE_URL",
        env_file=env_file,
        default="https://api.together.xyz/v1",
    )

    embedder = TogetherEmbeddingClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=args.timeout_seconds,
    )

    stats = await reembed_chunks_in_database(
        database_url=database_url,
        embedding_client=embedder,
        batch_size=args.batch_size,
        max_token_estimate=args.max_token_estimate,
        token_char_ratio=args.token_char_ratio,
        token_safety_factor=args.token_safety_factor,
        limit=args.limit,
        start_after_id=args.start_after_id,
        resource_id=args.resource_id,
        source_table_name=args.source_table_name,
        target_table_name=args.target_table_name,
        refresh_target_table=not args.no_refresh_target_table,
        docker_db_host=args.docker_db_host,
        host_db_host=args.host_db_host,
        dry_run=args.dry_run,
    )

    logger.info(
        "Done. Processed %s chunks in %s batches. Chunks above token estimate limit: %s. Last chunk ID: %s. Dry run: %s. Target table: %s",
        stats.processed_chunks,
        stats.processed_batches,
        stats.over_token_limit_chunks,
        stats.last_chunk_id,
        args.dry_run,
        args.target_table_name,
    )


if __name__ == "__main__":
    asyncio.run(main())
