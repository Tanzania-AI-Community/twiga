import json
from pathlib import Path

import pandas as pd

_RESULTS_DIR = Path(__file__).parent / "data" / "results"

# results.csv column -> headline metric name
_HEADLINE_MEAN_COLS = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "contextual_precision": "deepeval_contextual_precision",
    "contextual_recall": "deepeval_contextual_recall",
    "contextual_relevancy": "deepeval_contextual_relevancy",
    "recall_at_1": "recall_at_1",
    "recall_at_5": "recall_at_5",
    "recall_at_10": "recall_at_10",
    "mrr": "mrr",
    "ndcg_at_10": "ndcg_at_10",
    "rouge_1": "rouge_1",
    "rouge_2": "rouge_2",
    "rouge_l": "rouge_l",
    "bleu": "bleu",
    "citation_precision": "citation_precision",
    "citation_coverage": "citation_coverage",
    "abstention_ok": "abstention_rate",
}


def compute_headline(results_df: pd.DataFrame) -> dict[str, float]:
    """Aggregate per-row scores into the run's headline metrics.

    The one place headline semantics live — used when saving a run and when
    rendering it, so the two can't drift.
    """
    out: dict[str, float] = {}
    for src, dst in _HEADLINE_MEAN_COLS.items():
        if src in results_df.columns:
            vals = results_df[src].dropna()
            if not vals.empty:
                out[dst] = float(vals.mean())

    if "claims_total" in results_df.columns:
        total = results_df["claims_total"].dropna().sum()
        if total:
            for src, dst in [
                ("claims_supported", "claim_grounded_ratio"),
                ("claims_hallucinated", "hallucination_rate"),
                ("claims_retrieval_miss", "retrieval_miss_rate"),
            ]:
                if src in results_df.columns:
                    out[dst] = float(results_df[src].dropna().sum() / total)
    return out


def save_results(
    run_id: str,
    results_df: pd.DataFrame,
    metadata: dict,
) -> Path:
    run_dir = _RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results_df.to_csv(run_dir / "results.csv", index=False)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )
    return run_dir


def load_results(run_id: str) -> tuple[pd.DataFrame, dict]:
    run_dir = _RESULTS_DIR / run_id
    results_df = pd.read_csv(run_dir / "results.csv")
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    return results_df, metadata


def list_runs() -> list[str]:
    if not _RESULTS_DIR.exists():
        return []
    return [
        p.name
        for p in sorted(_RESULTS_DIR.iterdir())
        if p.is_dir() and (p / "results.csv").exists()
    ]


def summarize_errors(results_df: pd.DataFrame) -> dict[str, dict]:
    """Collect per-row failures stashed in 'error' / '<metric>_error' columns.

    deepeval_runner.py and twiga_runner.py catch exceptions per row/metric and
    record them in a sibling error column instead of raising, so a run always
    finishes and saves — but nothing surfaces those columns to the person
    running the eval. Returns {label: {"count": n, "samples": [...]}} for every
    error column that has at least one non-empty value.
    """
    error_cols = [c for c in results_df.columns if c == "error" or c.endswith("_error")]
    summary: dict[str, dict] = {}
    for col in error_cols:
        values = results_df[col].dropna().astype(str)
        values = values[values.str.strip() != ""]
        if values.empty:
            continue
        label = "pipeline" if col == "error" else col[: -len("_error")]
        summary[label] = {
            "count": int(len(values)),
            "samples": values.unique().tolist()[:3],
        }
    return summary
