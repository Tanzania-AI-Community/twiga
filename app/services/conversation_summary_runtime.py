"""Pinned, pool-wide summary count basis for the Together model pool."""

import hashlib
from functools import lru_cache

from tokenizers import Tokenizer

from app.config import LLMProvider, llm_settings, summary_settings
from app.database import db
from app.services.conversation_summary_service import (
    ConversationSummaryService,
    SummaryError,
)
from app.utils.llm_utils import _resolve_model_name
from app.utils.paths import paths

TOKENIZERS = {
    "zai-org/GLM-5.3-Flash": (
        "glm_5_3_flash.json",
        "19e773648cb4e65de8660ea6365e10acca112d42a854923df93db4a6f333a82d",
    ),
    "deepseek-ai/DeepSeek-V4.1-Flash": (
        "deepseek_v4_1_flash.json",
        "c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b",
    ),
}


@lru_cache(maxsize=2)
def _load_tokenizer(model: str) -> Tokenizer:
    filename, digest = TOKENIZERS[model]
    data = (paths.ASSETS / "tokenizers" / filename).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SummaryError(f"Summary tokenizer digest mismatch for {model}")
    return Tokenizer.from_str(data.decode("utf-8"))


def count_summary_tokens(text: str) -> int:
    # Both tokenizers are always used, even when a fallback is disabled or cooling.
    # This keeps persisted counts stable across supported pool configuration changes.
    if llm_settings.provider != LLMProvider.TOGETHER:
        raise SummaryError(f"Unsupported summary provider: {llm_settings.provider}")
    models = [_resolve_model_name(), *llm_settings.together_fallback_models]
    unsupported = set(models) - TOKENIZERS.keys()
    if unsupported:
        raise SummaryError(
            f"Unsupported summary model mapping: {sorted(unsupported)!r}"
        )
    return max(
        len(_load_tokenizer(model).encode(text, add_special_tokens=False).ids)
        for model in TOKENIZERS
    )


def validate_stored_counts(snapshot: db.ConversationSummarySnapshot) -> None:
    """Reject old count bases before their persisted values can influence budgets."""
    if snapshot.token_count != count_summary_tokens(snapshot.older_history_summary):
        raise SummaryError("Stored rollup count requires review and recount")
    for batch in snapshot.active_batches:
        if batch.token_count != count_summary_tokens(batch.summary_text):
            raise SummaryError("Stored batch count requires review and recount")
    if (
        snapshot.token_count > summary_settings.rollup_tokens
        or sum(batch.token_count for batch in snapshot.active_batches)
        > summary_settings.recent_tokens
    ):
        raise SummaryError("Recounted stored summaries exceed their fixed budgets")


conversation_summary_service = ConversationSummaryService(
    counter=count_summary_tokens, snapshot_validator=validate_stored_counts
)
