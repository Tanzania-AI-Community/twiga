"""Retrieval diagnostics — where does search break down?

The golden queries come in four styles (explanatory / keyword / misspelled /
Swahili) across every textbook chapter, so a drop in the headline ranking
metrics can be traced to the phrasings or content areas causing it: is Twiga
robust to misspellings, does Swahili phrasing hurt, which chapters are weak,
and which specific queries missed entirely.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from eval.app.components.charts import series_colors

# fixed display order: the plain phrasing first, the stress phrasings after
_STYLE_ORDER = ["explanatory", "keyword", "misspelled", "swahili"]
_STYLE_LABELS = {
    "explanatory": "Plain question",
    "keyword": "Keyword search",
    "misspelled": "Misspelled",
    "swahili": "Swahili",
}
_CHART_METRICS = {"recall_at_1": "Recall@1", "recall_at_10": "Recall@10", "mrr": "MRR"}
_TABLE_METRICS = {
    "recall_at_1": "Recall@1", "recall_at_5": "Recall@5", "recall_at_10": "Recall@10",
    "mrr": "MRR", "ndcg_at_10": "NDCG@10",
}
# a style this far below plain-question Recall@10 gets called out as a problem
_GAP_THRESHOLD = 0.10


def _style_label(style: str) -> str:
    return _STYLE_LABELS.get(style, style.title())


def render_retrieval_breakdown(results_df: pd.DataFrame) -> None:
    if "hit_at_k" not in results_df.columns:
        st.info("No retrieval rows in this run.")
        return
    df = results_df[results_df["hit_at_k"].notna()].copy()
    if df.empty:
        st.info("No retrieval rows in this run.")
        return

    df["query_style"] = df["query_style"].astype(str).str.strip().str.lower()
    df["chapter"] = df["chapter"].astype(str).str.strip()
    df["subject"] = df["chapter"].str.split("_").str[0]

    metric_cols = [c for c in _TABLE_METRICS if c in df.columns]

    # ── By query style ──────────────────────────────────────────────────────────
    st.markdown("**By query style — is it misspellings? Swahili?**")
    st.caption(
        "The same questions asked four ways. A gap between *Plain question* and a "
        "stress phrasing shows where search is fragile."
    )

    styles = [s for s in _STYLE_ORDER if s in set(df["query_style"])] + sorted(
        set(df["query_style"]) - set(_STYLE_ORDER) - {""}
    )
    by_style = df.groupby("query_style")[metric_cols].mean().reindex(styles)
    counts = df.groupby("query_style").size().reindex(styles)

    # call out the phrasings that fall visibly below the plain-question baseline
    if "recall_at_10" in by_style.columns and "explanatory" in by_style.index:
        base = by_style.loc["explanatory", "recall_at_10"]
        weak = {
            s: base - by_style.loc[s, "recall_at_10"]
            for s in styles if s != "explanatory"
            and pd.notna(by_style.loc[s, "recall_at_10"])
            and base - by_style.loc[s, "recall_at_10"] >= _GAP_THRESHOLD
        }
        if weak:
            worst = max(weak, key=weak.get)
            st.warning(
                "Weak spots vs plain questions (Recall@10): "
                + " · ".join(f"**{_style_label(s)}** −{gap:.0%}" for s, gap in sorted(
                    weak.items(), key=lambda kv: -kv[1]))
                + f". **{_style_label(worst)}** phrasing hurts the most."
            )
        else:
            st.caption(
                f"No stress phrasing falls more than {_GAP_THRESHOLD:.0%} of Recall@10 "
                "below plain questions — retrieval is holding up across phrasings."
            )

    chart_metrics = {c: lbl for c, lbl in _CHART_METRICS.items() if c in df.columns}
    if chart_metrics:
        long = by_style[list(chart_metrics)].reset_index().melt(
            id_vars="query_style", var_name="metric", value_name="score"
        )
        long["metric"] = long["metric"].map(chart_metrics)
        long["style"] = long["query_style"].map(_style_label)
        fig = px.bar(
            long, x="style", y="score", color="metric", barmode="group",
            labels={"style": "", "score": "", "metric": ""},
            color_discrete_map={
                lbl: series_colors()[i] for i, lbl in enumerate(chart_metrics.values())
            },
            category_orders={"style": [_style_label(s) for s in styles],
                             "metric": list(chart_metrics.values())},
        )
        fig.update_traces(hovertemplate="%{y:.1%}")
        fig.update_layout(
            font=dict(size=14),
            xaxis=dict(type="category", automargin=True),
            yaxis=dict(range=[0, 1.02], tickformat=".0%", automargin=True),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
            margin=dict(t=36, b=10, l=10, r=10),
            height=320,
            bargap=0.35,
        )
        st.plotly_chart(fig, width="stretch")

    style_table = by_style.reset_index()
    style_table["query_style"] = style_table["query_style"].map(_style_label)
    style_table.insert(1, "queries", counts.values)
    st.dataframe(
        style_table.rename(columns={"query_style": "style", **_TABLE_METRICS}),
        width="stretch", hide_index=True,
        column_config={
            lbl: st.column_config.NumberColumn(lbl, format="percent")
            for lbl in _TABLE_METRICS.values()
        },
    )

    # ── By chapter ──────────────────────────────────────────────────────────────
    st.markdown("**By chapter — weakest content areas first**")
    by_chapter = (
        df[df["chapter"] != ""]
        .groupby(["subject", "chapter"])[metric_cols]
        .agg(["mean"])
        .droplevel(1, axis=1)
        .reset_index()
    )
    by_chapter.insert(2, "queries", df[df["chapter"] != ""].groupby(["subject", "chapter"]).size().values)
    sort_col = "recall_at_10" if "recall_at_10" in by_chapter.columns else metric_cols[0]
    by_chapter = by_chapter.sort_values(sort_col)
    st.caption("Small per-chapter samples — read big differences, not single points.")
    st.dataframe(
        by_chapter.rename(columns=_TABLE_METRICS),
        width="stretch", hide_index=True,
        column_config={
            lbl: st.column_config.NumberColumn(lbl, format="percent")
            for lbl in _TABLE_METRICS.values()
        },
    )

    # ── Missed queries ──────────────────────────────────────────────────────────
    miss_col = "recall_at_10" if "recall_at_10" in df.columns else "hit_at_k"
    misses = df[df[miss_col].fillna(0) == 0]
    st.markdown("**Missed queries**")
    if misses.empty:
        st.caption("Every query got at least one correct chunk into the top 10. 🎉")
        return
    st.caption(
        f"{len(misses)} of {len(df)} queries got **no** correct chunk into the top 10 — "
        "the raw material for fixing retrieval."
    )
    show_cols = [c for c in ["user_query", "query_style", "chapter", "mrr"] if c in misses.columns]
    miss_table = misses[show_cols].copy()
    miss_table["query_style"] = miss_table["query_style"].map(_style_label)
    st.dataframe(
        miss_table.rename(columns={"user_query": "query", "query_style": "style", "mrr": "MRR"}),
        width="stretch", hide_index=True,
        column_config={"MRR": st.column_config.NumberColumn("MRR", format="percent")},
    )
