"""Overview — the health of Twiga's answers at a glance.

Four hero KPIs, each phrased as one of the questions the tool exists to
answer, taken from the latest FULL baseline run (run_type == "full"; older
runs without the tag fall back to a >= MIN_FULL_ROWS row-count check), with
deltas vs. the previous full run. Quick smoke runs are tracked in their own
section and never move the headline or the baseline trends.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from eval.app.components.charts import multi_trend_chart
from eval.app.runs_index import load_runs_index

MIN_FULL_ROWS = 50

_RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "results"

# (headline metric, short question label, plain-language one-liner, higher_is_better)
_HERO_METRICS = [
    ("claim_grounded_ratio", "Answers backed by the book",
     "Share of facts in Twiga's answers found in the textbook it retrieved.", True),
    ("citation_precision", "Citations that hold up",
     "When Twiga cites a passage, how often it truly supports the point.", True),
    ("abstention_rate", "Declines when it should",
     "On questions the book can't answer, how often Twiga says so instead of guessing.", True),
    ("recall_at_10", "Finds the right pages",
     "How often search puts a correct textbook chunk in its top 10 results.", True),
]

_GLOSSARY = [
    ("Answers backed by the book (claim grounding)",
     "Twiga's answer is split into individual facts; each is checked against the textbook passages it retrieved. This is the share that check out."),
    ("Citations that hold up (citation precision)",
     "Twiga marks which chunk each statement comes from. We verify the cited chunk actually supports that statement."),
    ("Declines when it should (abstention rate)",
     "We ask questions the textbook can't answer. A good answer refuses or corrects a false premise; a bad one invents a reply."),
    ("Finds the right pages (Recall@10, MRR, NDCG)",
     "For questions with known correct chunks, how well vector search surfaces them. The same questions are asked in four phrasings — plain, keyword, misspelled, Swahili."),
    ("Faithfulness / answer relevancy",
     "Judge scores for how grounded and how on-topic each answer is; the claim-level view above breaks faithfulness into individual facts."),
    ("Hallucination vs. retrieval miss",
     "For facts not in the retrieved chunks, we search the whole book: found elsewhere = a retrieval problem; nowhere = a true hallucination."),
]


def _run_meta(run_id: str) -> dict:
    try:
        return json.loads((_RESULTS_DIR / run_id / "metadata.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _n_rows(row: pd.Series, meta: dict) -> int:
    n = row.get("n_rows")
    if pd.notna(n):
        return int(n)
    n = meta.get("n_rows")
    return int(n) if n else 0


def _infer_run_type(row: pd.Series) -> str:
    """Explicit run_type when present; older runs fall back to the row-count
    threshold that used to define a full run."""
    rt = row.get("run_type")
    if isinstance(rt, str) and rt.strip():
        return rt.strip()
    n = row.get("n_rows")
    return "full" if pd.notna(n) and int(n) >= MIN_FULL_ROWS else "quick"


_RECALL_KS = (1, 5, 10)


def _retrieval_style_trends(runs: pd.DataFrame) -> pd.DataFrame:
    """Per-run Recall@1/5/10 split by query style, recomputed from each run's
    saved per-row results — the runs index only stores the blended overall,
    which a weak style (e.g. Swahili) can drag down misleadingly."""
    recall_cols = [f"recall_at_{k}" for k in _RECALL_KS]
    rows = []
    for _, r in runs.iterrows():
        try:
            df = pd.read_csv(
                _RESULTS_DIR / r["run_id"] / "results.csv",
                usecols=lambda c: c in ("query_style", *recall_cols),
            )
        except Exception:
            continue
        present = [c for c in recall_cols if c in df.columns]
        if "query_style" not in df.columns or not present:
            continue
        ret = df[df[present].notna().any(axis=1)].copy()
        if ret.empty:
            continue
        ret["query_style"] = ret["query_style"].astype(str).str.strip().str.lower()
        entry = {"label": r["label"], "timestamp": r["timestamp"]}
        for col in present:
            vals = ret[col].dropna()
            if not vals.empty:
                entry[col] = vals.mean()
        for style, g in ret.groupby("query_style"):
            if not style:
                continue
            for col in present:
                vals = g[col].dropna()
                if not vals.empty:
                    entry[f"{col}_{style}"] = vals.mean()
        rows.append(entry)
    return pd.DataFrame(rows)


def _chart_title(text: str) -> None:
    """A chart-group heading, deliberately a step above body text/captions so
    each section reads as its own labelled block at a glance."""
    st.markdown(
        f'<div style="font-size:1.15rem; font-weight:600; margin-bottom:0.35rem;">{text}</div>',
        unsafe_allow_html=True,
    )


def _date_labels(df: pd.DataFrame) -> pd.Series:
    """Chart x-axis labels: the run's date, with the time added only when
    several runs share a day (so points never collapse into one)."""
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True, format="ISO8601")
    dates = ts.dt.strftime("%Y-%m-%d")
    labels = dates.mask(dates.duplicated(keep=False), ts.dt.strftime("%Y-%m-%d %H:%M"))
    return labels.fillna(df["label"].astype(str))


def render():
    st.title("Overview")
    st.caption(
        "Twiga Evals checks whether Twiga's answers stay grounded in the Tanzanian "
        "secondary-school curriculum. The four numbers below map to the four "
        "questions that matter most."
    )

    runs_df = load_runs_index()
    if runs_df.empty:
        st.info("No evaluations yet. Head to **▶️ Run evaluation** to score Twiga for the first time.")
        return
    runs_df = runs_df.sort_values("timestamp").reset_index(drop=True)
    runs_df["run_type"] = runs_df.apply(_infer_run_type, axis=1)
    full_df = runs_df[runs_df["run_type"] == "full"]
    quick_df = runs_df[runs_df["run_type"] == "quick"]

    # latest / previous full runs (metadata carries the complete headline)
    full_runs: list[tuple[pd.Series, dict]] = []
    for _, row in full_df.iloc[::-1].iterrows():
        meta = _run_meta(row["run_id"])
        full_runs.append((row, meta))
        if len(full_runs) == 2:
            break

    with st.container(border=True):
        st.subheader("Latest health check")
        if not full_runs:
            st.info(
                "No full baseline run yet — quick smoke runs are kept out of the headline "
                "so the numbers stay steady. Start a full evaluation from **▶️ Run evaluation**."
            )
        else:
            latest_row, latest_meta = full_runs[0]
            prev_meta = full_runs[1][1] if len(full_runs) > 1 else {}

            cols = st.columns(len(_HERO_METRICS))
            for col, (key, label, blurb, _hib) in zip(cols, _HERO_METRICS):
                value = latest_meta.get(key)
                prev = prev_meta.get(key)
                with col:
                    if value is None:
                        st.metric(label, "—", help="Not measured in this run")
                    elif prev is not None:
                        st.metric(label, f"{value:.0%}", delta=f"{value - prev:+.0%}")
                    else:
                        st.metric(label, f"{value:.0%}")
                    st.caption(blurb)

            run_name = latest_meta.get("label", latest_row["run_id"])
            ts = str(latest_row.get("timestamp", ""))[:10]
            pieces = [p for p in [
                f"generation `{latest_meta.get('gen_model', '?')}`" if latest_meta.get("gen_model") else "",
                f"judge `{latest_meta.get('gen_judge_model', '?')}`" if latest_meta.get("gen_judge_model") else "",
            ] if p]
            st.caption(
                f"From the latest full evaluation **{run_name}** · "
                f"{_n_rows(latest_row, latest_meta)} test items (questions + retrieval queries) · {ts}"
                + (" · " + " · ".join(pieces) if pieces else "")
                + (f" · deltas vs. previous full evaluation **{full_runs[1][1].get('label', '')}**" if prev_meta else "")
            )

        with st.expander("What do these mean?"):
            for name, desc in _GLOSSARY:
                st.markdown(f"**{name}** — {desc}")

    st.divider()

    # ── Trends (full baseline runs only) ───────────────────────────────────────
    st.subheader("Trends across runs")
    st.caption(
        "Full baseline runs only — each point is one run, labelled by date. "
        "Higher is better except the rates marked ↓."
    )

    trend_df = full_df.copy()
    trend_df["label"] = _date_labels(trend_df)

    # retrieval shown two ways: the blended ranking metrics below (always, from
    # the runs index — includes MRR/NDCG/retrieval-miss, not just Recall), and
    # Recall@k split by query style (when each run's saved results.csv is still
    # on disk — the blended runs-index row alone can't be broken out by style).
    # These used to be either/or, which meant MRR/NDCG/retrieval-miss never
    # rendered once a run had style data (i.e. almost always).
    style_df = _retrieval_style_trends(full_df)
    if not style_df.empty:
        style_df = style_df.sort_values("timestamp").reset_index(drop=True)
        style_df["label"] = _date_labels(style_df)

    any_chart = False

    fig = multi_trend_chart(trend_df, _SEMANTIC_METRICS)
    if fig is not None:
        any_chart = True
        with st.container(border=True):
            _chart_title("Semantic — answer grounding & quality")
            st.plotly_chart(fig, width="stretch")

    fig = multi_trend_chart(trend_df, _RETRIEVAL_METRICS)
    if fig is not None:
        any_chart = True
        with st.container(border=True):
            _chart_title("Retrieval — finding the right pages")
            st.plotly_chart(fig, width="stretch")

    if not style_df.empty:
        k_figs = [(k, multi_trend_chart(style_df, _style_metrics(k))) for k in _RECALL_KS]
        k_figs = [(k, f) for k, f in k_figs if f is not None]
        if k_figs:
            any_chart = True
            with st.container(border=True):
                _chart_title("Retrieval — Recall@k by query style")
                st.caption(
                    "Overall blends all four phrasings, so one weak style can sink it — "
                    "the per-style lines show which phrasing is the real problem."
                )
                for col, (k, fig) in zip(st.columns(len(k_figs)), k_figs):
                    with col:
                        st.markdown(f"*Recall@{k}*")
                        st.plotly_chart(fig, width="stretch")

    fig = multi_trend_chart(trend_df, _CONTEXT_METRICS)
    if fig is not None:
        any_chart = True
        with st.container(border=True):
            _chart_title("Retrieval — judged quality of retrieved context")
            st.plotly_chart(fig, width="stretch")

    fig = multi_trend_chart(trend_df, _LEXICAL_METRICS)
    if fig is not None:
        any_chart = True
        with st.container(border=True):
            _chart_title("Lexical — word overlap with reference answers")
            st.plotly_chart(fig, width="stretch")

    if not any_chart:
        st.info("No full baseline runs with metrics yet to draw trends.")

    st.divider()

    # ── Quick runs ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("Quick runs")
        st.caption(
            "Fast smoke checks on a fixed 100-question sample (25 per subject) — "
            "faithfulness, abstention and Recall@10 only. Tracked separately: they "
            "never move the headline or the full-baseline trends above."
        )
        if quick_df.empty:
            st.info("No quick runs yet. Start one from **▶️ Run evaluation → ⚡ Quick run**.")
        else:
            qdf = quick_df.copy()
            qdf["label"] = _date_labels(qdf)
            fig = multi_trend_chart(qdf, _QUICK_METRICS)
            if fig is not None:
                _chart_title("Faithfulness · abstention · overall Recall@10")
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Quick runs exist but none carry the quick metrics yet.")

        qstyle_df = _retrieval_style_trends(quick_df)
        if not qstyle_df.empty:
            qstyle_df = qstyle_df.sort_values("timestamp").reset_index(drop=True)
            qstyle_df["label"] = _date_labels(qstyle_df)
            fig = multi_trend_chart(qstyle_df, _style_metrics(10))
            if fig is not None:
                _chart_title("Recall@10 by query style")
                st.plotly_chart(fig, width="stretch")

    st.divider()

    # ── Recent runs ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.subheader("Recent runs")
        st.caption("Open any of these in the **📊 Runs** tab for the full breakdown.")
        recent = runs_df.iloc[::-1].head(10)
        cols = [c for c in ["timestamp", "label", "run_type", "dataset_used", "n_rows",
                            "faithfulness", "claim_grounded_ratio"] if c in recent.columns]
        display = recent[cols].rename(columns={
            "timestamp": "when", "label": "run", "run_type": "type", "dataset_used": "suites",
            "n_rows": "questions", "claim_grounded_ratio": "grounded",
        }).copy()
        if "when" in display.columns:
            display["when"] = display["when"].astype(str).str[:16]
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            column_config={
                c: st.column_config.NumberColumn(c, format="percent")
                for c in ("faithfulness", "grounded") if c in display.columns
            },
        )


# Metric families, each rendered as one multi-line chart (column -> legend label).
# ↓ marks a lower-is-better rate so it reads correctly next to the others.
# Keep each family within 8 metrics — the chart palette has 8 fixed slots.
_QUICK_METRICS = {
    "faithfulness": "Faithfulness",
    "abstention_rate": "Abstention Rate",
    "recall_at_10": "Recall@10",
}
_SEMANTIC_METRICS = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer Relevancy",
    "claim_grounded_ratio": "Claim Grounding",
    "citation_precision": "Citation Precision",
    "citation_coverage": "Citation Coverage",
    "abstention_rate": "Abstention Rate",
    "hallucination_rate": "Hallucination Rate ↓",
}
_RETRIEVAL_METRICS = {
    "recall_at_1": "Recall@1",
    "recall_at_5": "Recall@5",
    "recall_at_10": "Recall@10",
    "mrr": "MRR",
    "ndcg_at_10": "NDCG@10",
    "retrieval_miss_rate": "Retrieval Miss ↓",
}
# per-style view built by _retrieval_style_trends from each run's results.csv
def _style_metrics(k: int) -> dict[str, str]:
    col = f"recall_at_{k}"
    return {
        f"{col}_explanatory": "Plain question",
        f"{col}_keyword": "Keyword search",
        f"{col}_misspelled": "Misspelled",
        f"{col}_swahili": "Swahili",
        col: "Overall",
    }
_CONTEXT_METRICS = {
    "deepeval_contextual_precision": "Contextual Precision",
    "deepeval_contextual_recall": "Contextual Recall",
    "deepeval_contextual_relevancy": "Contextual Relevancy",
}
_LEXICAL_METRICS = {
    "rouge_1": "ROUGE-1", "rouge_2": "ROUGE-2", "rouge_l": "ROUGE-L", "bleu": "BLEU",
}
