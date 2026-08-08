"""Twiga Evals — Streamlit evaluation dashboard.

Run with:
    streamlit run eval/app/app.py
"""

import subprocess
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so eval.* imports work
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

st.set_page_config(
    page_title="Twiga Evals",
    page_icon="🦒",
    layout="wide",
    initial_sidebar_state="expanded",
)

from eval.app.pages import about, datasets, new_run, overview, runs


def _git_info() -> tuple[str, str]:
    """Returns (branch, short_commit)."""
    root = str(_REPO_ROOT)
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        branch = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        commit = "unknown"
    return branch, commit


_PAGES = {
    "🏠  Overview": overview.render,
    "▶️  Run evaluation": new_run.render,
    "📊  Runs": runs.render,
    "📁  Datasets": datasets.render,
    "ℹ️  About": about.render,
}


def main():
    branch, commit = _git_info()

    with st.sidebar:
        st.markdown("## 🦒 Twiga Evals")
        st.caption("Is Twiga's teaching grounded in the curriculum?")
        st.divider()

        page = st.radio("Navigate", options=list(_PAGES), label_visibility="collapsed")

        st.divider()
        st.caption(f"Branch `{branch}` · commit `{commit}`")

    _PAGES[page]()


if __name__ == "__main__":
    main()
