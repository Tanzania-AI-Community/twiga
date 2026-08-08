"""Twiga's live runtime settings, imported so the eval can't drift from it.

Everything the eval uses to imitate Twiga's answering pipeline — model,
temperature, max tokens, embedding model, and how many chunks retrieval
returns — is read from Twiga's own config and tool code, never hardcoded here.
Change a value in Twiga and the eval follows automatically.

If Twiga's config can't be imported (e.g. an eval-only deployment without the
full app environment), we fall back to the last-known production values and log
a warning, so the eval still runs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Fallbacks — only used if app.config / the tool module can't be imported.
_FALLBACK = {
    "GEN_MODEL": "MiniMaxAI/MiniMax-M3",
    "GEN_TEMPERATURE": 0.25,
    "GEN_MAX_TOKENS": 8192,
    "EMBEDDING_MODEL": "intfloat/multilingual-e5-large-instruct",
    "RETRIEVAL_TOP_K": 15,
}

try:
    from app.config import embedding_settings, llm_settings
    from app.tools.tool_code.search_knowledge.main import SEARCH_KNOWLEDGE_N_RESULTS

    GEN_MODEL: str = llm_settings.llm_name
    GEN_TEMPERATURE: float = float(llm_settings.temperature)
    GEN_MAX_TOKENS: int = int(llm_settings.max_tokens or _FALLBACK["GEN_MAX_TOKENS"])
    EMBEDDING_MODEL: str = embedding_settings.embedder_name
    RETRIEVAL_TOP_K: int = SEARCH_KNOWLEDGE_N_RESULTS
    IMPORTED_FROM_TWIGA = True
except Exception as e:  # pragma: no cover - defensive
    logger.warning(
        "Could not import Twiga's config (%s) — falling back to last-known "
        "production values. Verify these still match Twiga.",
        e,
    )
    GEN_MODEL = _FALLBACK["GEN_MODEL"]
    GEN_TEMPERATURE = _FALLBACK["GEN_TEMPERATURE"]
    GEN_MAX_TOKENS = _FALLBACK["GEN_MAX_TOKENS"]
    EMBEDDING_MODEL = _FALLBACK["EMBEDDING_MODEL"]
    RETRIEVAL_TOP_K = _FALLBACK["RETRIEVAL_TOP_K"]
    IMPORTED_FROM_TWIGA = False
