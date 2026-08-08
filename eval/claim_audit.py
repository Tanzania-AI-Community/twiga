"""Whole-book audit of unsupported claims: hallucination or retrieval miss?

Faithfulness judges claims against the chunks that were *retrieved*. When a
claim is unsupported there, two very different failures look identical:

  retrieval_miss — the fact IS in the textbook, retrieval just didn't surface
                   the right chunk (fix retrieval: chunking, embeddings, top-k)
  hallucination  — the fact is nowhere in the textbook (fix the prompt/model)

For each non-"yes" claim, this embeds the claim, vector-searches the class's
full resource set (top-k nearest chunks from anywhere in the book), and asks
the judge whether any of those passages support the claim. Approximate by
nature — a fact phrased very differently from the book may still be missed —
so treat retrieval_miss as a lower bound.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from eval.twiga_runner import _embed, _vector_search

logger = logging.getLogger(__name__)

AUDIT_TOP_K = 5

_AUDIT_JUDGE_PROMPT = (
    "A claim from a student-facing answer was not supported by the passages "
    "the assistant originally saw. Below are the closest-matching passages "
    "found anywhere in the textbook.\n\n"
    "Passages:\n{passages}\n\n"
    "Claim: {claim}\n\n"
    'Does any passage support the claim? Answer "yes" if the claim is stated '
    'in, or directly inferable from, at least one passage; otherwise "no". '
    "You must choose one.\n"
    'Reply with ONLY this JSON and no other text: '
    '{{"verdict": "yes" or "no", "reason": "<one short sentence>"}}'
)


async def audit_unsupported_claims(
    breakdown: dict[str, Any],
    resource_ids: list[int],
    conn: asyncpg.Connection,
    embed_api_key: str,
    judge: Any,
    top_k: int = AUDIT_TOP_K,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Tag each non-"yes" claim with source_audit: retrieval_miss|hallucination.

    Returns the breakdown with updated claim_verdicts plus
    claims_retrieval_miss / claims_hallucinated counts. Claims the audit
    fails on are left untagged (and uncounted).
    """
    items = json.loads(breakdown["claim_verdicts"])
    targets = [i for i, it in enumerate(items) if it["verdict"] != "yes"]

    n_miss = 0
    n_halluc = 0
    for i in targets:
        claim = items[i]["claim"]
        try:
            embedding = await _embed(embed_api_key, claim, timeout_s)
            chunks = await _vector_search(conn, embedding, resource_ids, top_k)
            passages = "\n\n".join(c[1] for c in chunks)
            prompt = _AUDIT_JUDGE_PROMPT.format(passages=passages, claim=claim)
            raw = (await judge.a_generate(prompt)).strip()
            if "```" in raw:
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict not in ("yes", "no"):
                raise ValueError(f"bad audit verdict {verdict!r}")

            in_book = verdict == "yes"
            items[i]["source_audit"] = "retrieval_miss" if in_book else "hallucination"
            items[i]["audit_reason"] = str(data.get("reason", ""))
            items[i]["audit_chunk_ids"] = [c[0] for c in chunks]
            if in_book:
                n_miss += 1
            else:
                n_halluc += 1
        except Exception as e:
            logger.warning("Claim audit failed for %r: %s", claim[:60], e)

    return {
        **breakdown,
        "claim_verdicts": json.dumps(items, ensure_ascii=False),
        "claims_retrieval_miss": n_miss,
        "claims_hallucinated": n_halluc,
    }
