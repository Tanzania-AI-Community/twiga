"""Plotly figure builders shared by the eval app pages.

Series colors come from a fixed, CVD-validated categorical palette — the same
hue order stepped separately for light and dark surfaces, picked to keep
adjacent series distinguishable under color-vision deficiency. Colors are
assigned per metric from the full group definition (not just the metrics with
data), so a metric keeps its color as runs add or drop metrics. Groups must
stay within the palette's 8 slots.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_SERIES_COLORS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500",
             "#d55181", "#008300", "#9085e9", "#e66767"],
}


def series_colors() -> list[str]:
    try:
        mode = "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        mode = "light"
    return _SERIES_COLORS[mode]


def trend_chart(
    runs_df: pd.DataFrame,
    metric_col: str,
    title: str,
    x_label: str = "Run",
) -> go.Figure:
    """Line chart of a metric across runs. Hover shows git commit."""
    df = runs_df[["label", "git_commit", metric_col]].dropna(subset=[metric_col]).copy()
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, xaxis_title=x_label, yaxis_title=metric_col)
        return fig

    df["commit_short"] = df["git_commit"].astype(str).str[:7]
    fig = px.line(
        df,
        x="label",
        y=metric_col,
        markers=True,
        title=title,
        labels={"label": x_label, metric_col: ""},
        color_discrete_sequence=series_colors(),
        hover_data={"commit_short": True, metric_col: ":.1%"},
    )
    fig.update_layout(
        font=dict(size=14),
        xaxis=dict(type="category", tickangle=-30, automargin=True),
        yaxis=dict(range=[0, 1.02], tickformat=".0%", automargin=True),
        margin=dict(t=48, b=10, l=10, r=10),
        height=300,
    )
    return fig


def multi_trend_chart(
    runs_df: pd.DataFrame,
    metric_cols: dict[str, str],
    x_label: str = "Run",
) -> go.Figure | None:
    """One line per metric across runs, each its own colour.

    `metric_cols` maps a runs-index column -> the label shown in the legend.
    The chart title belongs to the page (render it with st.markdown above the
    chart) so a wrapping legend never collides with it.
    Returns None if none of the metrics have data.
    """
    present = {c: lbl for c, lbl in metric_cols.items()
               if c in runs_df.columns and runs_df[c].notna().any()}
    if not present:
        return None

    df = runs_df[["label", *present]].copy()
    long = df.melt(id_vars="label", value_vars=list(present), var_name="metric", value_name="score")
    long = long.dropna(subset=["score"])
    long["metric"] = long["metric"].map(present)

    colors = series_colors()
    color_map = {lbl: colors[i % len(colors)]
                 for i, lbl in enumerate(metric_cols.values())}

    # Trace order drives the "x unified" hover box's stacking order (not just
    # the legend), so order it by each metric's mean score, highest first —
    # otherwise the hover box lists metrics in whatever arbitrary order they
    # were defined in, which reads as scrambled next to the actual values.
    mean_score = long.groupby("metric")["score"].mean()
    hover_order = mean_score.sort_values(ascending=False).index.tolist()

    fig = px.line(
        long,
        x="label",
        y="score",
        color="metric",
        markers=True,
        labels={"label": x_label, "score": "", "metric": ""},
        color_discrete_map=color_map,
        category_orders={"metric": hover_order},
    )
    fig.update_traces(hovertemplate="%{y:.1%}", line_width=2, marker_size=7)
    # Top margin sized for the legend's worst-case wrap (~3 items per row on a
    # narrow window) so its rows never spill into the plot or the page heading.
    legend_rows = -(-len(present) // 3)
    fig.update_layout(
        font=dict(size=14),
        hovermode="x unified",
        # one evenly spaced tick per run — keeps date labels from being read
        # as a continuous time axis with empty hour ticks between runs
        xaxis=dict(type="category", tickangle=-30, automargin=True, title=None),
        yaxis=dict(range=[0, 1.02], tickformat=".0%", automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
        margin=dict(t=10 + 26 * legend_rows, b=10, l=10, r=10),
        height=340,
    )
    return fig
