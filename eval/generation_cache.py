"""Content-addressed cache for eval-pipeline generations (retrieval + answer).

Every cache key embeds a fingerprint hash of everything that determines the
output — model, temperature, max_tokens, embedding model, prompt text, and
the source of the functions that build the request. If any of those change,
the key changes with it, so a stale entry never gets served: it just becomes
unreachable and a fresh entry is written next to it. There is deliberately no
manual "cache version" to remember to bump, and no explicit staleness check —
mismatches can't collide by construction.

Not covered by the fingerprint: the database content backing retrieval (chunk
embeddings, resource text). If the corpus changes, cached answers for
unchanged questions are still served — same known limitation any content
cache has with an external data source.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / "data" / "generation_cache"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_hash(*fns: Callable) -> str:
    return _sha256("".join(inspect.getsource(fn) for fn in fns))


def twiga_pipeline_fingerprint(gen_model: str, top_k: int) -> dict[str, str]:
    """Fingerprint for eval.twiga_runner.run_twiga_pipeline's output: covers
    embedding, retrieval formatting, the real Twiga system prompt, and
    generation."""
    from eval import twiga_runner
    from eval.twiga_config import EMBEDDING_MODEL, GEN_MAX_TOKENS, GEN_TEMPERATURE

    prompt_text = twiga_runner._SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return {
        "fn": "twiga_pipeline",
        "gen_model": gen_model,
        "gen_model_slug": twiga_runner.openrouter_slug(gen_model),
        "gen_temperature": repr(GEN_TEMPERATURE),
        "gen_max_tokens": repr(GEN_MAX_TOKENS),
        "embedding_model": EMBEDDING_MODEL,
        "top_k": repr(top_k),
        "system_prompt_sha256": _sha256(prompt_text),
        "code_sha256": _source_hash(
            twiga_runner._generate,
            twiga_runner._format_context_for_llm,
            twiga_runner._embed,
        ),
    }


def retrieval_eval_fingerprint(gen_model: str) -> dict[str, str]:
    """Fingerprint for deepeval_runner._generate_response's output: the
    generic contextual-metrics prompt over CSV-provided retrieval context
    (distinct from Twiga's real system prompt)."""
    from eval import deepeval_runner
    from eval.twiga_runner import openrouter_slug

    return {
        "fn": "retrieval_eval_generate",
        "gen_model": gen_model,
        "gen_model_slug": openrouter_slug(gen_model),
        "code_sha256": _source_hash(deepeval_runner._generate_response),
    }


def make_key(fingerprint: dict[str, str], *parts: str) -> str:
    fp_hash = _sha256(json.dumps(fingerprint, sort_keys=True))[:16]
    parts_hash = _sha256(json.dumps(list(parts)))
    return f"{fp_hash}_{parts_hash}"


def get(key: str) -> dict[str, Any] | None:
    path = _CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def put(key: str, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{key}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("Failed to write generation cache entry %s", key)


class HitCounter:
    """Small per-run tally so callers can log a hit/miss summary."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    def hit(self) -> None:
        self.hits += 1

    def miss(self) -> None:
        self.misses += 1

    def log(self, label: str) -> None:
        total = self.hits + self.misses
        if total:
            logger.info(
                "[%s] generation cache: %d/%d reused (%d fresh)",
                label, self.hits, total, self.misses,
            )
