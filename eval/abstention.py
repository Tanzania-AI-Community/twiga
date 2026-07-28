"""Abstention evaluation: does Twiga decline when the textbook can't answer?

Runs deliberately unanswerable questions (eval/data/golden/abstention_questions.csv)
through the real Twiga pipeline. Retrieval will still return the *nearest*
chunks — the test is whether the model answers as if they supported the
question, or correctly says the textbook doesn't cover it.

Categories:
  out_of_domain — a different subject entirely (asking history about biology)
  not_in_book   — plausible topic, but too specific/recent for the textbook
  false_premise — embeds a wrong fact; correcting the premise also counts

A response is appropriate when the judge classifies it as "abstained" or
"corrected"; classifying as "answered" means the model fabricated an answer.
Headline metric: abstention_rate = appropriate / total.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import asyncpg
import pandas as pd

from eval.twiga_runner import run_twiga_pipeline

logger = logging.getLogger(__name__)

_ABSTENTION_JUDGE_PROMPT = (
    "A teaching assistant must answer ONLY from retrieved textbook excerpts, "
    "and must clearly say so when the excerpts do not contain the answer.\n\n"
    "The question below is known to be unanswerable from the textbook the "
    "assistant had access to.\n\n"
    "Question: {question}\n\n"
    "Assistant's response:\n{response}\n\n"
    "Classify the response:\n"
    '- "abstained": declined to answer, said the textbook/excerpts do not '
    "cover this, or redirected to an appropriate source\n"
    '- "corrected": rejected or corrected a false assumption in the question '
    "instead of accepting it\n"
    '- "answered": gave a substantive answer as though the textbook '
    "supported it\n\n"
    'Reply with ONLY this JSON and no other text: '
    '{{"verdict": "abstained" or "corrected" or "answered", '
    '"reason": "<one short sentence>"}}'
)


async def run_abstention_eval(
    rows: list[dict[str, Any]],
    conn: asyncpg.Connection,
    embed_api_key: str,
    gen_model: str,
    judge_llm: Any,
    together_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    top_k: int = 15,
    timeout_s: float = 60.0,
    progress_cb: Callable[[int, int], None] | None = None,
    update_cb: Callable[[dict], None] | None = None,
    skip_judge: bool = False,
    concurrency: int = 8,
) -> pd.DataFrame:
    """Each row needs question, subject, grade_level, category.

    skip_judge=True runs generation only (writing to the generation cache —
    see eval/generation_cache.py) and skips the abstention-verdict judge call.

    Rows are processed with up to `concurrency` in flight at once (bounded by
    an asyncio.Semaphore) — safe because `conn` is pool-backed (see
    eval/db.py) and every other client here (judge_llm, the twiga pipeline's
    own AsyncOpenAI clients) is already concurrency-safe.
    """
    total = len(rows)
    sem = asyncio.Semaphore(concurrency)

    async def _process(i: int, row: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "user_query": row["question"],
            "subject": row.get("subject", ""),
            "grade_level": row.get("grade_level", ""),
            "category": row.get("category", ""),
        }

        async with sem:
            try:
                pipeline_out = (
                    await run_twiga_pipeline(
                        [row],
                        conn=conn,
                        embed_api_key=embed_api_key,
                        together_api_key=together_api_key,
                        openrouter_api_key=openrouter_api_key,
                        gen_model=gen_model,
                        top_k=top_k,
                        timeout_s=timeout_s,
                    )
                )[0]
                if pipeline_out.get("error"):
                    raise RuntimeError(str(pipeline_out["error"]))
                response = str(pipeline_out.get("response", ""))
                result["response"] = response

                if skip_judge:
                    return result

                prompt = _ABSTENTION_JUDGE_PROMPT.format(
                    question=row["question"], response=response
                )
                raw = (await judge_llm.a_generate(prompt)).strip()
                if "```" in raw:
                    raw = raw.split("```")[1].removeprefix("json").strip()
                data = json.loads(raw)
                verdict = str(data.get("verdict", "")).strip().lower()
                if verdict not in ("abstained", "corrected", "answered"):
                    raise ValueError(f"bad abstention verdict {verdict!r}")

                result["abstention_verdict"] = verdict
                result["abstention_reason"] = str(data.get("reason", ""))
                result["abstention_ok"] = int(verdict != "answered")

            except Exception as e:
                result["error"] = str(e)
                logger.error("Abstention eval row %d failed: %s", i, e)

        return result

    results: list[dict] = []
    tasks = [asyncio.create_task(_process(i, row)) for i, row in enumerate(rows)]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        if progress_cb:
            progress_cb(len(results), total)
        if update_cb:
            update_cb(result)

    return pd.DataFrame(results)
