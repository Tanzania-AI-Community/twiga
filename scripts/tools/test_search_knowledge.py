"""
Manual test script for the search_knowledge function.

This script tests the actual search_knowledge tool against the current database
and embeddings setup. Run it manually to inspect the returned payload.

Usage:
    docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_search_knowledge.py --search-phrase 'benefits of forests to people living nearby' --class-id 1"
"""

import argparse
import asyncio

from app.tools.tool_code.search_knowledge.main import search_knowledge


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual search_knowledge tool test")
    parser.add_argument(
        "--search-phrase",
        default="photosynthesis",
        help="Phrase to search in the knowledge base.",
    )
    parser.add_argument(
        "--class-id",
        type=int,
        default=1,
        help="Class ID used to filter searchable resources.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    print("Running search_knowledge test")
    print(f"search_phrase: {args.search_phrase}")
    print(f"class_id: {args.class_id}")

    try:
        result = await search_knowledge(
            search_phrase=args.search_phrase,
            class_id=args.class_id,
        )
    except Exception as exc:
        print(f"search_knowledge failed: {exc}")
        return 1

    content_string = result.get("content")
    source_chunk_ids = result.get("source_chunk_ids")

    print("\n\n" + "=" * 80)
    print("Raw result:")
    print(f"content_string:\n {content_string}\n\n")
    print("-" * 80)
    print(f"source_chunk_ids: {source_chunk_ids}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
