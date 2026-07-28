"""Datasets page — every dataset runs use, grouped by the suite it feeds."""

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from eval.deepeval_runner import QUESTIONS_DIR, SUBJECTS
from eval.testset import load_testset

_GOLDEN_DIR = Path(__file__).parent.parent.parent / "data" / "golden"

# suite -> (filename, expected columns, description)
_SUITE_SETS = [
    ("🔍 Retrieval", "retrieval_golden.csv",
     ["user_query", "golden_chunk_ids", "reference_answer", "query_style", "chapter"],
     "Sanity-checked questions with duplicate-verified golden chunk ids, scored with "
     "Recall@k/MRR/NDCG plus the contextual judge metrics. 40 paired questions asked in "
     "all four styles (explanatory/keyword/misspelled/swahili), 160 queries total."),
    ("🚫 Abstention", "abstention_questions.csv",
     ["question", "subject", "grade_level", "category"],
     "Unanswerable questions (out-of-domain / not-in-book / false-premise); checks "
     "Twiga declines instead of fabricating."),
    ("⚡ Quick run", "quick_run_questions.csv",
     ["question", "subject", "grade_level", "reference_answer"],
     "A fixed sample of 100 questions (25 per subject, drawn with a fixed seed from the "
     "Generation question banks) scored for faithfulness in quick runs. Fixed so quick "
     "runs stay comparable to each other."),
]


def _row_count(name: str) -> int:
    path = _GOLDEN_DIR / name
    if not path.exists():
        return 0
    try:
        return len(pd.read_csv(path))
    except Exception:
        return 0


def _download_template(columns: list[str]) -> bytes:
    buf = io.StringIO()
    buf.write(",".join(columns) + "\n")
    return buf.getvalue().encode()


def render():
    st.title("Datasets")
    st.caption("Everything below is used by runs, grouped by the suite it feeds.")

    # ── Generation — the subject question banks ────────────────────────────────
    st.subheader("📝 Generation — subject question banks")
    st.caption(
        "A full run asks every question from all four banks; the quick-run sample is "
        "drawn from them too. Questions were written from textbook chunks, with "
        "reference answers filled in and quality-checked."
    )

    for subject in SUBJECTS:
        path = QUESTIONS_DIR / f"{subject}_questions.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
            clean = df[
                df["reference_answer"].notna()
                & (df["reference_answer"].astype(str).str.strip() != "")
            ]
        except Exception:
            df = clean = pd.DataFrame()

        with st.expander(f"{subject}_questions.csv  ({len(clean)} questions)"):
            if not df.empty:
                grade_levels = sorted(df["grade_level"].dropna().unique()) if "grade_level" in df.columns else []
                if grade_levels:
                    st.caption("Forms: " + ", ".join(str(g) for g in grade_levels))

                if st.button("Preview", key=f"preview_q_{subject}"):
                    preview_cols = [c for c in ["question", "grade_level", "reference_answer"] if c in df.columns]
                    st.dataframe(clean[preview_cols].head(10), width="stretch")

                st.download_button(
                    label="Download questions",
                    data=clean.to_csv(index=False).encode(),
                    file_name=f"{subject}_questions.csv",
                    mime="text/csv",
                    key=f"dl_q_{subject}",
                )

    st.divider()

    # ── The other suites — one golden file each ────────────────────────────────
    for suite, name, columns, description in _SUITE_SETS:
        st.subheader(suite)
        count = _row_count(name)
        with st.expander(f"{name}  ({count} rows)", expanded=False):
            st.caption(description)
            st.markdown("**Expected columns:** " + ", ".join(f"`{c}`" for c in columns))

            col1, col2 = st.columns(2)
            with col1:
                if count > 0:
                    if st.button(f"Preview {name}", key=f"preview_{name}"):
                        st.dataframe(load_testset(name).head(10), width="stretch")
                else:
                    st.info("Empty — no rows yet")
            with col2:
                st.download_button(
                    label="Download template",
                    data=_download_template(columns),
                    file_name=name,
                    mime="text/csv",
                    key=f"dl_{name}",
                )
