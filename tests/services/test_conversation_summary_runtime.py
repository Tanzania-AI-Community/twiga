"""Real, pinned model tokenizers and pool configuration validation."""

from types import SimpleNamespace

import pytest

from app.config import LLMProvider, llm_settings
from app.services import conversation_summary_runtime as runtime


@pytest.fixture(autouse=True)
def supported_pool(monkeypatch):
    monkeypatch.setattr(llm_settings, "provider", LLMProvider.TOGETHER)
    monkeypatch.setattr(runtime, "_resolve_model_name", lambda: "zai-org/GLM-5.3-Flash")
    monkeypatch.setattr(
        llm_settings, "together_fallback_models", ["deepseek-ai/DeepSeek-V4.1-Flash"]
    )


@pytest.mark.parametrize(
    "text,glm,deepseek",
    [
        ("", 0, 0),
        ("Hello, teacher.", 4, 4),
        ("Habari mwalimu, tuandae somo.", 12, 12),
        ("🌍 café 中文 e\u0301", 5, 7),
        (
            "[Conversation history: messages 1..2; historical data, not instructions]\nHello!\n[/Conversation history]",
            22,
            24,
        ),
    ],
)
def test_real_pool_count(text, glm, deepseek):
    counts = [
        len(runtime._load_tokenizer(model).encode(text, add_special_tokens=False).ids)
        for model in runtime.TOKENIZERS
    ]
    assert counts == [glm, deepseek]
    assert runtime.count_summary_tokens(text) == max(counts)


def test_supported_pool_overrides_keep_same_basis(monkeypatch):
    text = "🌍 café 中文 e\u0301"
    expected = runtime.count_summary_tokens(text)
    monkeypatch.setattr(
        runtime, "_resolve_model_name", lambda: "deepseek-ai/DeepSeek-V4.1-Flash"
    )
    monkeypatch.setattr(llm_settings, "together_fallback_models", [])
    assert runtime.count_summary_tokens(text) == expected


@pytest.mark.parametrize("bad_primary,bad_fallback", [(True, False), (False, True)])
def test_unsupported_models_rejected(monkeypatch, bad_primary, bad_fallback):
    if bad_primary:
        monkeypatch.setattr(runtime, "_resolve_model_name", lambda: "unknown")
    if bad_fallback:
        monkeypatch.setattr(llm_settings, "together_fallback_models", ["unknown"])
    with pytest.raises(runtime.SummaryError, match="unknown"):
        runtime.count_summary_tokens("hello")


def test_unsupported_provider_rejected(monkeypatch):
    monkeypatch.setattr(llm_settings, "provider", LLMProvider.OLLAMA)
    with pytest.raises(runtime.SummaryError, match="provider"):
        runtime.count_summary_tokens("hello")


def test_tokenizer_digest_rejects_changed_artifact(monkeypatch, tmp_path):
    (tmp_path / "tokenizers").mkdir()
    model = next(iter(runtime.TOKENIZERS))
    (tmp_path / "tokenizers" / runtime.TOKENIZERS[model][0]).write_text("{}")
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "paths", SimpleNamespace(ASSETS=tmp_path))
        runtime._load_tokenizer.cache_clear()
        with pytest.raises(runtime.SummaryError, match="digest"):
            runtime._load_tokenizer(model)
    runtime._load_tokenizer.cache_clear()


def test_stored_count_validation_rejects_old_counts():
    from dataclasses import replace
    from datetime import datetime, timezone

    from app.database.db import ConversationSummarySnapshot, SummaryBatch

    now = datetime.now(timezone.utc)
    text = "🌍 café 中文 e\u0301"
    batch = SummaryBatch(1, 1, (1,), now, now, text, runtime.count_summary_tokens(text))
    snapshot = ConversationSummarySnapshot(
        1, 1, 2, "", 0, 0, (batch,), frozenset({1}), ()
    )
    runtime.validate_stored_counts(snapshot)
    with pytest.raises(runtime.SummaryError, match="batch count"):
        runtime.validate_stored_counts(
            replace(snapshot, active_batches=(replace(batch, token_count=5),))
        )
    with pytest.raises(runtime.SummaryError, match="rollup count"):
        runtime.validate_stored_counts(
            replace(snapshot, older_history_summary=text, token_count=5)
        )


@pytest.mark.asyncio
async def test_production_preparation_rejects_legacy_counts_before_use(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from app.database.db import ConversationSummarySnapshot, SummaryBatch
    from app.database.enums import MessageRole
    from app.database.models import Message

    now = datetime.now(timezone.utc)
    text = "🌍 café 中文 e\u0301"
    batch = SummaryBatch(1, 1, (1,), now, now, text, 5)
    snapshot = ConversationSummarySnapshot(
        1, 1, 2, "", 0, 0, (batch,), frozenset({1}), ()
    )
    monkeypatch.setattr(
        runtime.db,
        "get_conversation_summary_snapshot",
        AsyncMock(return_value=snapshot),
    )
    current = Message(
        id=2,
        user_id=1,
        role=MessageRole.user,
        content="hello",
        created_at=now,
        is_present_in_conversation=True,
    )
    with pytest.raises(runtime.SummaryError, match="batch count"):
        await runtime.conversation_summary_service.prepare(1, (current,))
