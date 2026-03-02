import argparse
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import select

from app.database.models import Chunk
from scripts.database.reembedding_utils import (
    TogetherEmbeddingClient,
    project_root,
    read_env_value,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 8
DEFAULT_MODEL = "intfloat/multilingual-e5-large-instruct"


@dataclass
class ReembeddingStats:
    processed_chunks: int = 0
    processed_batches: int = 0
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
    if parsed.hostname and "neon.tech" in parsed.hostname:
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_params.setdefault("ssl", "require")
        normalized = parsed._replace(query=urlencode(query_params)).geturl()

    return normalized


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


async def _fetch_chunk_batch(
    session: AsyncSession,
    start_after_id: int,
    batch_size: int,
    resource_id: int | None = None,
) -> list[tuple[int, str]]:
    statement = select(Chunk.id, Chunk.content).where(Chunk.id > start_after_id)
    if resource_id is not None:
        statement = statement.where(Chunk.resource_id == resource_id)
    statement = statement.order_by(Chunk.id).limit(batch_size)

    result = await session.execute(statement)
    return [(row[0], row[1]) for row in result.all()]


async def reembed_chunks_in_database(
    database_url: str,
    embedding_client: TogetherEmbeddingClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    start_after_id: int = 0,
    resource_id: int | None = None,
    docker_db_host: str = "db",
    host_db_host: str = "localhost",
    dry_run: bool = False,
) -> ReembeddingStats:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")
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
            while True:
                current_batch_size = (
                    min(batch_size, remaining) if remaining is not None else batch_size
                )
                if current_batch_size <= 0:
                    break

                batch_rows = await _fetch_chunk_batch(
                    session=session,
                    start_after_id=current_id,
                    batch_size=current_batch_size,
                    resource_id=resource_id,
                )
                if not batch_rows:
                    break

                chunk_ids = [chunk_id for chunk_id, _ in batch_rows]
                chunk_texts = [content for _, content in batch_rows]
                embeddings = embedding_client.embed_documents(chunk_texts)

                if len(embeddings) != len(batch_rows):
                    raise ValueError(
                        "Together returned an unexpected number of embeddings."
                    )

                if not dry_run:
                    for chunk_id, embedding in zip(chunk_ids, embeddings):
                        await session.execute(
                            update(Chunk)
                            .where(Chunk.id == chunk_id)
                            .values(embedding=embedding)
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
        limit=args.limit,
        start_after_id=args.start_after_id,
        resource_id=args.resource_id,
        docker_db_host=args.docker_db_host,
        host_db_host=args.host_db_host,
        dry_run=args.dry_run,
    )

    logger.info(
        "Done. Processed %s chunks in %s batches. Last chunk ID: %s. Dry run: %s",
        stats.processed_chunks,
        stats.processed_batches,
        stats.last_chunk_id,
        args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
