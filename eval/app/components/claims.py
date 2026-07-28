"""Claim-level faithfulness breakdown display.

Renders the per-claim verdicts saved by deepeval_runner's FaithfulnessMetric
scoring: which facts in each response are grounded in the textbook context,
which are contradicted, and which couldn't be verified.
"""

import json

import pandas as pd
import streamlit as st

_ICONS = {"yes": "✅", "no": "❌", "idk": "❓"}
_MAX_ROWS = 100


def render_claim_breakdown(results_df: pd.DataFrame) -> None:
    """Show aggregate claim counts and a per-response verdict list.

    No-op if the run has no claim_verdicts column (older runs, retrieval-only
    runs, or rows where faithfulness failed).
    """
    if "claim_verdicts" not in results_df.columns:
        return

    rows: list[tuple[pd.Series, list[dict]]] = []
    for _, r in results_df.iterrows():
        raw = r.get("claim_verdicts")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            verdicts = json.loads(raw)
        except Exception:
            continue
        if verdicts:
            rows.append((r, verdicts))

    if not rows:
        return

    st.subheader("Claim-level faithfulness")

    all_claims = [c for _, v in rows for c in v]
    total = len(all_claims)
    supported = sum(1 for c in all_claims if c.get("verdict") == "yes")
    contradicted = sum(1 for c in all_claims if c.get("verdict") == "no")
    unverifiable = total - supported - contradicted

    n_miss = sum(1 for c in all_claims if c.get("source_audit") == "retrieval_miss")
    n_halluc = sum(1 for c in all_claims if c.get("source_audit") == "hallucination")

    st.caption(
        f"Every answer is split into individual facts (claims) and each is checked "
        f"against the textbook passages Twiga retrieved — {total:,} claims from "
        f"{len(rows)} answers in this run."
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Grounded", f"{supported / total:.0%}" if total else "—",
        help=f"{supported:,} of {total:,} claims verified against the retrieved passages",
    )
    m2.metric("Claims checked", f"{total:,}")
    m3.metric("Contradicted", contradicted, help="Claims the textbook passages contradict")
    m4.metric("Unverifiable", unverifiable, help="Claims the passages neither support nor contradict")

    if n_miss or n_halluc:
        a1, a2 = st.columns(2)
        a1.metric(
            "In book, not retrieved",
            n_miss,
            help="Unsupported claim found elsewhere in the textbook — a retrieval problem",
        )
        a2.metric(
            "Not found in book",
            n_halluc,
            help="Unsupported claim absent from the whole textbook — a hallucination",
        )

    for r, verdicts in rows[:_MAX_ROWS]:
        n_yes = sum(1 for c in verdicts if c.get("verdict") == "yes")
        query = str(r.get("user_query", "") or r.get("question", ""))[:90]
        with st.expander(f"{n_yes}/{len(verdicts)} grounded — {query}"):
            response = r.get("response")
            if isinstance(response, str) and response.strip():
                st.caption("Response")
                st.write(response)
                st.divider()
            for c in verdicts:
                verdict = str(c.get("verdict", "")).lower()
                icon = _ICONS.get(verdict, "•")
                escalated = c.get("original_verdict") == "idk"
                suffix = "  *(escalated from ❓)*" if escalated else ""
                st.markdown(f"{icon} {c.get('claim', '')}{suffix}")
                reason = c.get("escalation_reason") if escalated else c.get("reason")
                if reason and (verdict != "yes" or escalated):
                    st.caption(f"↳ {reason}")
                audit = c.get("source_audit")
                if audit == "retrieval_miss":
                    st.caption(f"📖 Found in textbook — retrieval miss. {c.get('audit_reason', '')}")
                elif audit == "hallucination":
                    st.caption(f"🚫 Not found anywhere in textbook — hallucination. {c.get('audit_reason', '')}")

    if len(rows) > _MAX_ROWS:
        st.caption(f"Showing first {_MAX_ROWS} of {len(rows)} responses.")
