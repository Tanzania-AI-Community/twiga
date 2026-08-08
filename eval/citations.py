"""Citation correctness scoring for Twiga responses.

Twiga cites textbook chunks inline as {{TWIGA_CITATION:{"chunk_id":N}}}.
Each citation is checked three ways:

  validity   — the cited chunk_id is one of the chunks actually retrieved
               (an id outside that set is a hallucinated citation)
  precision  — the cited chunk's content supports the statement the citation
               is attached to (judged, forced yes/no)
  coverage   — fraction of sentences in the answer that carry a citation
               (approximate: sentence splitting is heuristic)

The statement a citation "covers" is taken as the text between the previous
marker and this one, trimmed to the last two sentences.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r'\{\{TWIGA_CITATION:\{"chunk_id":(\d+)\}\}\}')
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_CITATION_JUDGE_PROMPT = (
    "You are verifying a citation in a teaching assistant's answer.\n\n"
    "Cited textbook passage:\n{chunk}\n\n"
    "Statement the citation is attached to:\n{statement}\n\n"
    'Does the cited passage support the statement? Answer "yes" if the '
    "statement is stated in, or directly inferable from, the passage. "
    'Otherwise answer "no". You must choose one.\n'
    'Reply with ONLY this JSON and no other text: '
    '{{"verdict": "yes" or "no", "reason": "<one short sentence>"}}'
)


def extract_citations(response_with_citations: str) -> list[tuple[str, int]]:
    """(statement, chunk_id) per citation marker, in order of appearance."""
    out: list[tuple[str, int]] = []
    last_end = 0
    for m in CITATION_RE.finditer(response_with_citations):
        span = response_with_citations[last_end : m.start()].strip()
        sentences = [s for s in _SENT_SPLIT_RE.split(span) if s.strip()]
        statement = " ".join(sentences[-2:]).strip()
        if statement:
            out.append((statement, int(m.group(1))))
        last_end = m.end()
    return out


def count_sentences(text: str) -> int:
    return len([s for s in _SENT_SPLIT_RE.split(text.strip()) if s.strip()])


async def score_citations(
    response_with_citations: str,
    retrieved_chunks: dict[int, str],
    judge: Any,
) -> dict[str, Any]:
    """Score one response's citations. `judge` needs an async a_generate(str).

    Returns flat columns plus a citation_details JSON list. Precision counts a
    judge failure as unscored (excluded from the denominator), while a
    hallucinated chunk_id counts as unsupported.
    """
    citations = extract_citations(response_with_citations)
    plain_text = CITATION_RE.sub("", response_with_citations)
    total_sentences = count_sentences(plain_text)

    details: list[dict] = []
    n_valid = 0
    n_supported = 0
    n_scored = 0

    for statement, chunk_id in citations:
        d: dict[str, Any] = {"chunk_id": chunk_id, "statement": statement}
        chunk = retrieved_chunks.get(chunk_id)
        if chunk is None:
            d["valid"] = False
            d["supported"] = False
            d["reason"] = "cited chunk_id was not among the retrieved chunks"
            n_scored += 1
            details.append(d)
            continue

        d["valid"] = True
        n_valid += 1
        prompt = _CITATION_JUDGE_PROMPT.format(chunk=chunk, statement=statement)
        try:
            raw = (await judge.a_generate(prompt)).strip()
            if "```" in raw:
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict not in ("yes", "no"):
                raise ValueError(f"bad verdict {verdict!r}")
            d["supported"] = verdict == "yes"
            d["reason"] = str(data.get("reason", ""))
            n_scored += 1
            if d["supported"]:
                n_supported += 1
        except Exception as e:
            d["supported"] = None
            d["reason"] = f"judge error: {e}"
            logger.warning("Citation judge failed for chunk %d: %s", chunk_id, e)
        details.append(d)

    n = len(citations)
    return {
        "citation_count": n,
        "citation_validity": (n_valid / n) if n else None,
        "citation_precision": (n_supported / n_scored) if n_scored else None,
        "citation_coverage": (
            min(n / total_sentences, 1.0) if total_sentences else None
        ),
        "citation_details": json.dumps(details, ensure_ascii=False),
    }
