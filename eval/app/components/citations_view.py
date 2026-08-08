"""Citation-correctness breakdown display.

Renders the per-citation verdicts saved by eval.citations.score_citations:
whether each cited chunk exists in the retrieved set and actually supports
the statement it's attached to.
"""

import json

import pandas as pd
import streamlit as st

_MAX_ROWS = 100


def render_citation_breakdown(results_df: pd.DataFrame) -> None:
    """No-op if the run has no citation columns (non-Twiga or older runs)."""
    if "citation_details" not in results_df.columns:
        return

    rows: list[tuple[pd.Series, list[dict]]] = []
    for _, r in results_df.iterrows():
        raw = r.get("citation_details")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            details = json.loads(raw)
        except Exception:
            continue
        rows.append((r, details))

    if not rows:
        return

    st.subheader("Citation correctness")

    def _mean(col: str) -> float | None:
        if col not in results_df.columns:
            return None
        vals = results_df[col].dropna()
        return float(vals.mean()) if not vals.empty else None

    all_details = [d for _, ds in rows for d in ds]
    n_uncited = sum(1 for _, ds in rows if not ds)
    m1, m2, m3, m4 = st.columns(4)
    precision = _mean("citation_precision")
    coverage = _mean("citation_coverage")
    validity = _mean("citation_validity")
    m1.metric("Citation precision", f"{precision:.0%}" if precision is not None else "—",
              help="Cited chunk actually supports the adjacent statement")
    m2.metric("Sentence coverage", f"{coverage:.0%}" if coverage is not None else "—",
              help="Fraction of answer sentences carrying a citation (approximate)")
    m3.metric("Valid chunk ids", f"{validity:.0%}" if validity is not None else "—",
              help="Cited chunk_id was among the retrieved chunks")
    m4.metric("Citations / uncited answers", f"{len(all_details)} / {n_uncited}")

    for r, details in rows[:_MAX_ROWS]:
        if not details:
            continue
        n_ok = sum(1 for d in details if d.get("supported"))
        query = str(r.get("user_query", "") or r.get("question", ""))[:90]
        with st.expander(f"{n_ok}/{len(details)} citations supported — {query}"):
            for d in details:
                supported = d.get("supported")
                icon = "✅" if supported else ("⚠️" if supported is None else "❌")
                st.markdown(f"{icon} `chunk {d.get('chunk_id')}` — {d.get('statement', '')}")
                reason = d.get("reason")
                if reason and not supported:
                    st.caption(f"↳ {reason}")

    if len(rows) > _MAX_ROWS:
        st.caption(f"Showing first {_MAX_ROWS} of {len(rows)} responses.")
