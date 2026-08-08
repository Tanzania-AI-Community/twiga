"""Runs page — history table, per-run report, run comparison, deletion."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from eval.app.components.run_report import render_run_report
from eval.app.runs_index import delete_run, load_runs_index
from eval.results import compute_headline, load_results

_TABLE_COLS = [
    "timestamp", "label", "run_type", "git_commit", "dataset_used", "n_rows",
    "faithfulness", "claim_grounded_ratio", "citation_precision", "abstention_rate",
]

_RENAME = {
    "timestamp": "when", "label": "run", "run_type": "type", "git_commit": "commit",
    "dataset_used": "suites", "n_rows": "items", "claim_grounded_ratio": "grounded",
    "citation_precision": "citations ok", "abstention_rate": "abstains",
}

_PERCENT_COLS = ["faithfulness", "grounded", "citations ok", "abstains"]

_COMPARE_METRICS = [
    "faithfulness", "answer_relevancy", "claim_grounded_ratio",
    "hallucination_rate", "retrieval_miss_rate",
    "citation_precision", "citation_coverage", "abstention_rate",
    "recall_at_10", "mrr", "rouge_l",
]


def _short(commit) -> str:
    s = str(commit)
    return s[:7] if s and s != "unknown" and s != "nan" else "—"


def _fmt_label(runs_df: pd.DataFrame):
    def fmt(run_id: str) -> str:
        if run_id == "—":
            return run_id
        match = runs_df[runs_df["run_id"] == run_id]
        return f"{match['label'].values[0]}  ({run_id})" if not match.empty else run_id
    return fmt


def render():
    st.title("Runs")

    runs_df = load_runs_index()
    if runs_df.empty:
        st.info("No runs yet — go to **New Run** to get started.")
        return
    runs_df = runs_df.sort_values("timestamp", ascending=False).reset_index(drop=True)

    display = runs_df[[c for c in _TABLE_COLS if c in runs_df.columns]].copy()
    if "git_commit" in display.columns:
        display["git_commit"] = display["git_commit"].apply(_short)
    if "timestamp" in display.columns:
        display["timestamp"] = display["timestamp"].astype(str).str[:16]
    display = display.rename(columns=_RENAME)
    st.dataframe(
        display, width="stretch", hide_index=True,
        column_config={
            c: st.column_config.NumberColumn(c, format="percent")
            for c in _PERCENT_COLS if c in display.columns
        },
    )

    st.divider()

    run_ids = runs_df["run_id"].tolist()
    fmt = _fmt_label(runs_df)
    selected = st.selectbox("Open a run", options=["—"] + run_ids, format_func=fmt)
    if selected == "—":
        return

    try:
        results_df, meta = load_results(selected)
    except Exception as e:
        st.warning(f"Could not load run: {e}")
        return

    st.subheader(meta.get("label", selected))
    render_run_report(results_df, meta, key=f"runs_{selected}")

    # ── Compare ────────────────────────────────────────────────────────────────
    st.divider()
    other = st.selectbox(
        "Compare with…",
        options=["—"] + [r for r in run_ids if r != selected],
        format_func=fmt,
        key=f"cmp_{selected}",
    )
    if other != "—":
        try:
            other_df, other_meta = load_results(other)
        except Exception as e:
            st.warning(f"Could not load comparison run: {e}")
        else:
            _render_compare(results_df, meta, other_df, other_meta)

    # ── Delete ─────────────────────────────────────────────────────────────────
    st.divider()
    with st.expander("Danger zone"):
        confirm_key = f"confirm_delete_{selected}"
        label = meta.get("label", selected)
        if not st.session_state.get(confirm_key, False):
            if st.button(f"Delete run '{label}'", type="secondary"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning(f"Permanently delete run '{label}' and its results? This can't be undone.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, delete permanently", type="primary", key=f"del_{selected}"):
                    delete_run(selected)
                    st.session_state.pop(confirm_key, None)
                    st.success("Run deleted.")
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"cancel_{selected}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


def _render_compare(df_a: pd.DataFrame, meta_a: dict, df_b: pd.DataFrame, meta_b: dict) -> None:
    st.subheader("Comparison")

    judge_a = meta_a.get("gen_judge_model")
    judge_b = meta_b.get("gen_judge_model")
    if judge_a and judge_b and judge_a != judge_b:
        st.warning(
            f"These runs used different judges (`{judge_a}` vs `{judge_b}`) — "
            "score differences reflect the judge as much as Twiga."
        )

    head_a = compute_headline(df_a)
    head_b = compute_headline(df_b)
    rows = []
    for m in _COMPARE_METRICS:
        if m in head_a or m in head_b:
            a, b = head_a.get(m), head_b.get(m)
            rows.append({
                "metric": m,
                meta_a.get("label", "A"): round(a, 3) if a is not None else None,
                meta_b.get("label", "B"): round(b, 3) if b is not None else None,
                "delta": round(a - b, 3) if a is not None and b is not None else None,
            })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # per-question regressions on faithfulness for shared questions
    if "faithfulness" in df_a.columns and "faithfulness" in df_b.columns and "user_query" in df_a.columns:
        merged = df_a[["user_query", "faithfulness"]].merge(
            df_b[["user_query", "faithfulness"]], on="user_query", suffixes=("_a", "_b")
        ).dropna()
        if not merged.empty:
            merged["delta"] = merged["faithfulness_a"] - merged["faithfulness_b"]
            regressions = merged[merged["delta"] < 0].sort_values("delta")
            st.caption(
                f"{len(merged)} shared questions · {len(regressions)} scored lower "
                f"in '{meta_a.get('label', 'A')}'"
            )
            if not regressions.empty:
                st.dataframe(
                    regressions.head(10).round(3),
                    width="stretch",
                    hide_index=True,
                )
