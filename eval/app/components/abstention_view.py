"""Abstention results display.

Shows how Twiga handled deliberately unanswerable questions: overall
abstention rate, per-category breakdown, and every fabricated answer in full.
"""

import pandas as pd
import streamlit as st


def render_abstention_results(results_df: pd.DataFrame) -> None:
    """No-op if the run has no abstention rows."""
    if "abstention_ok" not in results_df.columns:
        return
    df = results_df[results_df["abstention_ok"].notna()].copy()
    if df.empty:
        return

    st.subheader("Abstention (unanswerable questions)")

    ok = int(df["abstention_ok"].sum())
    total = len(df)
    m1, m2 = st.columns(2)
    m1.metric(
        "Abstention rate",
        f"{ok}/{total} ({ok / total:.0%})",
        help="Declined or corrected the premise instead of fabricating an answer",
    )
    m2.metric("Fabricated answers", total - ok)

    if "category" in df.columns:
        by_cat = (
            df.groupby("category")["abstention_ok"].agg(["mean", "count"]).reset_index()
        )
        by_cat.columns = ["category", "abstention_rate", "n"]
        by_cat["abstention_rate"] = by_cat["abstention_rate"].round(2)
        st.dataframe(by_cat, width="stretch", hide_index=True)

    failures = df[df["abstention_ok"] == 0]
    if not failures.empty:
        st.markdown("**Fabricated answers** — the model answered as though the textbook supported it:")
        for _, r in failures.iterrows():
            with st.expander(f"[{r.get('category', '?')}] {str(r.get('user_query', ''))[:90]}"):
                st.write(r.get("response", ""))
                reason = r.get("abstention_reason")
                if isinstance(reason, str) and reason:
                    st.caption(f"Judge: {reason}")
