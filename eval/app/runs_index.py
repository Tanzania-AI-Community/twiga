import contextlib
import fcntl
import os
import shutil
from pathlib import Path

import pandas as pd

_RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
_RUNS_CSV = _RESULTS_DIR / "runs.csv"
_LOCK_PATH = _RESULTS_DIR / ".runs_csv.lock"


@contextlib.contextmanager
def _locked():
    """Exclusive lock around a runs.csv read-modify-write. Without this, two
    processes appending/deleting near-simultaneously (e.g. a manually
    launched scripts/*.py run finishing alongside the app) can race and one
    write silently clobbers the other."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

_COLUMNS = [
    "run_id", "timestamp", "label", "git_commit", "dataset_used",
    "metrics_run", "n_rows", "run_type", "pipeline", "gen_model", "gen_judge_model",
    "recall_at_1", "recall_at_5", "recall_at_10",
    "mrr", "ndcg_at_10", "rouge_1", "rouge_2", "rouge_l", "bleu",
    "faithfulness", "answer_relevancy", "deepeval_contextual_precision",
    "deepeval_contextual_recall", "deepeval_contextual_relevancy",
    "claim_grounded_ratio", "hallucination_rate", "retrieval_miss_rate",
    "citation_precision", "citation_coverage", "abstention_rate",
    "run_dir",
]


def _empty_index() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write-then-rename so a concurrent reader never sees a half-written
    file (pandas.to_csv isn't atomic on its own)."""
    tmp_path = path.with_suffix(f"{path.suffix}.tmp{os.getpid()}")
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)


def load_runs_index() -> pd.DataFrame:
    if not _RUNS_CSV.exists():
        return _empty_index()
    try:
        df = pd.read_csv(_RUNS_CSV)
        for col in _COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[_COLUMNS]
    except Exception:
        return _empty_index()


def append_run(
    run_id: str,
    label: str,
    git_commit: str,
    dataset: str,
    metrics_run: str,
    headline_scores: dict,
    n_rows: int | None = None,
    run_type: str | None = None,
    pipeline: str | None = None,
    gen_model: str | None = None,
    gen_judge_model: str | None = None,
) -> None:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone
    run_dir = str(_RESULTS_DIR / run_id)

    row: dict = {col: None for col in _COLUMNS}
    row.update({
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "git_commit": git_commit,
        "dataset_used": dataset,
        "metrics_run": metrics_run,
        "n_rows": n_rows,
        "run_type": run_type,
        "pipeline": pipeline,
        "gen_model": gen_model,
        "gen_judge_model": gen_judge_model,
        "run_dir": run_dir,
        **{k: v for k, v in headline_scores.items() if k in _COLUMNS},
    })
    new_row = pd.DataFrame([row])[_COLUMNS]

    with _locked():
        df = pd.concat([load_runs_index(), new_row], ignore_index=True)
        _atomic_write_csv(df, _RUNS_CSV)


def delete_run(run_id: str) -> None:
    with _locked():
        df = load_runs_index()
        df = df[df["run_id"] != run_id]
        _atomic_write_csv(df, _RUNS_CSV)

    run_dir = _RESULTS_DIR / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
