"""Complete report for a saved run, rendered in tabs.

Single rendering path used both immediately after a run finishes and from the
Runs page, so the two views can never drift.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from eval.app.components.abstention_view import render_abstention_results
from eval.app.components.citations_view import render_citation_breakdown
from eval.app.components.claims import render_claim_breakdown
from eval.app.components.retrieval_view import render_retrieval_breakdown
from eval.results import compute_headline, summarize_errors

_METRIC_GROUPS = [
    ("Generation", [
        "faithfulness", "answer_relevancy", "claim_grounded_ratio",
        "hallucination_rate", "retrieval_miss_rate",
    ]),
    ("Citations", ["citation_precision", "citation_coverage"]),
    ("Abstention", ["abstention_rate"]),
    ("Retrieval", [
        "recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10",
        "deepeval_contextual_precision", "deepeval_contextual_recall",
        "deepeval_contextual_relevancy",
    ]),
    ("Lexical", ["rouge_1", "rouge_2", "rouge_l", "bleu"]),
]

_LOWER_BETTER = {"hallucination_rate", "retrieval_miss_rate"}

_MODEL_FIELDS = [
    ("Pipeline", "pipeline"),
    ("Generator", "gen_model"),
    ("Gen provider", "gen_provider"),
    ("Gen judge", "gen_judge_model"),
    ("Retrieval judge", "retrieval_judge_model"),
    ("Escalation judge", "escalation_judge_model"),
]


def _label(metric: str) -> str:
    return metric.replace("deepeval_", "").replace("_", " ").title()


def _summary_tab(results_df: pd.DataFrame, metadata: dict) -> None:
    bits = [f"{name}: `{metadata[key]}`" for name, key in _MODEL_FIELDS if metadata.get(key)]
    commit = str(metadata.get("git_commit", ""))[:7]
    if commit and commit != "unknown":
        bits.append(f"Commit: `{commit}`")
    bits.append(f"Rows: {len(results_df)}")
    st.caption(" | ".join(bits))

    headline = compute_headline(results_df)
    st.caption("All scores are percentages of their scale. ↓ marks rates where lower is better.")
    for group_name, metrics in _METRIC_GROUPS:
        present = [m for m in metrics if m in headline]
        if not present:
            continue
        with st.container(border=True):
            st.markdown(f"**{group_name}**")
            cols = st.columns(5)
            for i, m in enumerate(present):
                suffix = " ↓" if m in _LOWER_BETTER else ""
                cols[i % 5].metric(_label(m) + suffix, f"{headline[m]:.1%}")

    error_summary = summarize_errors(results_df)
    if error_summary:
        total = len(results_df)
        lines = [f"- **{lbl}** failed on {info['count']}/{total} rows" for lbl, info in error_summary.items()]
        st.warning("Some rows have missing scores:\n\n" + "\n".join(lines))

    score_cols = [c for c in ["faithfulness", "answer_relevancy", "citation_precision", "rouge_l"] if c in results_df.columns]
    if "subject" in results_df.columns and score_cols:
        by_subject = results_df.groupby("subject")[score_cols].mean()
        if not by_subject.empty and by_subject.notna().any().any():
            st.markdown("**By subject**")
            st.dataframe(
                by_subject.reset_index(), width="stretch", hide_index=True,
                column_config={
                    c: st.column_config.NumberColumn(_label(c), format="percent")
                    for c in score_cols
                },
            )

    # query-style / chapter / missed-query granularity lives in the Retrieval tab


def render_run_report(results_df: pd.DataFrame, metadata: dict, key: str = "report") -> None:
    tabs = ["Summary"]
    if "hit_at_k" in results_df.columns and results_df["hit_at_k"].notna().any():
        tabs.append("Retrieval")
    if "claim_verdicts" in results_df.columns and results_df["claim_verdicts"].notna().any():
        tabs.append("Claims")
    if "citation_details" in results_df.columns and results_df["citation_details"].notna().any():
        tabs.append("Citations")
    if "abstention_ok" in results_df.columns and results_df["abstention_ok"].notna().any():
        tabs.append("Abstention")
    error_summary = summarize_errors(results_df)
    if error_summary:
        tabs.append("Errors")
    tabs.append("Raw data")

    rendered = st.tabs(tabs)
    for tab_name, tab in zip(tabs, rendered):
        with tab:
            if tab_name == "Summary":
                _summary_tab(results_df, metadata)
            elif tab_name == "Retrieval":
                render_retrieval_breakdown(results_df)
            elif tab_name == "Claims":
                render_claim_breakdown(results_df)
            elif tab_name == "Citations":
                render_citation_breakdown(results_df)
            elif tab_name == "Abstention":
                render_abstention_results(results_df)
            elif tab_name == "Errors":
                for lbl, info in error_summary.items():
                    st.markdown(f"**{lbl}** — {info['count']} rows")
                    for sample in info["samples"]:
                        st.code(sample, language=None)
            elif tab_name == "Raw data":
                st.dataframe(results_df, width="stretch", hide_index=True)
                st.download_button(
                    "Download results.csv",
                    data=results_df.to_csv(index=False).encode(),
                    file_name=f"{metadata.get('run_id', 'results')}.csv",
                    mime="text/csv",
                    key=f"{key}_download",
                )
