import argparse
import json
import logging
from pathlib import Path
from typing import Any

from scripts.database.reembedding_utils import (
    TogetherEmbeddingClient,
    chunked,
    project_root,
    read_env_value,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 8
DEFAULT_MODEL = "intfloat/multilingual-e5-large-instruct"
DEFAULT_INPUT_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "sample_data"
    / "chunks_BAAI.json"
)
DEFAULT_OUTPUT_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "sample_data"
    / "chunks_multimodal.json"
)


def load_chunks(input_file: Path) -> list[dict[str, Any]]:
    with input_file.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, list):
        raise ValueError("Input JSON must be a list of chunk objects.")

    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("Input JSON must contain only object items.")

    return payload


def reembed_chunks_payload(
    chunks: list[dict[str, Any]],
    embedding_client: TogetherEmbeddingClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict[str, Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")

    updated_chunks: list[dict[str, Any]] = []
    processed = 0

    for batch in chunked(chunks, batch_size):
        texts = []
        for item in batch:
            chunk_text = item.get("chunk")
            if not isinstance(chunk_text, str):
                raise ValueError("Every chunk must include a string 'chunk' field.")
            texts.append(chunk_text)

        embeddings = embedding_client.embed_documents(texts)
        if len(embeddings) != len(batch):
            raise ValueError("Together returned an unexpected number of embeddings.")

        for chunk_obj, embedding in zip(batch, embeddings):
            updated_chunk = dict(chunk_obj)
            updated_chunk["embedding"] = embedding
            updated_chunks.append(updated_chunk)

        processed += len(batch)
        logger.info("Re-embedded %s/%s chunks", processed, len(chunks))

    return updated_chunks


def reembed_chunks_file(
    input_file: Path,
    output_file: Path,
    embedding_client: TogetherEmbeddingClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    chunks = load_chunks(input_file)
    updated_chunks = reembed_chunks_payload(
        chunks=chunks,
        embedding_client=embedding_client,
        batch_size=batch_size,
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(updated_chunks, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return len(updated_chunks)


def _parse_args() -> argparse.Namespace:
    default_env_file = project_root() / ".env"
    parser = argparse.ArgumentParser(
        description=(
            "Create a new chunks JSON file with updated embeddings from Together."
        )
    )
    parser.add_argument(
        "--env-file",
        default=str(default_env_file),
        help="Path to .env file used as fallback for EMBEDDING_API_KEY.",
    )
    parser.add_argument(
        "--input-file",
        default=str(DEFAULT_INPUT_FILE),
        help="Input chunks JSON file path.",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Output chunks JSON file path.",
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    env_file = Path(args.env_file).expanduser()
    if not env_file.is_absolute():
        env_file = project_root() / env_file

    api_key = args.api_key or read_env_value("EMBEDDING_API_KEY", env_file=env_file)
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

    total = reembed_chunks_file(
        input_file=Path(args.input_file),
        output_file=Path(args.output_file),
        embedding_client=embedder,
        batch_size=args.batch_size,
    )
    logger.info("Wrote %s re-embedded chunks to %s", total, args.output_file)


if __name__ == "__main__":
    main()
