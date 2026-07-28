"""New Run page — launch an evaluation run.

Two run types, nothing else to configure (so runs stay comparable):
  Full — every suite on the full question sets: Generation (faithfulness,
         claim verdicts with escalation, citations, whole-book audit),
         Lexical (ROUGE/BLEU), Retrieval (ranking + judged context quality),
         Abstention (declines unanswerable questions?)
  Quick — smoke test: faithfulness on a fixed 100-question sample, the
          abstention set, and judge-free Recall@10 on the retrieval golds
"""

from __future__ import annotations

import asyncio
import json
import signal
import subprocess
import sys
import time
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from eval.abstention import run_abstention_eval
from eval.app.components.run_report import render_run_report
from eval.app.runs_index import append_run
from eval.db import ReconnectingConnection
from eval.deepeval_runner import (
    DEFAULT_TIMEOUT_S,
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
from eval.live_table_throttle import LiveTableThrottle
from eval.results import compute_headline, save_results
from eval.twiga_config import GEN_TEMPERATURE, IMPORTED_FROM_TWIGA, RETRIEVAL_TOP_K

_RETRIEVAL_CSV = GOLDEN_DIR / "retrieval_golden.csv"
_ABSTENTION_CSV = GOLDEN_DIR / "abstention_questions.csv"
_QUICK_CSV = GOLDEN_DIR / "quick_run_questions.csv"

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_RESULTS_DIR = _REPO_ROOT / "eval" / "data" / "results"
_STATUS_PATH = _RESULTS_DIR / "active_run.json"
_FULL_RUN_SCRIPT = _REPO_ROOT / "scripts" / "run_full_eval.py"


def _read_status() -> dict | None:
    try:
        return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_is_our_run(pid: int) -> bool:
    """True if pid is alive AND looks like one of our eval scripts.

    A bare liveness check (os.kill(pid, 0)) can't tell a live eval process
    apart from some unrelated process that reused the same pid after the real
    one died without cleaning up its status file — on a long-lived shared
    machine that's not just theoretical. Cross-checking /proc/<pid>/cmdline
    closes that gap; if we can't read it (e.g. not Linux), fall back to the
    liveness check alone rather than block on this.
    """
    try:
        os.kill(pid, 0)
    except (OSError, ValueError, TypeError):
        return False
    try:
        # argv entries, not the raw joined string — a substring search over
        # the whole cmdline would false-positive on, say, a --label value or
        # a `python -c "..."` script that happens to mention the filename.
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\x00")
    except OSError:
        return True
    return any(a.endswith((b"run_full_eval.py", b"run_quick_eval.py")) for a in args)


def _active_status() -> dict | None:
    """Current background full run, with a liveness check on its pid."""
    s = _read_status()
    if not s:
        return None
    if s.get("state") == "running":
        try:
            pid = int(s["pid"])
        except (ValueError, TypeError):
            s["state"] = "crashed"
        else:
            if not _pid_is_our_run(pid):
                s["state"] = "crashed"
    return s


def _launch_full_run(label: str) -> None:
    """Start the headless full evaluation as a detached process — it survives
    this tab and even a Streamlit restart. Progress lands in active_run.json."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _RESULTS_DIR / f"full_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.log"
    env = {**os.environ, "EVAL_LOG_PATH": str(log_path)}
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            [sys.executable, str(_FULL_RUN_SCRIPT), "--label", label],
            cwd=str(_REPO_ROOT), env=env,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # provisional status so the page shows the panel (and blocks double-starts)
    # immediately; the runner overwrites it with real progress
    _STATUS_PATH.write_text(json.dumps({
        "run_id": "", "label": label, "pid": proc.pid, "state": "running",
        "phase": "starting", "done": 0, "total": 0, "started_at": time.time(),
        "log_path": str(log_path),
    }), encoding="utf-8")


def _render_active_run(status: dict) -> None:
    st.subheader("Full evaluation in progress")
    state = status.get("state")

    if state in ("crashed", "failed"):
        detail = status.get("error", "the process is no longer running")
        st.error(
            f"The background run **{status.get('label') or ''}** stopped without saving: {detail}."
            + (f"  Log: `{status.get('log_path')}`" if status.get("log_path") else "")
        )
        if st.button("Dismiss and allow a new run"):
            _STATUS_PATH.unlink(missing_ok=True)
            st.rerun()
        return

    @st.fragment(run_every="10s")
    def _panel() -> None:
        s = _active_status()
        if not s or s.get("state") != "running":
            st.rerun(scope="app")  # finished (file gone) or failed — redraw page
            return
        done, total = int(s.get("done") or 0), int(s.get("total") or 0)
        st.progress(min(done / total, 1.0) if total else 0.0,
                    text=f"{s.get('phase', 'starting')} — {done}/{total or '?'} items")
        elapsed = time.time() - float(s.get("started_at") or time.time())
        eta = ""
        if done and total:
            left = elapsed / done * (total - done)
            eta = f" · roughly {left / 3600:.1f} h left" if left > 5400 else f" · roughly {left / 60:.0f} min left"
        st.caption(f"**{s.get('label') or 'full evaluation'}** · {elapsed / 60:.0f} min elapsed{eta}")

    _panel()
    st.caption(
        "Running **in the background** — closing this tab or restarting the app won't stop it. "
        "The run appears on the **📊 Runs** tab and the Overview when it finishes."
    )
    with st.expander("Stop this run"):
        st.warning("Stops the background process. Nothing is saved as a run — only the raw checkpoint file remains.")
        if st.button("Stop the run", type="primary"):
            try:
                os.killpg(int(status["pid"]), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(int(status["pid"]), signal.SIGTERM)
                except Exception:
                    pass
            _STATUS_PATH.unlink(missing_ok=True)
            st.rerun()

_LIVE_COLS = ["user_query", "subject", "response", "faithfulness", "answer_relevancy", "abstention_verdict"]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).parent.parent.parent.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _row_count(path: Path) -> int:
    try:
        return len(pd.read_csv(path)) if path.exists() else 0
    except Exception:
        return 0


def _clean_count(subject: str) -> int:
    """Questions with a usable reference answer for a subject."""
    p = QUESTIONS_DIR / f"{subject}_questions.csv"
    if not p.exists():
        return 0
    try:
        df = pd.read_csv(p)
        return int((df["reference_answer"].notna() & (df["reference_answer"].astype(str).str.strip() != "")).sum())
    except Exception:
        return 0


def _estimate_minutes(gen_n: int, ret_n: int, abst_n: int, quick: bool = False) -> int:
    """Rough wall-clock estimate. Generation is the slow suite (full pipeline
    + judge + escalation + audit); retrieval and abstention are lighter. Quick
    runs skip relevancy/escalation/audit/citations and all retrieval judging."""
    if quick:
        seconds = gen_n * 20 + ret_n * 3 + abst_n * 40
    else:
        seconds = gen_n * 45 + ret_n * 12 + abst_n * 40
    return max(1, round(seconds / 60))


def render():
    load_dotenv()
    st.title("Run evaluation")

    active = _active_status()
    if active:
        _render_active_run(active)
        return

    quick = st.radio(
        "Run type",
        ["Full evaluation", "⚡ Quick run"],
        horizontal=True, key="nr_type",
        help="A quick run is a fast smoke check on a fixed 100-question sample "
        "(25 per subject) scoring only faithfulness, abstention and Recall@10. "
        "Full runs use every question and every metric.",
    ) == "⚡ Quick run"
    if quick:
        st.caption(
            "A fast smoke check: **faithfulness** on a fixed 100-question sample "
            "(25 per subject), the **abstention** set, and **Recall@10** on the golden "
            "retrieval queries. Skips relevancy, citations, hallucination audit and the "
            "judged retrieval metrics, so it's quick and cheap. Quick runs get their own "
            "section on the Overview — they never move the full-baseline headline."
        )
    else:
        st.caption(
            "Runs the **complete** test suite on the full question sets — nothing to "
            "pick, so every full run is directly comparable on the Overview and Runs tabs."
        )

    embed_api_key = os.environ.get("EVAL_EMBED_API_KEY", "")
    judge_api_key = os.environ.get("EVAL_JUDGE_API_KEY", "")
    # Generation prefers Together (production's real provider) when it has a
    # key configured, falling back to OpenRouter (judge_api_key) otherwise —
    # see eval.twiga_runner.resolve_gen_client.
    together_api_key = os.environ.get("LLM_API_KEY") or None
    db_url = os.environ.get("DATABASE_URL", "")
    if not embed_api_key:
        st.error("EVAL_EMBED_API_KEY is not set in your environment / .env — can't reach the embedder (DeepInfra).")
        return
    if not judge_api_key:
        st.error("EVAL_JUDGE_API_KEY is not set in your environment / .env — can't reach the judge (OpenRouter).")
        return
    if not db_url:
        st.error("DATABASE_URL is not set in your environment / .env — can't reach the textbook database.")
        return

    ret_count = _row_count(_RETRIEVAL_CSV)
    abst_count = _row_count(_ABSTENTION_CSV)
    quick_count = _row_count(_QUICK_CSV)

    selected_subjects: list[str] = []

    if quick:
        # ── Step 1: what a quick run tests (fixed) ──────────────────────────────
        st.subheader("1 · What a quick run tests")
        if quick_count == 0:
            st.error(
                "No quick-run question set found at eval/data/golden/quick_run_questions.csv."
            )
            return
        run_generation = True
        run_lexical = False
        run_retrieval = ret_count > 0
        run_abstention = abst_count > 0
        with st.container(border=True):
            st.markdown(
                f"- 📝  **Faithfulness** — {quick_count} questions, an equal random sample "
                "from each subject (a fixed set, so quick runs stay comparable to each other)\n"
                f"- 🚫  **Abstention** — all {abst_count} unanswerable questions\n"
                f"- 🔍  **Recall@10** — all {ret_count} golden retrieval queries, ranking only "
                "(no judge calls)"
            )
    else:
        # ── Step 1: what a full evaluation tests (fixed — no picking) ───────────
        st.subheader("1 · What a full evaluation tests")
        run_generation = True
        run_lexical = True
        run_retrieval = ret_count > 0
        run_abstention = abst_count > 0
        selected_subjects = SUBJECTS
        counts = {s: _clean_count(s) for s in SUBJECTS}
        planned = sum(counts.values())
        with st.container(border=True):
            st.markdown(
                f"- 📝  **Generation** — {planned} curriculum questions "
                f"({'  ·  '.join(f'{s} {n}' for s, n in counts.items())}): faithfulness, "
                "claim grounding, citations, hallucination audit\n"
                "- 🔤  **Lexical** — ROUGE/BLEU of those answers vs. the reference answers\n"
                + (f"- 🔍  **Retrieval** — {ret_count} golden queries: Recall@k, MRR, NDCG "
                   "plus judged context quality, across all four phrasing styles\n" if ret_count
                   else "- 🔍  **Retrieval** — ⚠ no `retrieval_golden.csv` found, will be skipped\n")
                + (f"- 🚫  **Abstention** — {abst_count} unanswerable questions: does Twiga "
                   "decline instead of inventing?" if abst_count
                   else "- 🚫  **Abstention** — ⚠ no `abstention_questions.csv` found, will be skipped")
            )

    # ── How Twiga is run (reference, not a step) ────────────────────────────────
    with st.expander("⚙️  How Twiga is run — fixed, mirrors production"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Model", GEN_MODEL.split("/")[-1])
        c2.metric("Temperature", f"{GEN_TEMPERATURE:g}")
        c3.metric("Chunks retrieved", RETRIEVAL_TOP_K)
        src = "imported live from Twiga's config" if IMPORTED_FROM_TWIGA else "last-known values (Twiga config not importable)"
        st.caption(
            f"These mirror the real Twiga — {src} — so the eval can't drift from production. "
            "Change them in Twiga and this follows automatically."
        )
        gen_provider = "Together (production's real provider)" if together_api_key else "OpenRouter (no LLM_API_KEY set, so falling back)"
        st.caption(f"Generation provider this run: **{gen_provider}**.")
        st.caption(
            f"Grader: `{GEN_JUDGE_MODEL}` (fixed so runs stay comparable) · second opinion on "
            f"unverifiable facts: `{ESCALATION_JUDGE_MODEL}` · citation and hallucination checks always on."
        )

    # Fixed run configuration — Twiga-mirroring values come from eval.twiga_config;
    # judges and the extra grounding checks are eval features kept always-on for
    # full runs. Quick runs drop everything but faithfulness/abstention/Recall@10.
    use_direct = False
    gen_model = GEN_MODEL
    gen_judge_model = GEN_JUDGE_MODEL
    retrieval_judge_model = RETRIEVAL_JUDGE_MODEL
    escalate_idk = not quick
    check_citations = not quick
    audit_unsupported = not quick
    twiga_top_k = RETRIEVAL_TOP_K
    timeout_s = DEFAULT_TIMEOUT_S

    # ── Step 2: review & run ────────────────────────────────────────────────────
    st.subheader("2 · Review & run")
    suites = [
        name for name, on in [
            ("generation", run_generation and (quick or bool(selected_subjects))),
            ("retrieval", run_retrieval and ret_count > 0),
            ("abstention", run_abstention and abst_count > 0),
        ] if on
    ]
    if "generation" in suites:
        gen_n = quick_count if quick else sum(_clean_count(s) for s in selected_subjects)
    else:
        gen_n = 0
    ret_n = ret_count if "retrieval" in suites else 0
    abst_n = abst_count if "abstention" in suites else 0

    with st.container(border=True):
        if not suites:
            st.info("Nothing to run — the question set files above are missing or empty.")
            start = False
        else:
            parts = []
            if gen_n:
                gen_name = "Faithfulness (quick set)" if quick else "Generation"
                parts.append(f"**{gen_name}** · {gen_n} questions" + (" (+ ROUGE/BLEU)" if run_lexical else ""))
            if ret_n:
                parts.append(f"**Retrieval** · {ret_n} queries")
            if abst_n:
                parts.append(f"**Abstention** · {abst_n} questions")
            mins = _estimate_minutes(gen_n, ret_n, abst_n, quick=quick)
            st.markdown("About to run:  " + "  +  ".join(parts))
            st.caption(
                f"~{gen_n + ret_n + abst_n} model-graded items · roughly **{mins} min** · uses paid API calls · "
                + ("runs **in the background** — you can close this tab and come back" if not quick
                   else "runs in this tab — keep it open; stop early from the toolbar (top right)")
            )
            run_label = st.text_input(
                "Name this run (optional)", placeholder="e.g. baseline-v1, after-prompt-tweak", key="nr_label"
            )
            start = st.button("▶️  Start evaluation", type="primary")

    if not suites or not start:
        return
    run_label = st.session_state.get("nr_label", "")

    if not quick:
        # full evaluations always run detached — a ~7h run must survive the tab
        _launch_full_run(run_label.strip())
        st.rerun()

    gen_judge_llm = OpenRouterJudgeLLM(model=gen_judge_model, api_key=judge_api_key, timeout=float(timeout_s))
    retrieval_judge_llm = OpenRouterJudgeLLM(model=retrieval_judge_model, api_key=judge_api_key, timeout=float(timeout_s))
    escalation_judge_llm = (
        OpenRouterJudgeLLM(model=ESCALATION_JUDGE_MODEL, api_key=judge_api_key, timeout=float(timeout_s) * 3)
        if escalate_idk else None
    )

    st.caption("To stop an in-progress run, use the **Stop** control in the toolbar (top right).")
    progress_bar = st.progress(0.0, text="Starting…")
    table_placeholder = st.empty()
    throttle = LiveTableThrottle(min_interval_s=2.0)
    throttle.set_placeholder(table_placeholder)

    gen_rows: list[dict] = []
    if "generation" in suites:
        if quick:
            # fixed 100-question sample (equal per subject) — see generate_quick_dataset.py
            gen_rows = pd.read_csv(_QUICK_CSV).to_dict("records")
        else:
            for s in selected_subjects:
                p = QUESTIONS_DIR / f"{s}_questions.csv"
                if p.exists():
                    df = pd.read_csv(p)
                    df = df[df["reference_answer"].notna() & (df["reference_answer"].astype(str).str.strip() != "")]
                    # full question set — no sampling, so runs stay comparable
                    gen_rows.extend(df.to_dict("records"))
    abst_rows = pd.read_csv(_ABSTENTION_CSV).to_dict("records") if "abstention" in suites else []
    ret_rows = pd.read_csv(_RETRIEVAL_CSV).to_dict("records") if "retrieval" in suites else []

    total_steps = len(gen_rows) + len(abst_rows) + len(ret_rows)
    all_results: list[dict] = []
    done = 0
    phase = ""

    def progress_cb(_c: int, _t: int) -> None:
        nonlocal done
        done += 1
        progress_bar.progress(min(done / max(total_steps, 1), 1.0), text=f"{phase} — row {done}/{total_steps}")

    def update_cb(row: dict) -> None:
        all_results.append(row)
        df_live = pd.DataFrame(all_results)
        cols = [c for c in _LIVE_COLS if c in df_live.columns]
        throttle.update(df_live[cols])

    async def _run() -> None:
        nonlocal phase
        db_url_clean = db_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = ReconnectingConnection(db_url_clean, ssl="require")
        try:
            if ret_rows:
                phase = "Retrieval"
                await run_retrieval_eval(
                    rows=ret_rows, conn=conn, embed_api_key=embed_api_key, together_api_key=together_api_key, openrouter_api_key=judge_api_key,
                    judge_llm=retrieval_judge_llm, gen_model=gen_model,
                    top_k=int(twiga_top_k), timeout_s=float(timeout_s),
                    progress_cb=progress_cb, update_cb=update_cb,
                    judge_metrics=not quick,
                )
            if gen_rows:
                phase = "Generation"
                await run_generation_eval(
                    rows=gen_rows, embed_api_key=embed_api_key, together_api_key=together_api_key, openrouter_api_key=judge_api_key, gen_model=gen_model,
                    judge_llm=gen_judge_llm, timeout_s=float(timeout_s),
                    progress_cb=progress_cb, update_cb=update_cb,
                    conn=conn, use_twiga=not use_direct,
                    twiga_top_k=int(twiga_top_k),
                    escalation_judge=escalation_judge_llm,
                    check_citations=check_citations and not use_direct,
                    audit_unsupported=audit_unsupported and not use_direct,
                    include_relevancy=not quick,
                )
            if abst_rows:
                phase = "Abstention"
                await run_abstention_eval(
                    rows=abst_rows, conn=conn, embed_api_key=embed_api_key, together_api_key=together_api_key, openrouter_api_key=judge_api_key,
                    gen_model=gen_model, judge_llm=gen_judge_llm,
                    top_k=int(twiga_top_k), timeout_s=float(timeout_s),
                    progress_cb=progress_cb, update_cb=update_cb,
                )
        finally:
            await conn.close()

    try:
        asyncio.run(_run())
    except Exception as e:
        st.error(f"Run failed: {e}")
        return

    results_df = pd.DataFrame(all_results)
    if results_df.empty:
        st.warning("No results produced.")
        return

    # optional lexical add-on over the generation rows
    if run_lexical and "response" in results_df.columns:
        from eval.metrics.lexical import LexicalMetrics

        async def _lex() -> None:
            metric = LexicalMetrics()
            for idx in results_df.index:
                row = results_df.loc[idx]
                if isinstance(row.get("response"), str) and isinstance(row.get("reference_answer"), str):
                    try:
                        scores = await metric.ascore(
                            {"response": row["response"], "reference": row["reference_answer"]}
                        )
                        for k, v in scores.items():
                            results_df.loc[idx, k] = v
                    except Exception:
                        pass

        asyncio.run(_lex())

    throttle.update(results_df[[c for c in _LIVE_COLS if c in results_df.columns]], force=True)
    progress_bar.progress(1.0, text="Done!")

    # ── Save ───────────────────────────────────────────────────────────────────
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    label = run_label.strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pipeline_tag = "direct" if use_direct else "twiga"
    headline = compute_headline(results_df)

    metadata = {
        "run_id": run_id,
        "label": label,
        "git_commit": _git_commit(),
        "run_type": "quick" if quick else "full",
        "dataset_used": ("quick: " if quick else "") + " + ".join(suites),
        "metrics_run": ("faithfulness,abstention,recall_at_10" if quick
                        else ",".join(suites + (["lexical"] if run_lexical else []))),
        "pipeline": pipeline_tag,
        "gen_model": gen_model,
        "gen_provider": "together" if together_api_key else "openrouter",
        "gen_judge_model": gen_judge_model if ("generation" in suites or "abstention" in suites) else None,
        "retrieval_judge_model": retrieval_judge_model if "retrieval" in suites else None,
        "escalation_judge_model": ESCALATION_JUDGE_MODEL if escalate_idk else None,
        "default_judge": True,
        "gen_temperature": GEN_TEMPERATURE,
        "twiga_settings_from_config": IMPORTED_FROM_TWIGA,
        "n_rows": len(results_df),
        **headline,
    }
    save_results(run_id, results_df, metadata)
    append_run(
        run_id=run_id,
        label=label,
        git_commit=metadata["git_commit"],
        dataset=metadata["dataset_used"],
        metrics_run=metadata["metrics_run"],
        headline_scores=headline,
        n_rows=len(results_df),
        run_type=metadata["run_type"],
        pipeline=pipeline_tag,
        gen_model=gen_model,
        gen_judge_model=gen_judge_model,
    )

    st.success(f"Run saved as `{run_id}` ({label}).")
    render_run_report(results_df, metadata, key=f"post_{run_id}")
