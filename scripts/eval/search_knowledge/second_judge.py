"""
Cross-check labels.jsonl with a second LLM judge from a different model family.

Regrades every pooled chunk in shuffled order (to avoid position bias), writes
labels_judge2.jsonl, and writes disagreements.md listing the chunks where the two
judges differ on whether a chunk is grade 2. A person resolves those in
label_overrides.jsonl. Resumes if interrupted.

Run from the twiga/ directory:
docker exec -w /app -e PYTHONPATH=/app dev-app-1 uv run python scripts/eval/search_knowledge/second_judge.py
"""

import asyncio
import json
import random
from pathlib import Path

from build_labels import judge
from sqlalchemy import select

from app.database.engine import get_session
from app.database.models import Chunk

HERE = Path(__file__).parent
MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
CONCURRENCY = 2
PREVIEW_CHARS = 300


async def regrade(question: dict, semaphore: asyncio.Semaphore, out):
    async with semaphore:
        ids = [int(i) for i in question["labels"]]
        async with get_session() as session:
            result = await session.execute(select(Chunk).where(Chunk.id.in_(ids)))
            chunks = list(result.scalars().all())
        random.Random(question["id"]).shuffle(chunks)
        for attempt in range(4):
            try:
                labels = await judge(question["query"], chunks, model=MODEL)
                break
            except Exception as e:
                print(f"  retry {attempt + 1} for {question['id']}: {e!r}")
                await asyncio.sleep(10 * (attempt + 1))
        else:
            print(f"  FAILED {question['id']}, rerun the script to retry it")
            return
        out.write(
            json.dumps(
                {
                    "id": question["id"],
                    "labels": {str(k): v for k, v in sorted(labels.items())},
                }
            )
            + "\n"
        )
        out.flush()
        print(f"{question['id']} done")


def write_disagreements(questions: list[dict], second: dict, chunks: dict) -> None:
    lines = [
        "# Label disagreements",
        "",
        f"Chunks where the first judge and {MODEL} disagree on grade 2.",
        'Resolve each in label_overrides.jsonl as {"id": "q03", "chunk": 30, "grade": 1}.',
        "",
    ]
    total = 0
    for q in questions:
        if q["id"] not in second:
            continue
        diffs = [
            (cid, g, second[q["id"]][cid])
            for cid, g in q["labels"].items()
            if (g == 2) != (second[q["id"]].get(cid) == 2)
        ]
        if not diffs:
            continue
        total += len(diffs)
        lines += [f"## {q['id']}: {q['query']}", ""]
        for cid, first, other in diffs:
            text = " ".join(chunks[cid].split())[:PREVIEW_CHARS]
            lines.append(f"- `{cid}` first={first} second={other}: {text}")
        lines.append("")
    (HERE / "disagreements.md").write_text("\n".join(lines))
    print(f"{total} disagreements written to disagreements.md")


async def main():
    questions = [json.loads(line) for line in open(HERE / "labels.jsonl")]
    path = HERE / "labels_judge2.jsonl"
    done = {json.loads(line)["id"] for line in open(path)} if path.exists() else set()
    todo = [q for q in questions if q["id"] not in done]
    print(f"{len(done)} already regraded, {len(todo)} to go")
    semaphore = asyncio.Semaphore(CONCURRENCY)
    with open(path, "a") as out:
        await asyncio.gather(*(regrade(q, semaphore, out) for q in todo))

    second = {d["id"]: d["labels"] for d in (json.loads(line) for line in open(path))}
    chunks = json.load(open(HERE / "chunks.json"))
    write_disagreements(questions, second, chunks)


if __name__ == "__main__":
    asyncio.run(main())
