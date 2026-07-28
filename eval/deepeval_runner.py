"""Core logic for DeepEval-based evaluation.

Part 1 — Retrieval Quality (retrieval_golden.csv):
  ContextualPrecision, ContextualRecall, ContextualRelevancy (LLM-judged)
  Recall@1/5/10, MRR, NDCG@10 (ranking metrics against golden_chunk_ids)

Part 2 — Generation Quality (subject question CSVs):
  AnswerRelevancy, Faithfulness
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any, Callable

import asyncpg
import pandas as pd
from openai import AsyncOpenAI, OpenAI

from deepeval.models import DeepEvalBaseLLM
from deepeval.metrics import (
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    AnswerRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.test_case import LLMTestCase

from eval import generation_cache
from eval.citations import score_citations
from eval.claim_audit import audit_unsupported_claims
from eval.cleaning import clean_response
from eval.twiga_runner import (
    OPENROUTER_BASE_URL,
    _embed,
    openrouter_slug,
    run_twiga_pipeline,
)

logger = logging.getLogger(__name__)

# Judge models are eval settings (the graders) — fixed here for comparability.
# Run via OpenRouter (OpenRouterJudgeLLM below) — kept on its own key so judge
# billing never competes with generation or embeddings (see EVAL_JUDGE_API_KEY,
# EVAL_EMBED_API_KEY). None of the three still touch Together/LLM_API_KEY.
RETRIEVAL_JUDGE_MODEL = "moonshotai/kimi-k2-thinking"
GEN_JUDGE_MODEL = "moonshotai/kimi-k2-thinking"
# The generation model mirrors Twiga's own config (see eval.twiga_config).
from eval.twiga_config import GEN_MODEL  # noqa: E402

# Judge models this eval has been run against, past and present (all via
# OpenRouter now — see OpenRouterJudgeLLM below). Reasoning models burn hidden
# thinking tokens before emitting content, so they need a larger completion
# budget or the judge JSON gets truncated.
JUDGE_MODELS: dict[str, dict] = {
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {"reasoning": False},
    "deepseek-ai/DeepSeek-V4-Pro": {"reasoning": True},
    "zai-org/GLM-5.2": {"reasoning": True},
    "openai/gpt-oss-120b": {"reasoning": True},
    "moonshotai/kimi-k2-thinking": {"reasoning": True},
}
# Generous so structured-output metrics that verdict a long list (Contextual
# Precision/Relevancy over 15 chunks, Contextual Recall over a long reference)
# don't truncate mid-JSON. Billing is per actual output token, so headroom is free.
DEFAULT_JUDGE_MAX_TOKENS = 8192
REASONING_JUDGE_MAX_TOKENS = 8192

# Second-pass judge for claims the primary judge marked "idk": stronger reader,
# only invoked on the few ambiguous claims so cost stays negligible.
ESCALATION_JUDGE_MODEL = "moonshotai/kimi-k2-thinking"


def judge_max_tokens(model: str) -> int:
    """Completion budget for a judge model; generous for unknown models since
    they may be reasoning models."""
    info = JUDGE_MODELS.get(model)
    if info is None or info["reasoning"]:
        return REASONING_JUDGE_MAX_TOKENS
    return DEFAULT_JUDGE_MAX_TOKENS


# Fallback only if a caller omits top_k entirely — every real caller (the app,
# scripts/run_full_eval.py, scripts/run_quick_eval.py) passes the real value
# explicitly from eval.twiga_config.RETRIEVAL_TOP_K. Deliberately named apart
# from that one so the two are never confused for each other again — a
# same-named constant here once got imported by mistake instead of the config
# value, silently scoring contextual retrieval metrics against 5 retrieved
# chunks instead of Twiga's real top_k.
_FALLBACK_TOP_K = 5
DEFAULT_TIMEOUT_S = 300.0
# Recall@10 and NDCG@10 need at least 10 ranked results regardless of how many
# chunks Top-K feeds to the LLM for context/contextual-metric scoring.
RANKING_EVAL_K = 10
# english has no question CSV in the subjects bank, so it's not listed
SUBJECTS = ["history", "geography", "biology", "agriculture"]

_REPO_ROOT = Path(__file__).parent.parent
GOLDEN_DIR = _REPO_ROOT / "eval" / "data" / "golden"
QUESTIONS_DIR = GOLDEN_DIR / "subjects"


class _ChatCompletionsJudgeLLM(DeepEvalBaseLLM):
    """Shared retry/parsing logic for judge LLMs backed by an OpenAI-compatible
    chat-completions client. Subclasses only need to construct `self._client`
    / `self._async_client`.
    """

    _model_name: str
    _max_tokens: int
    _client: Any
    _async_client: Any

    def load_model(self) -> "_ChatCompletionsJudgeLLM":
        return self

    def get_model_name(self) -> str:
        return self._model_name

    def _attempts(self, schema: Any) -> list[dict | None]:
        """Ordered response-format strategies to try until the output parses.

        Judges are intermittently bad at valid JSON for the complex contextual
        metrics, and different metrics fail under different modes. Each metric
        makes several judge calls, so one bad call fails the whole metric —
        retrying per call across strategies (json_object → json_schema →
        another json_object → free-form) drives that failure rate near zero.
        """
        if schema is None or not hasattr(schema, "model_json_schema"):
            return [None]
        return [
            {"type": "json_object"},
            {"type": "json_schema", "schema": schema.model_json_schema()},
            {"type": "json_object"},
            None,  # last resort: free-form, let DeepEval salvage it
        ]

    @staticmethod
    def _parses(content: str) -> bool:
        s = content.strip()
        if "```" in s:
            s = s.split("```")[1].removeprefix("json").strip()
        try:
            json.loads(s)
            return True
        except Exception:
            return False

    def generate(self, prompt: str, schema: Any = None, *args: Any, **kwargs: Any) -> str:
        last = ""
        for rf in self._attempts(schema):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=self._max_tokens,
                    **({"response_format": rf} if rf else {}),
                )
            except Exception:
                continue
            last = (resp.choices[0].message.content or "").strip()
            if rf is None or self._parses(last):
                return last
        return last

    async def a_generate(self, prompt: str, schema: Any = None, *args: Any, **kwargs: Any) -> str:
        # Genuinely async (and therefore actually bound by `timeout` above) —
        # previously this delegated to the blocking generate() above, which
        # meant a hung judge call could never be interrupted by a timeout since
        # nothing here ever yielded control back to the event loop.
        last = ""
        for rf in self._attempts(schema):
            try:
                resp = await self._async_client.chat.completions.create(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=self._max_tokens,
                    **({"response_format": rf} if rf else {}),
                )
            except Exception:
                continue
            last = (resp.choices[0].message.content or "").strip()
            if rf is None or self._parses(last):
                return last
        return last


class OpenRouterJudgeLLM(_ChatCompletionsJudgeLLM):
    """OpenRouter LLM adapter for DeepEval judge metrics — eval-only, kept
    independent of Twiga's own Together account (see EVAL_JUDGE_API_KEY)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_tokens: int | None = None,
    ):
        self._model_name = model
        self._max_tokens = max_tokens if max_tokens is not None else judge_max_tokens(model)
        self._client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key, timeout=timeout)
        self._async_client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key, timeout=timeout)
        super().__init__(model)


async def _get_resource_id(conn: asyncpg.Connection, chunk_id: int) -> int:
    row = await conn.fetchrow("SELECT resource_id FROM chunks WHERE id = $1", chunk_id)
    return int(row["resource_id"])


def _retrieval_ranking_metrics(golden_ids: list[int], retrieved_ids: list[int]) -> dict[str, float]:
    """Recall@1/5/10, MRR, and NDCG@10 for one query.

    Binary relevance: a retrieved chunk is relevant iff its id is in golden_ids.
    `retrieved_ids` must already be ordered by rank (closest match first).
    """
    golden_set = set(golden_ids)

    def recall_at(k: int) -> float:
        if not golden_set:
            return 0.0
        hits = len(set(retrieved_ids[:k]) & golden_set)
        return hits / len(golden_set)

    reciprocal_rank = 0.0
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in golden_set:
            reciprocal_rank = 1.0 / rank
            break

    k = min(RANKING_EVAL_K, len(retrieved_ids))
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved_ids[:k], start=1)
        if chunk_id in golden_set
    )
    ideal_hits = min(len(golden_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

    return {
        "recall_at_1": recall_at(1),
        "recall_at_5": recall_at(5),
        "recall_at_10": recall_at(10),
        "mrr": reciprocal_rank,
        "ndcg_at_10": (dcg / idcg) if idcg > 0 else 0.0,
    }


async def _vector_search(
    conn: asyncpg.Connection,
    embedding: list[float],
    resource_id: int,
    top_k: int,
) -> list[tuple[int, str]]:
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    rows = await conn.fetch(
        """
        SELECT c.id, c.content
        FROM chunks c
        WHERE c.resource_id = $1 AND c.chunk_type = 'text'
        ORDER BY c.embedding <=> $2::vector
        LIMIT $3
        """,
        resource_id,
        emb_str,
        top_k,
    )
    return [(int(r["id"]), r["content"]) for r in rows]


async def _generate_response(
    client: Any, model: str, question: str, chunks: list[str]
) -> str:
    context = "\n\n".join(f"[Passage {i + 1}]\n{c}" for i, c in enumerate(chunks))
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a knowledgeable teacher answering curriculum questions "
                    "for Tanzanian secondary school students. Answer using ONLY the "
                    "provided textbook passages. Write in clear, plain prose."
                ),
            },
            {
                "role": "user",
                "content": f"Textbook content:\n{context}\n\nQuestion: {question}",
            },
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return (resp.choices[0].message.content or "").strip()


async def run_retrieval_eval(
    rows: list[dict],
    conn: asyncpg.Connection,
    embed_api_key: str,
    gen_api_key: str,
    judge_llm: OpenRouterJudgeLLM,
    gen_model: str = GEN_MODEL,
    top_k: int = _FALLBACK_TOP_K,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    progress_cb: Callable[[int, int], None] | None = None,
    update_cb: Callable[[dict], None] | None = None,
    judge_metrics: bool = True,
    skip_judge: bool = False,
    concurrency: int = 8,
) -> pd.DataFrame:
    """Part 1: Retrieval quality — ContextualPrecision, Recall, Relevancy.

    With judge_metrics=False only the local ranking metrics (Recall@k, MRR,
    NDCG) are computed — no answer generation and no judge calls — which is
    what quick runs use (so gen_api_key goes unused there).

    `embed_api_key` (DeepInfra) embeds the retrieval golden queries;
    `gen_api_key` (OpenRouter) generates the answer the contextual judge
    metrics score.

    skip_judge=True (only meaningful with judge_metrics=True) still generates
    and caches the answer — see eval/generation_cache.py — but skips the
    judge calls, for a cache-warming pass ahead of a real scored run.

    Rows are processed with up to `concurrency` in flight at once. Each row
    builds its own fresh ContextualPrecision/Recall/Relevancy metric objects
    rather than sharing one across rows — a_measure() writes score/reason
    onto `self`, so sharing would let concurrent rows clobber each other.
    """
    gen_client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=gen_api_key, timeout=timeout_s)
    _metric_names = {
        "ContextualPrecisionMetric": "contextual_precision",
        "ContextualRecallMetric": "contextual_recall",
        "ContextualRelevancyMetric": "contextual_relevancy",
    }

    def _make_metrics() -> list[Any]:
        return [
            ContextualPrecisionMetric(model=judge_llm, threshold=0.5, verbose_mode=False),
            ContextualRecallMetric(model=judge_llm, threshold=0.5, verbose_mode=False),
            ContextualRelevancyMetric(model=judge_llm, threshold=0.5, verbose_mode=False),
        ] if judge_metrics else []

    gen_fingerprint = generation_cache.retrieval_eval_fingerprint(gen_model)
    gen_cache_hits = generation_cache.HitCounter()
    sem = asyncio.Semaphore(concurrency)

    async def _process(i: int, row: dict) -> dict:
        result: dict = {
            "user_query": row["user_query"],
            "golden_chunk_ids": row.get("golden_chunk_ids", ""),
            "chapter": row.get("chapter", ""),
            "query_style": row.get("query_style", ""),
        }
        metrics = _make_metrics()

        async with sem:
            try:
                golden_ids = [int(i) for i in json.loads(row["golden_chunk_ids"])]
                seed_id = golden_ids[0]

                resource_id = await _get_resource_id(conn, seed_id)
                embedding = await _embed(embed_api_key, row["user_query"], timeout_s)
                # Fetch enough for Recall@10/NDCG@10 even if Top-K (context size) is smaller.
                fetch_k = max(top_k, RANKING_EVAL_K)
                retrieved = await _vector_search(conn, embedding, resource_id, fetch_k)

                retrieved_ids_ranked = [r[0] for r in retrieved]
                retrieved_ids = retrieved_ids_ranked[:top_k]
                retrieval_context = [r[1] for r in retrieved[:top_k]]

                # hit if any of the golden chunks is in the top-K results
                result["hit_at_k"] = int(bool(set(golden_ids) & set(retrieved_ids)))
                result["retrieved_ids"] = json.dumps(retrieved_ids)
                result.update(_retrieval_ranking_metrics(golden_ids, retrieved_ids_ranked))

                if judge_metrics:
                    gen_cache_key = generation_cache.make_key(
                        gen_fingerprint, row["user_query"], *retrieval_context
                    )
                    cached_output = generation_cache.get(gen_cache_key)
                    if cached_output is not None:
                        gen_cache_hits.hit()
                        actual_output = cached_output["response"]
                    else:
                        gen_cache_hits.miss()
                        actual_output = await _generate_response(
                            gen_client, openrouter_slug(gen_model), row["user_query"], retrieval_context
                        )
                        generation_cache.put(gen_cache_key, {"response": actual_output})

                    result["response"] = actual_output

                    test_case = LLMTestCase(
                        input=row["user_query"],
                        actual_output=actual_output,
                        expected_output=row.get("reference_answer", ""),
                        retrieval_context=retrieval_context,
                    )

                for metric in (metrics if not skip_judge else []):
                    col = _metric_names[metric.__class__.__name__]
                    try:
                        await metric.a_measure(test_case)
                        err = getattr(metric, "error", None)
                        if err:
                            result[col] = None
                            result[f"{col}_error"] = str(err)
                            logger.warning("Metric %s row %d internal error: %s", col, i, err)
                        else:
                            result[col] = metric.score
                            result[f"{col}_reason"] = getattr(metric, "reason", "")
                    except Exception as e:
                        result[col] = None
                        result[f"{col}_error"] = str(e)
                        logger.warning("Metric %s failed row %d: %s", col, i, e)

            except Exception as e:
                result["error"] = str(e)
                logger.error("Retrieval eval row %d failed: %s", i, e)

        return result

    results: list[dict] = []
    total = len(rows)
    tasks = [asyncio.create_task(_process(i, row)) for i, row in enumerate(rows)]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        if progress_cb:
            progress_cb(len(results), total)
        if update_cb:
            update_cb(result)

    gen_cache_hits.log("retrieval_eval")
    return pd.DataFrame(results)


def _faithfulness_breakdown(metric: FaithfulnessMetric) -> dict[str, Any]:
    """Per-claim verdicts from a measured FaithfulnessMetric.

    DeepEval decomposes the answer into claims and verdicts them against the
    retrieval context ("yes" = supported, "no" = contradicted, "idk" =
    unverifiable); verdicts align with claims by index. The aggregate score
    hides this — persist it so each fact in the output is auditable.
    """
    claims = list(getattr(metric, "claims", None) or [])
    verdicts = list(getattr(metric, "verdicts", None) or [])
    items = []
    for j, v in enumerate(verdicts):
        verdict = str(getattr(v, "verdict", "")).strip().lower()
        items.append(
            {
                "claim": claims[j] if j < len(claims) else "",
                "verdict": verdict,
                "reason": getattr(v, "reason", None) or "",
            }
        )
    supported = sum(1 for it in items if it["verdict"] == "yes")
    contradicted = sum(1 for it in items if it["verdict"] == "no")
    return {
        "claim_verdicts": json.dumps(items, ensure_ascii=False),
        "claims_supported": supported,
        "claims_contradicted": contradicted,
        "claims_total": len(items),
    }


_ESCALATION_PROMPT = (
    "You are verifying whether a single claim is supported by textbook context.\n\n"
    "Textbook context:\n{context}\n\n"
    "Claim: {claim}\n\n"
    'Answer "yes" if the claim is stated in, or can be directly inferred from, '
    'the context. Answer "no" if it is absent from or contradicted by the '
    "context. You must choose one — do not hedge.\n"
    'Reply with ONLY this JSON and no other text: '
    '{{"verdict": "yes" or "no", "reason": "<one short sentence>"}}'
)


async def _escalate_ambiguous_claims(
    breakdown: dict[str, Any],
    context_chunks: list[str],
    judge: OpenRouterJudgeLLM,
) -> dict[str, Any]:
    """Re-verdict "idk" claims with a stronger judge, forced binary.

    Overwrites each resolved claim's verdict (keeping the original under
    "original_verdict") and recomputes the counts. Claims the escalation
    judge fails on stay "idk".
    """
    items = json.loads(breakdown["claim_verdicts"])
    idk_indices = [i for i, it in enumerate(items) if it["verdict"] == "idk"]
    if not idk_indices:
        return breakdown

    context = "\n\n".join(context_chunks)
    escalated = 0
    for i in idk_indices:
        prompt = _ESCALATION_PROMPT.format(context=context, claim=items[i]["claim"])
        try:
            raw = (await judge.a_generate(prompt)).strip()
            if "```" in raw:
                raw = raw.split("```")[1].removeprefix("json").strip()
            data = json.loads(raw)
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict in ("yes", "no"):
                items[i]["original_verdict"] = "idk"
                items[i]["verdict"] = verdict
                items[i]["escalation_reason"] = str(data.get("reason", ""))
                escalated += 1
        except Exception as e:
            logger.warning("Escalation failed for claim %r: %s", items[i]["claim"][:60], e)

    supported = sum(1 for it in items if it["verdict"] == "yes")
    contradicted = sum(1 for it in items if it["verdict"] == "no")
    return {
        "claim_verdicts": json.dumps(items, ensure_ascii=False),
        "claims_supported": supported,
        "claims_contradicted": contradicted,
        "claims_total": len(items),
        "claims_escalated": escalated,
    }


async def run_generation_eval(
    rows: list[dict],
    embed_api_key: str,
    gen_api_key: str,
    gen_model: str,
    judge_llm: OpenRouterJudgeLLM,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    progress_cb: Callable[[int, int], None] | None = None,
    update_cb: Callable[[dict], None] | None = None,
    conn: asyncpg.Connection | None = None,
    use_twiga: bool = False,
    twiga_top_k: int = 15,
    escalation_judge: OpenRouterJudgeLLM | None = None,
    check_citations: bool = True,
    audit_unsupported: bool = True,
    include_relevancy: bool = True,
    skip_judge: bool = False,
    concurrency: int = 8,
) -> pd.DataFrame:
    """Part 2: Generation quality — AnswerRelevancy, Faithfulness.

    With use_twiga=True (requires conn), answers come from Twiga's real
    pipeline — live vector retrieval against the class textbook plus Twiga's
    actual system prompt — so the judge metrics score the real system instead
    of a generic prompt over the CSV's pre-retrieved chunks.

    `embed_api_key` (DeepInfra) embeds the question when use_twiga=True;
    `gen_api_key` (OpenRouter) generates the answer either way.

    skip_judge=True runs generation only (writing to the generation cache —
    see eval/generation_cache.py) and returns before any judge/citation call,
    so a cache-warming pass can populate answers cheaply before a second pass
    scores them — a failed/retried judge pass then never re-pays for
    generation.

    Rows are processed with up to `concurrency` in flight at once. Metric
    objects are stateful (a_measure() writes score/reason/claims/etc. onto
    `self`), so each row builds its own fresh metrics rather than sharing one
    instance — reusing one across concurrent rows would let two rows'
    results race and silently clobber each other.
    """
    if use_twiga and conn is None:
        raise ValueError("use_twiga=True requires a database connection")
    gen_client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=gen_api_key, timeout=timeout_s)
    _metric_names = {
        "AnswerRelevancyMetric": "answer_relevancy",
        "FaithfulnessMetric": "faithfulness",
    }

    def _make_metrics() -> list[Any]:
        return [
            *([AnswerRelevancyMetric(model=judge_llm, threshold=0.5, verbose_mode=False)]
              if include_relevancy else []),
            # penalize_ambiguous_claims: an "idk" (unverifiable) claim counts against
            # the score, so the metric reduces to supported_claims / total_claims —
            # a fact the textbook can't back is a failure even if not contradicted.
            # Also makes the score robust to judges that label fabrications "idk"
            # instead of "no" (observed with DeepSeek-V4-Pro).
            FaithfulnessMetric(
                model=judge_llm,
                threshold=0.5,
                verbose_mode=False,
                penalize_ambiguous_claims=True,
            ),
        ]

    gen_fingerprint = generation_cache.retrieval_eval_fingerprint(gen_model)
    gen_cache_hits = generation_cache.HitCounter()
    sem = asyncio.Semaphore(concurrency)

    async def _process(i: int, row: dict) -> dict:
        result: dict = {
            "user_query": row.get("question", ""),
            "subject": row.get("subject", ""),
            "grade_level": row.get("grade_level", ""),
            "reference_answer": row.get("reference_answer", ""),
        }
        resource_ids: list[int] = []
        metrics = _make_metrics()

        async with sem:
            try:
                if use_twiga:
                    pipeline_out = (
                        await run_twiga_pipeline(
                            [row],
                            conn=conn,
                            embed_api_key=embed_api_key,
                            gen_api_key=gen_api_key,
                            gen_model=gen_model,
                            top_k=twiga_top_k,
                            timeout_s=timeout_s,
                        )
                    )[0]
                    if pipeline_out.get("error"):
                        raise RuntimeError(str(pipeline_out["error"]))
                    response = str(pipeline_out.get("response", ""))
                    chunk_contents = json.loads(pipeline_out["retrieved_chunk_contents"])
                    result["retrieved_chunk_ids"] = pipeline_out.get("retrieved_chunk_ids", "")
                    resource_ids = json.loads(pipeline_out.get("resource_ids", "[]"))

                    if not skip_judge and check_citations and pipeline_out.get("response_with_citations"):
                        chunk_ids = json.loads(pipeline_out["retrieved_chunk_ids"])
                        try:
                            result.update(
                                await score_citations(
                                    pipeline_out["response_with_citations"],
                                    dict(zip(chunk_ids, chunk_contents)),
                                    judge_llm,
                                )
                            )
                        except Exception as e:
                            result["citations_error"] = str(e)
                            logger.warning("Citation scoring failed row %d: %s", i, e)
                else:
                    chunk_contents = json.loads(row["chunk_contents"])
                    gen_cache_key = generation_cache.make_key(
                        gen_fingerprint, row["question"], *chunk_contents
                    )
                    cached_output = generation_cache.get(gen_cache_key)
                    if cached_output is not None:
                        gen_cache_hits.hit()
                        response = cached_output["response"]
                    else:
                        gen_cache_hits.miss()
                        response = await _generate_response(
                            gen_client, openrouter_slug(gen_model), row["question"], chunk_contents
                        )
                        generation_cache.put(gen_cache_key, {"response": response})

                # Judge only the factual substance: greetings, teaching tips, and
                # follow-up questions would otherwise be extracted as claims and
                # verdicted against the textbook. Keep the raw text for auditing.
                cleaned = clean_response(response) or response
                result["response"] = cleaned
                if cleaned != response:
                    result["response_raw"] = response

                if skip_judge:
                    return result

                test_case = LLMTestCase(
                    input=row["question"],
                    actual_output=cleaned,
                    expected_output=row.get("reference_answer", ""),
                    retrieval_context=chunk_contents,
                )

                for metric in metrics:
                    col = _metric_names[metric.__class__.__name__]
                    try:
                        await metric.a_measure(test_case)
                        err = getattr(metric, "error", None)
                        if err:
                            result[col] = None
                            result[f"{col}_error"] = str(err)
                            logger.warning("Metric %s row %d internal error: %s", col, i, err)
                        else:
                            result[col] = metric.score
                            result[f"{col}_reason"] = getattr(metric, "reason", "")
                            if isinstance(metric, FaithfulnessMetric):
                                breakdown = _faithfulness_breakdown(metric)
                                if escalation_judge is not None:
                                    breakdown = await _escalate_ambiguous_claims(
                                        breakdown, chunk_contents, escalation_judge
                                    )
                                    if breakdown.get("claims_escalated") and breakdown["claims_total"]:
                                        # score stays supported/total (penalized
                                        # semantics), now with escalated verdicts
                                        result[f"{col}_pre_escalation"] = result[col]
                                        result[col] = (
                                            breakdown["claims_supported"] / breakdown["claims_total"]
                                        )
                                if (
                                    audit_unsupported
                                    and resource_ids
                                    and conn is not None
                                    and breakdown["claims_total"] > breakdown["claims_supported"]
                                ):
                                    breakdown = await audit_unsupported_claims(
                                        breakdown,
                                        resource_ids,
                                        conn,
                                        embed_api_key,
                                        judge_llm,
                                        timeout_s=timeout_s,
                                    )
                                result.update(breakdown)
                    except Exception as e:
                        result[col] = None
                        result[f"{col}_error"] = str(e)
                        logger.warning("Metric %s failed row %d: %s", col, i, e)

            except Exception as e:
                result["error"] = str(e)
                logger.error("Generation eval row %d failed: %s", i, e)

        return result

    results: list[dict] = []
    total = len(rows)
    tasks = [asyncio.create_task(_process(i, row)) for i, row in enumerate(rows)]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        if progress_cb:
            progress_cb(len(results), total)
        if update_cb:
            update_cb(result)

    gen_cache_hits.log("generation_eval")
    return pd.DataFrame(results)
