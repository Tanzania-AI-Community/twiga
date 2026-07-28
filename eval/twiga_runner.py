"""Replicates Twiga's core pipeline for evaluation.

For each question row:
  1. Look up class_id from (subject, grade_level) in the DB
  2. Fetch resource_ids for that class
  3. Embed the question and vector-search (top-15, same as search_knowledge tool)
  4. Format context with Twiga's citation-marker format
  5. Call LLM with Twiga's real system prompt + context
  6. Strip citation markers from the response
  7. Return response + plain retrieved context for metric scoring

No WhatsApp delivery, no citation rendering, no LaTeX processing.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

import asyncpg
from openai import AsyncOpenAI

from eval import generation_cache

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter names the same model differently than Together. Same underlying
# weights either way -- update this if Twiga's production GEN_MODEL changes.
_OPENROUTER_MODEL_SLUGS = {
    "MiniMaxAI/MiniMax-M3": "minimax/minimax-m3",
}


def openrouter_slug(model: str) -> str:
    return _OPENROUTER_MODEL_SLUGS.get(model, model)


# DeepInfra hosts EMBEDDING_MODEL under the identical HuggingFace-style id, so
# no slug translation is needed here (unlike the OpenRouter generation model).
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

_SYSTEM_PROMPT_PATH = (
    Path(__file__).parent.parent
    / "app" / "assets" / "prompts" / "twiga_system" / "v0.0"
)

_CITATION_RE = re.compile(r'\{\{TWIGA_CITATION:\{"chunk_id":\d+\}\}\}')

_GRADE_DISPLAY = {
    "os1": "Form 1", "os2": "Form 2", "os3": "Form 3", "os4": "Form 4",
    "as1": "Form 5", "as2": "Form 6",
}

# All Twiga-mirroring settings come from eval.twiga_config, which reads them
# from Twiga's own config/tool code — so the eval can't silently drift from
# production. Change them in Twiga, not here.
from eval.twiga_config import (  # noqa: E402
    EMBEDDING_MODEL,
    GEN_MAX_TOKENS,
    GEN_MODEL,
    GEN_TEMPERATURE,
    RETRIEVAL_TOP_K,
)

DEFAULT_TIMEOUT_S = 300.0


def _load_system_prompt(subject: str, grade_level: str) -> str:
    text = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    grade = _GRADE_DISPLAY.get(grade_level, grade_level)
    class_info = f"{subject.capitalize()} {grade}"
    return text.format(user_name="Eval Teacher", class_info=class_info)


def _strip_citations(text: str) -> str:
    return _CITATION_RE.sub("", text).strip()


async def _embed(embed_api_key: str, text: str, timeout: float = DEFAULT_TIMEOUT_S) -> list[float]:
    # No "query:"/"passage:" prefix -- DeepInfra's docs recommend one, but
    # production's own embedder (app/utils/embedder.py) sends raw text, and
    # matching production exactly matters more here than following generic
    # best-practice advice for the model.
    client = AsyncOpenAI(base_url=DEEPINFRA_BASE_URL, api_key=embed_api_key, timeout=timeout)
    resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return resp.data[0].embedding


def _format_context_for_llm(chunks: list[tuple[int, str, str | None]]) -> str:
    """Format retrieved chunks the same way search_knowledge does."""
    parts = []
    for chunk_id, content, section_title in chunks:
        heading = (
            f"-text from section {section_title}"
            if section_title else "-text"
        )
        parts.append(heading)
        parts.append(content)
        parts.append(f'Cite as: {{{{TWIGA_CITATION:{{"chunk_id":{chunk_id}}}}}}}\n')
    return "\n".join(parts)


async def _get_class_id(
    conn: asyncpg.Connection, subject: str, grade_level: str
) -> int | None:
    row = await conn.fetchrow(
        """
        SELECT cl.id
        FROM classes cl
        JOIN subjects s ON cl.subject_id = s.id
        WHERE s.name = $1 AND cl.grade_level = $2
        """,
        subject,
        grade_level,
    )
    return int(row["id"]) if row else None


async def _get_resource_ids(conn: asyncpg.Connection, class_id: int) -> list[int]:
    rows = await conn.fetch(
        "SELECT resource_id FROM classes_resources WHERE class_id = $1",
        class_id,
    )
    return [int(r["resource_id"]) for r in rows]


async def _vector_search(
    conn: asyncpg.Connection,
    embedding: list[float],
    resource_ids: list[int],
    top_k: int,
) -> list[tuple[int, str, str | None]]:
    """Returns (chunk_id, content, section_title) tuples ordered by similarity."""
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    rows = await conn.fetch(
        """
        SELECT c.id, c.content, c.top_level_section_title
        FROM chunks c
        WHERE c.resource_id = ANY($1::int[]) AND c.chunk_type = 'text'
        ORDER BY c.embedding <=> $2::vector
        LIMIT $3
        """,
        resource_ids,
        emb_str,
        top_k,
    )
    return [(int(r["id"]), r["content"], r.get("top_level_section_title")) for r in rows]


async def _generate(
    client: Any,
    model: str,
    system_prompt: str,
    question: str,
    formatted_context: str,
) -> str:
    user_msg = f"Textbook content:\n{formatted_context}\n\nTeacher's question: {question}"
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        # match Twiga's real generation params (from eval.twiga_config)
        temperature=GEN_TEMPERATURE,
        max_tokens=GEN_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()


async def run_twiga_pipeline(
    rows: list[dict[str, Any]],
    conn: asyncpg.Connection,
    embed_api_key: str,
    gen_api_key: str,
    gen_model: str = GEN_MODEL,
    top_k: int = RETRIEVAL_TOP_K,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    progress_cb: Callable[[int, int], None] | None = None,
    update_cb: Callable[[dict], None] | None = None,
) -> list[dict[str, Any]]:
    """Run Twiga's pipeline for each row.

    Each row must have 'question' or 'user_query', 'subject', 'grade_level'.
    Returns result dicts with 'response', 'retrieved_context' (plain text),
    'retrieved_chunk_ids', plus all input fields passed through.

    `embed_api_key` (DeepInfra) embeds the question; `gen_api_key`
    (OpenRouter) generates the answer. Split into two providers because
    Together (production's actual provider for both) may not have credit for
    one even when it does for the other — and neither is used here at all.
    """
    gen_client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=gen_api_key, timeout=timeout_s)

    class_id_cache: dict[tuple[str, str], int | None] = {}
    resource_id_cache: dict[int, list[int]] = {}

    fingerprint = generation_cache.twiga_pipeline_fingerprint(gen_model, top_k)
    gen_cache_hits = generation_cache.HitCounter()

    results: list[dict[str, Any]] = []
    total = len(rows)

    for i, row in enumerate(rows):
        subject = str(row.get("subject", ""))
        grade_level = str(row.get("grade_level", ""))
        question = str(row.get("user_query", "") or row.get("question", ""))

        result: dict[str, Any] = {
            **row,
            "user_query": question,
        }

        gen_cache_key = generation_cache.make_key(fingerprint, subject, grade_level, question)
        cached = generation_cache.get(gen_cache_key)
        if cached is not None:
            gen_cache_hits.hit()
            result.update(cached)
            results.append(result)
            if progress_cb:
                progress_cb(i + 1, total)
            if update_cb:
                update_cb(result)
            continue
        gen_cache_hits.miss()

        try:
            cache_key = (subject, grade_level)
            if cache_key not in class_id_cache:
                class_id_cache[cache_key] = await _get_class_id(conn, subject, grade_level)
            class_id = class_id_cache[cache_key]

            if class_id is None:
                result["error"] = f"No class found in DB for {subject}/{grade_level}"
                logger.warning("No class for %s/%s (row %d)", subject, grade_level, i)
                results.append(result)
                if progress_cb:
                    progress_cb(i + 1, total)
                if update_cb:
                    update_cb(result)
                continue

            if class_id not in resource_id_cache:
                resource_id_cache[class_id] = await _get_resource_ids(conn, class_id)
            resource_ids = resource_id_cache[class_id]

            if not resource_ids:
                result["error"] = f"No resources for class_id={class_id}"
                results.append(result)
                if progress_cb:
                    progress_cb(i + 1, total)
                if update_cb:
                    update_cb(result)
                continue

            embedding = await _embed(embed_api_key, question, timeout_s)
            chunks = await _vector_search(conn, embedding, resource_ids, top_k)

            # the class's full resource set, for whole-book claim auditing
            result["resource_ids"] = json.dumps(resource_ids)
            result["retrieved_chunk_ids"] = json.dumps([c[0] for c in chunks])
            # plain text for metric scoring (faithfulness needs this)
            result["retrieved_context"] = "\n\n".join(c[1] for c in chunks)
            # per-chunk list for DeepEval metrics that take retrieval_context
            result["retrieved_chunk_contents"] = json.dumps(
                [c[1] for c in chunks], ensure_ascii=False
            )

            formatted_context = _format_context_for_llm(chunks)
            system_prompt = _load_system_prompt(subject, grade_level)

            raw_response = await _generate(
                gen_client, openrouter_slug(gen_model), system_prompt, question, formatted_context
            )
            # citations kept for citation-correctness scoring; stripped copy
            # for metrics that should see plain prose
            result["response_with_citations"] = raw_response
            result["response"] = _strip_citations(raw_response)

            generation_cache.put(gen_cache_key, {
                "resource_ids": result["resource_ids"],
                "retrieved_chunk_ids": result["retrieved_chunk_ids"],
                "retrieved_context": result["retrieved_context"],
                "retrieved_chunk_contents": result["retrieved_chunk_contents"],
                "response_with_citations": result["response_with_citations"],
                "response": result["response"],
            })

        except Exception as e:
            result["error"] = str(e)
            logger.error("Twiga pipeline row %d failed: %s", i, e)

        results.append(result)
        if progress_cb:
            progress_cb(i + 1, total)
        if update_cb:
            update_cb(result)

    gen_cache_hits.log("twiga_pipeline")

    return results
