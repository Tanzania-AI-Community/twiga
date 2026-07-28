"""Headless full evaluation — Retrieval + Generation (all subjects, full set)
+ Abstention + Lexical. Saves one comparable run, exactly like the Run page.

Launched detached by the app's "Start evaluation" button (so a ~7h run
survives the browser tab and the Streamlit server), or manually:

    uv run python scripts/run_full_eval.py --label my-baseline

Progress is written to data/results/active_run.json every few items; the Run
page reads it to show a live progress panel. On success the file is removed;
on failure it stays with state="failed" and the error message.
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Quiet per-request library DEBUG logging — otherwise a ~7h / thousands-of-calls
# run writes a multi-GB log and risks filling the disk.
logging.basicConfig(level=logging.INFO)
for noisy in ("httpcore", "httpx", "together", "asyncio", "openai", "urllib3", "asyncpg"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

import pandas as pd
from dotenv import load_dotenv

from eval.abstention import run_abstention_eval
from eval.app.runs_index import append_run
from eval.db import ReconnectingConnection
from eval.deepeval_runner import (
    ESCALATION_JUDGE_MODEL,
    GEN_JUDGE_MODEL,
    GEN_MODEL,
    GOLDEN_DIR,
    OpenRouterJudgeLLM,
    QUESTIONS_DIR,
    RETRIEVAL_JUDGE_MODEL,
    SUBJECTS,
    run_generation_eval,
    run_retrieval_eval,
)
from eval.metrics.lexical import LexicalMetrics
from eval.results import compute_headline, save_results, summarize_errors
from eval.twiga_config import GEN_TEMPERATURE, IMPORTED_FROM_TWIGA, RETRIEVAL_TOP_K

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--label", default=os.environ.get("EVAL_LABEL", ""))
parser.add_argument(
    "--generate-only", action="store_true",
    help="Run generation only (retrieval+answer, writing to the generation "
    "cache) and skip all judge/metric calls. No run is saved — this just "
    "warms the cache so a later real run can skip straight to judging "
    "instead of re-paying for generation on every retry.",
)
parser.add_argument(
    "--concurrency", type=int, default=8,
    help="Rows processed in flight at once per phase (default 8). Judging is "
    "the bottleneck (Kimi via OpenRouter), not local compute, so this is "
    "safe to raise unless it trips a provider rate limit.",
)
args = parser.parse_args()

load_dotenv(_REPO_ROOT / ".env")
EMBED_API_KEY = os.environ["EVAL_EMBED_API_KEY"]
JUDGE_API_KEY = os.environ["EVAL_JUDGE_API_KEY"]
DB_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
TIMEOUT = 300.0
LABEL = args.label.strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
GENERATE_ONLY = args.generate_only
CONCURRENCY = args.concurrency

_RESULTS_DIR = _REPO_ROOT / "eval" / "data" / "results"
_STATUS_PATH = _RESULTS_DIR / "active_run.json"
_RETRIEVAL_CSV = GOLDEN_DIR / "retrieval_golden.csv"
_ABSTENTION_CSV = GOLDEN_DIR / "abstention_questions.csv"

RUN_ID = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
_CKPT_DIR = _RESULTS_DIR / RUN_ID
_CKPT_DIR.mkdir(parents=True, exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


# ── status file the Run page polls ───────────────────────────────────────────
t0 = time.time()
done = 0
phase = ""
total_steps = 0


def write_status(state: str, **extra) -> None:
    payload = {
        "run_id": RUN_ID, "label": LABEL, "pid": os.getpid(),
        "state": state, "phase": phase, "done": done, "total": total_steps,
        "started_at": t0, "log_path": os.environ.get("EVAL_LOG_PATH", ""),
        **extra,
    }
    try:
        _STATUS_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


# ── load the full question sets ─────────────────────────────────────────────
gen_rows: list[dict] = []
for s in SUBJECTS:
    p = QUESTIONS_DIR / f"{s}_questions.csv"
    if p.exists():
        df = pd.read_csv(p)
        df = df[df["reference_answer"].notna() & (df["reference_answer"].astype(str).str.strip() != "")]
        gen_rows.extend(df.to_dict("records"))
ret_rows = pd.read_csv(_RETRIEVAL_CSV).to_dict("records") if _RETRIEVAL_CSV.exists() else []
abst_rows = pd.read_csv(_ABSTENTION_CSV).to_dict("records") if _ABSTENTION_CSV.exists() else []

total_steps = len(ret_rows) + len(gen_rows) + len(abst_rows)
print(f"[{LABEL}] retrieval={len(ret_rows)} generation={len(gen_rows)} abstention={len(abst_rows)} "
      f"= {total_steps} items", flush=True)
print(f"gen_model={GEN_MODEL} temp={GEN_TEMPERATURE} top_k={RETRIEVAL_TOP_K} "
      f"from_config={IMPORTED_FROM_TWIGA}", flush=True)
write_status("running")

gen_judge = OpenRouterJudgeLLM(model=GEN_JUDGE_MODEL, api_key=JUDGE_API_KEY, timeout=TIMEOUT)
ret_judge = OpenRouterJudgeLLM(model=RETRIEVAL_JUDGE_MODEL, api_key=JUDGE_API_KEY, timeout=TIMEOUT)
esc_judge = OpenRouterJudgeLLM(model=ESCALATION_JUDGE_MODEL, api_key=JUDGE_API_KEY, timeout=TIMEOUT * 3)

all_results: list[dict] = []


def progress(_c, _t):
    global done
    done += 1
    if done % 10 == 0 or done == total_steps:
        el = time.time() - t0
        print(f"  [{phase}] {done}/{total_steps}  ({el/60:.0f} min elapsed)", flush=True)
        write_status("running")


def update(row):
    all_results.append(row)
    # checkpoint so a crash late in a ~7h run doesn't lose everything
    if len(all_results) % 25 == 0:
        try:
            pd.DataFrame(all_results).to_csv(_CKPT_DIR / "checkpoint.csv", index=False)
        except Exception:
            pass


async def main():
    global phase
    conn = ReconnectingConnection(DB_URL, ssl="require")
    try:
        if ret_rows:
            phase = "retrieval"
            write_status("running")
            await run_retrieval_eval(
                rows=ret_rows, conn=conn, embed_api_key=EMBED_API_KEY, gen_api_key=JUDGE_API_KEY,
                judge_llm=ret_judge, gen_model=GEN_MODEL, top_k=RETRIEVAL_TOP_K,
                timeout_s=TIMEOUT, progress_cb=progress, update_cb=update,
                skip_judge=GENERATE_ONLY, concurrency=CONCURRENCY,
            )
        phase = "generation"
        write_status("running")
        await run_generation_eval(
            rows=gen_rows, embed_api_key=EMBED_API_KEY, gen_api_key=JUDGE_API_KEY,
            gen_model=GEN_MODEL, judge_llm=gen_judge,
            timeout_s=TIMEOUT, progress_cb=progress, update_cb=update,
            conn=conn, use_twiga=True, twiga_top_k=RETRIEVAL_TOP_K,
            escalation_judge=esc_judge, check_citations=True, audit_unsupported=True,
            skip_judge=GENERATE_ONLY, concurrency=CONCURRENCY,
        )
        if abst_rows:
            phase = "abstention"
            write_status("running")
            await run_abstention_eval(
                rows=abst_rows, conn=conn, embed_api_key=EMBED_API_KEY, gen_api_key=JUDGE_API_KEY,
                gen_model=GEN_MODEL, judge_llm=gen_judge, top_k=RETRIEVAL_TOP_K,
                timeout_s=TIMEOUT, progress_cb=progress, update_cb=update,
                skip_judge=GENERATE_ONLY, concurrency=CONCURRENCY,
            )
    finally:
        await conn.close()


try:
    asyncio.run(main())

    if GENERATE_ONLY:
        (_CKPT_DIR / "checkpoint.csv").unlink(missing_ok=True)
        _STATUS_PATH.unlink(missing_ok=True)
        print(
            f"\nGENERATED (no judging, no run saved) in {(time.time()-t0)/60:.0f} min — "
            f"{len(all_results)} rows written to the generation cache",
            flush=True,
        )
        sys.exit(0)

    results_df = pd.DataFrame(all_results)

    phase = "lexical"
    write_status("running")
    lex = LexicalMetrics()

    async def add_lexical():
        for idx in results_df.index:
            r = results_df.loc[idx]
            if isinstance(r.get("response"), str) and isinstance(r.get("reference_answer"), str) and r["reference_answer"]:
                try:
                    for k, v in (await lex.ascore({"response": r["response"], "reference": r["reference_answer"]})).items():
                        results_df.loc[idx, k] = v
                except Exception:
                    pass

    asyncio.run(add_lexical())

    # ── save ────────────────────────────────────────────────────────────────
    errors = summarize_errors(results_df)
    if errors:
        print("\nERRORS:", json.dumps({k: v["count"] for k, v in errors.items()}), flush=True)

    headline = compute_headline(results_df)
    commit = _git_commit()
    metadata = {
        "run_id": RUN_ID, "label": LABEL, "git_commit": commit,
        "run_type": "full",
        "dataset_used": "generation + retrieval + abstention",
        "metrics_run": "generation,retrieval,abstention,lexical",
        "pipeline": "twiga", "gen_model": GEN_MODEL, "gen_judge_model": GEN_JUDGE_MODEL,
        "retrieval_judge_model": RETRIEVAL_JUDGE_MODEL, "escalation_judge_model": ESCALATION_JUDGE_MODEL,
        "default_judge": True, "gen_temperature": GEN_TEMPERATURE,
        "twiga_settings_from_config": IMPORTED_FROM_TWIGA, "n_rows": len(results_df),
        **headline,
    }
    save_results(RUN_ID, results_df, metadata)
    append_run(
        run_id=RUN_ID, label=LABEL, git_commit=commit,
        dataset=metadata["dataset_used"], metrics_run=metadata["metrics_run"],
        headline_scores=headline, n_rows=len(results_df), run_type="full",
        pipeline="twiga", gen_model=GEN_MODEL, gen_judge_model=GEN_JUDGE_MODEL,
    )
    (_CKPT_DIR / "checkpoint.csv").unlink(missing_ok=True)
    _STATUS_PATH.unlink(missing_ok=True)
    print(f"\nDONE in {(time.time()-t0)/60:.0f} min — saved {RUN_ID} ({len(results_df)} rows)", flush=True)
    print("Headline:", json.dumps({k: round(v, 3) for k, v in headline.items()}, indent=2), flush=True)
except Exception as e:
    write_status("failed", error=f"{type(e).__name__}: {e}")
    raise
