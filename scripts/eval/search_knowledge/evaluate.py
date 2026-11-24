"""
Score search_knowledge retrieval against labels.jsonl, optionally with a local reranker.

Grade 2 labels count as relevant for precision/recall/MRR; nDCG uses the 0/1/2 grades.
Recall is measured against every grade-2 chunk found in the labelling pool.

Rerankers:
  none                 vector search order (today's behaviour)
  local:<hf-model>     a cross-encoder run on this machine, e.g. local:BAAI/bge-reranker-v2-m3

Run on the host (needs chunks.json, see README.md):
python3 scripts/eval/search_knowledge/evaluate.py none --k 5 8 10 15
uv run --no-project --python 3.12 --with sentence-transformers \
  python scripts/eval/search_knowledge/evaluate.py local:BAAI/bge-reranker-v2-m3 --pool 30 50
"""

import argparse
import asyncio
import json
import math
import statistics
import time
from pathlib import Path

HERE = Path(__file__).parent
TOP_K = 15


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path)]


def load_questions() -> list[dict]:
    """Labels with any manual corrections from label_overrides.jsonl applied."""
    questions = {q["id"]: q for q in load(HERE / "labels.jsonl")}
    overrides = HERE / "label_overrides.jsonl"
    if overrides.exists():
        for fix in load(overrides):
            questions[fix["id"]]["labels"][str(fix["chunk"])] = fix["grade"]
    return list(questions.values())


def metrics(ranking: list[int], labels: dict[str, int], k: int = TOP_K) -> dict:
    grades = [labels.get(str(i), 0) for i in ranking[:k]]
    relevant_total = sum(1 for g in labels.values() if g == 2)
    hits = sum(1 for g in grades if g == 2)
    first_hit = next((r for r, g in enumerate(grades, 1) if g == 2), None)
    dcg = sum((2**g - 1) / math.log2(r + 1) for r, g in enumerate(grades, 1))
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(r + 1) for r, g in enumerate(ideal, 1))
    return {
        "p@5": sum(1 for g in grades[:5] if g == 2) / 5,
        f"p@{k}": hits / k,
        f"recall@{k}": hits / relevant_total if relevant_total else None,
        "mrr": 1 / first_hit if first_hit else 0.0,
        f"ndcg@{k}": dcg / idcg if idcg else None,
    }


def make_ranker(name: str):
    """Return an async fn(query, texts) -> indices, most relevant first."""
    if name == "none":

        async def keep(query, texts):
            return list(range(len(texts)))

        return keep

    if name.startswith("local:"):
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(name.split(":", 1)[1], max_length=512)

        async def local(query, texts):
            scores = model.predict([(query, t) for t in texts], batch_size=16)
            return sorted(range(len(texts)), key=lambda i: scores[i], reverse=True)

        return local

    raise ValueError(f"Unknown reranker: {name}")


async def evaluate(
    name: str, questions: list[dict], chunks: dict, pool: int, k: int
) -> dict:
    ranker = make_ranker(name)
    await ranker("warm up", ["warm up"])  # keep model loading out of latency
    in_scope, out_of_scope, latencies = [], [], []
    for q in questions:
        candidates = q["vector_ranking"][:pool]
        start = time.perf_counter()
        order = await ranker(q["query"], [chunks[str(i)] for i in candidates])
        latencies.append(time.perf_counter() - start)
        ranking = [candidates[i] for i in order]
        if q["topic"] == "oos":
            # No good answer exists: count how many top results the judge still found relevant.
            out_of_scope.append(metrics(ranking, q["labels"], k)[f"p@{k}"])
        else:
            in_scope.append(metrics(ranking, q["labels"], k))

    summary = {"reranker": name, "pool": pool, "k": k}
    for key in in_scope[0]:
        values = [m[key] for m in in_scope if m[key] is not None]
        summary[key] = round(statistics.mean(values), 3)
    summary[f"oos_false_hits@{k}"] = round(statistics.mean(out_of_scope), 3)
    if name != "none":
        latencies.sort()
        summary["latency_p50_s"] = round(statistics.median(latencies), 3)
        summary["latency_p95_s"] = round(latencies[int(0.95 * (len(latencies) - 1))], 3)
    return summary


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rerankers", nargs="+")
    parser.add_argument("--pool", type=int, nargs="+", default=[50])
    parser.add_argument("--k", type=int, nargs="+", default=[TOP_K])
    args = parser.parse_args()

    questions = load_questions()
    chunks = json.load(open(HERE / "chunks.json"))
    rows = []
    for name in args.rerankers:
        for k in args.k:
            # Without a reranker, the pool is just the top k.
            for pool in [k] if name == "none" else args.pool:
                rows.append(await evaluate(name, questions, chunks, pool, k))
                print(json.dumps(rows[-1]))
    with open(HERE / "results.jsonl", "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
