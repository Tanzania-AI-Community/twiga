"""
Record cosine distances and per-step latency of today's search for each eval query.

Writes distances.jsonl (vector top 50 chunk ids with their cosine distances) for
the cutoff experiment in evaluate.py, and prints where search time goes:
the embedding call (fresh client per query, as in production, vs a reused client)
and the pgvector query.

Run from the twiga/ directory:
docker exec -w /app -e PYTHONPATH=/app dev-app-1 uv run python scripts/eval/search_knowledge/measure_search.py
"""

import asyncio
import json
import statistics
import time
from pathlib import Path

from sqlalchemy import select

from app.database.engine import get_session
from app.database.enums import ChunkType
from app.database.models import Chunk
from app.utils import embedder

HERE = Path(__file__).parent
POOL = 50


def summary(name: str, seconds: list[float]) -> str:
    seconds = sorted(seconds)
    p95 = seconds[int(0.95 * (len(seconds) - 1))]
    return f"{name}: p50 {statistics.median(seconds):.3f}s, p95 {p95:.3f}s, max {seconds[-1]:.3f}s"


async def main():
    questions = [json.loads(line) for line in open(HERE / "questions.jsonl")]
    reused_client = embedder.get_embedding_client()
    fresh, reused, db_times = [], [], []
    rows = []
    for q in questions:
        start = time.perf_counter()
        await asyncio.to_thread(embedder.get_embedding, q["query"])  # production path
        fresh.append(time.perf_counter() - start)

        start = time.perf_counter()
        vector = await asyncio.to_thread(reused_client.embed_query, q["query"])
        reused.append(time.perf_counter() - start)

        distance = Chunk.embedding.cosine_distance(vector)
        start = time.perf_counter()
        async with get_session() as session:
            result = await session.execute(
                select(Chunk.id, distance)
                .where(Chunk.chunk_type == ChunkType.text)
                .order_by(distance)
                .limit(POOL)
            )
            hits = result.all()
        db_times.append(time.perf_counter() - start)
        rows.append(
            {
                "id": q["id"],
                "ranking": [h[0] for h in hits],
                "distances": [round(float(h[1]), 4) for h in hits],
            }
        )
        await asyncio.sleep(1)  # stay under the embedding per-minute quota

    with open(HERE / "distances.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(summary("embedding, new client per query (production)", fresh[1:]))
    print(summary("embedding, reused client", reused))
    print(summary("pgvector query, top 50", db_times))
    print(f"first production embedding call (cold): {fresh[0]:.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
