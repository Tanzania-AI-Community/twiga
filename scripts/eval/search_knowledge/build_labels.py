"""
Build relevance labels for the search_knowledge eval set.

For each query in questions.jsonl, pool candidate chunks from vector search and
Postgres full-text search, then ask the LLM to grade each candidate:
2 = directly answers the query, 1 = partially relevant, 0 = not relevant.
Labels are written to labels.jsonl and should be spot-checked by a person.

Run from the twiga/ directory:
docker exec -w /app -e PYTHONPATH=/app dev-app-1 uv run python scripts/eval/search_knowledge/build_labels.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select

from app.config import LLMProvider, llm_settings
from app.database.db import vector_search
from app.database.engine import get_session
from app.database.enums import ChunkType
from app.database.models import Chunk
from app.utils.llm_utils import async_llm_request

HERE = Path(__file__).parent
VECTOR_POOL = 50
KEYWORD_POOL = 20
CONCURRENCY = 2

JUDGE_PROMPT = """You grade search results for a teaching assistant used by secondary school teachers in Tanzania.
For the search query, grade every numbered textbook chunk:
2 = directly answers or covers the query
1 = partially relevant, useful background for the query
0 = not relevant
Reply with only a JSON object mapping every chunk number to its grade, e.g. {"12": 2, "40": 0}."""


async def keyword_search(query: str, n_results: int) -> list[Chunk]:
    # OR the words together; plainto_tsquery needs every word, so long phrases match nothing.
    words = re.findall(r"[a-zA-Z]+", query)
    tsquery = func.to_tsquery("english", " | ".join(words))
    tsvector = func.to_tsvector("english", Chunk.content)
    async with get_session() as session:
        result = await session.execute(
            select(Chunk)
            .where(Chunk.chunk_type == ChunkType.text, tsvector.op("@@")(tsquery))
            .order_by(func.ts_rank(tsvector, tsquery).desc())
            .limit(n_results)
        )
        return list(result.scalars().all())


async def judge(
    query: str, chunks: list[Chunk], model: str | None = None
) -> dict[int, int]:
    listing = "\n\n".join(f"[{c.id}]\n{c.content}" for c in chunks)
    # A different Together model can be passed for a second, independent judge.
    override = (
        {
            "model_name": model,
            "provider": LLMProvider.TOGETHER,
            "api_key": llm_settings.api_key,
            # Reasoning models need longer than the app's default timeout here.
            "timeout": 300,
        }
        if model
        else {}
    )
    response = await async_llm_request(
        messages=[
            SystemMessage(content=JUDGE_PROMPT),
            HumanMessage(content=f"Search query: {query}\n\nChunks:\n\n{listing}"),
        ],
        run_name="search_knowledge_eval_judge",
        temperature=0,
        **override,
    )
    text = re.sub(r"<think>.*?</think>", "", str(response.content), flags=re.S)
    grades = json.loads(re.search(r"\{.*\}", text, flags=re.S).group(0))
    ids = {c.id for c in chunks}
    labels = {int(k): int(v) for k, v in grades.items() if int(k) in ids}
    missing = ids - labels.keys()
    if missing:
        raise ValueError(f"Judge skipped {len(missing)} chunks for '{query}'")
    return labels


async def label_question(question: dict) -> dict:
    vector = await vector_search(
        query=question["query"],
        n_results=VECTOR_POOL,
        where={"chunk_type": [ChunkType.text]},
    )
    keyword = await keyword_search(question["query"], KEYWORD_POOL)
    pool = list({c.id: c for c in vector + keyword}.values())
    labels = await judge(question["query"], pool)
    relevant = sum(1 for g in labels.values() if g == 2)
    print(f"{question['id']} {question['query']!r}: {relevant}/{len(pool)} grade 2")
    return {
        **question,
        "vector_ranking": [c.id for c in vector],
        "labels": {str(k): v for k, v in sorted(labels.items())},
    }


async def label_with_retries(question: dict, semaphore: asyncio.Semaphore, out):
    async with semaphore:
        for attempt in range(4):
            try:
                result = await label_question(question)
                # Append as we go so a crash keeps finished questions.
                out.write(json.dumps(result) + "\n")
                out.flush()
                return
            except Exception as e:
                print(f"  retry {attempt + 1} for {question['id']}: {e!r}")
                await asyncio.sleep(10 * (attempt + 1))
        print(f"  FAILED {question['id']}, rerun the script to retry it")


async def main():
    questions = [json.loads(line) for line in open(HERE / "questions.jsonl")]
    if len(sys.argv) > 1:  # optional limit for a quick trial run
        questions = questions[: int(sys.argv[1])]
    labels_path = HERE / "labels.jsonl"
    done = (
        {json.loads(line)["id"] for line in open(labels_path)}
        if labels_path.exists()
        else set()
    )
    todo = [q for q in questions if q["id"] not in done]
    print(f"{len(done)} already labelled, {len(todo)} to go")
    semaphore = asyncio.Semaphore(CONCURRENCY)
    with open(labels_path, "a") as out:
        await asyncio.gather(*(label_with_retries(q, semaphore, out) for q in todo))


if __name__ == "__main__":
    asyncio.run(main())
