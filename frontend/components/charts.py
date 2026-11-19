"""Plotly chart builders for InsightFlow.

Charts receive pre-aggregated data from the backend. No chart contains
hardcoded values.
"""

from __future__ import annotations

import html
from typing import Any

import plotly.graph_objects as go

from components.ui import INDIGO, SKY, TEAL

_FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
_GRID = "#EEF1F7"
_MUTED = "#64748B"
_PALETTE = [INDIGO, SKY, TEAL, "#F59E0B", "#E11D48", "#8B5CF6", "#0EA5E9", "#14B8A6"]


def _apply(fig: go.Figure, height: int = 320, legend: bool = False) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=12, r=12, t=28, b=12),
        font=dict(family=_FONT, size=12, color="#334155"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=_PALETTE,
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hoverlabel=dict(bgcolor="#0F172A", font=dict(color="#fff", family=_FONT, size=12)),
    )
    fig.update_xaxes(gridcolor=_GRID, zeroline=False, linecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zeroline=False, linecolor=_GRID)
    return fig


def histogram(stats: dict[str, Any], color: str = INDIGO) -> go.Figure:
    """Bar-based histogram from backend-provided bins."""
    bins = stats.get("histogram") or []
    if not bins:
        return _empty_chart("No numeric distribution available")
    centers = [(item["start"] + item["end"]) / 2 for item in bins]
    widths = [item["end"] - item["start"] for item in bins]
    labels = [f"{item['start']:,.2f} – {item['end']:,.2f}" for item in bins]
    figure = go.Figure(
        go.Bar(
            x=centers,
            y=[item["count"] for item in bins],
            width=widths,
            customdata=labels,
            marker=dict(color=color, opacity=0.85, line=dict(width=0)),
            hovertemplate="Range: %{customdata}<br>Records: %{y:,}<extra></extra>",
        )
    )
    figure.update_layout(bargap=0.06)
    figure.update_xaxes(title=html.escape(str(stats.get("name", "value"))))
    figure.update_yaxes(title="Records")
    return _apply(figure)


def box_plot(stats: dict[str, Any], color: str = TEAL) -> go.Figure:
    """Box plot using quartile summaries (no raw rows required)."""
    if stats.get("median") is None:
        return _empty_chart("Not enough values for a box plot")
    figure = go.Figure(
        go.Box(
            q1=[stats.get("q1")],
            median=[stats.get("median")],
            q3=[stats.get("q3")],
            lowerfence=[stats.get("minimum")],
            upperfence=[stats.get("maximum")],
            name=html.escape(str(stats.get("name", "value"))),
            marker_color=color,
            fillcolor="rgba(13,148,136,.14)",
            line=dict(color=color, width=2),
            boxpoints=False,
        )
    )
    figure.update_yaxes(title=html.escape(str(stats.get("name", "value"))))
    return _apply(figure, height=250)


def category_bar(stats: dict[str, Any], limit: int = 10) -> go.Figure:
    values = (stats.get("top_values") or [])[:limit]
    if not values:
        return _empty_chart("No category values available")
    ordered = list(reversed(values))
    labels = [html.escape(str(item["value"])) for item in ordered]
    counts = [item["count"] for item in ordered]
    figure = go.Figure(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker=dict(color=INDIGO, opacity=0.85),
            customdata=[f"{item['percentage']:.1f}%" for item in ordered],
            hovertemplate="%{y}<br>Records: %{x:,}<br>Share: %{customdata}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Records")
    return _apply(figure, height=max(260, 34 * len(labels) + 80))


def correlation_heatmap(correlations: dict[str, Any]) -> go.Figure:
    columns = correlations.get("columns") or []
    matrix = correlations.get("matrix") or []
    if not columns:
        return _empty_chart("At least two numeric columns are required")
    text = [["" if value is None else f"{value:.2f}" for value in row] for row in matrix]
    safe_columns = [html.escape(str(column)) for column in columns]
    figure = go.Figure(
        go.Heatmap(
            z=matrix,
            x=safe_columns,
            y=safe_columns,
            zmin=-1,
            zmax=1,
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=11),
            colorscale=[
                [0.0, "#E11D48"],
                [0.25, "#FB7185"],
                [0.5, "#F8FAFC"],
                [0.75, "#5EEAD4"],
                [1.0, "#0F766E"],
            ],
            hovertemplate="%{x} ↔ %{y}<br>r = %{z:.3f}<extra></extra>",
            colorbar=dict(title="r", thickness=12, len=0.75),
        )
    )
    return _apply(figure, height=max(360, 48 * len(columns) + 120))


def time_series(series: dict[str, Any]) -> go.Figure:
    points = series.get("points") or []
    if not points:
        return _empty_chart("No time series points available")
    figure = go.Figure(
        go.Scatter(
            x=[point["period"] for point in points],
            y=[point["value"] for point in points],
            mode="lines+markers",
            line=dict(color=INDIGO, width=2.5, shape="spline", smoothing=0.35),
            marker=dict(size=5, color=INDIGO, line=dict(color="#fff", width=1.5)),
            fill="tozeroy",
            fillcolor="rgba(79,70,229,.08)",
            customdata=[point["record_count"] for point in points],
            hovertemplate="%{x}<br>Value: %{y:,.2f}<br>Records: %{customdata:,}<extra></extra>",
        )
    )
    metric_name = html.escape(str(series.get("metric_column", "")))
    aggregation = html.escape(str(series.get("aggregation", "value")))
    figure.update_yaxes(title=f"{aggregation} of {metric_name}")
    return _apply(figure, height=340)


def anomaly_scores(buckets: list[dict[str, Any]]) -> go.Figure:
    if not buckets:
        return _empty_chart("No score distribution available")
    centers = [(item["start"] + item["end"]) / 2 for item in buckets]
    widths = [item["end"] - item["start"] for item in buckets]
    labels = [f"{item['start']:.3f} – {item['end']:.3f}" for item in buckets]
    figure = go.Figure(
        go.Bar(
            x=centers,
            y=[item["count"] for item in buckets],
            width=widths,
            marker=dict(color="#E11D48", opacity=0.82),
            customdata=labels,
            hovertemplate="Anomaly score %{customdata}<br>Records: %{y:,}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Anomaly score (higher = more unusual)")
    figure.update_yaxes(title="Records")
    return _apply(figure)


def anomaly_ratio_pie(anomalies: int, total: int) -> go.Figure:
    normal = max(total - anomalies, 0)
    figure = go.Figure(
        go.Pie(
            labels=["Normal", "Flagged"],
            values=[normal, anomalies],
            hole=0.68,
            marker=dict(colors=["#E2E8F0", "#E11D48"], line=dict(color="#fff", width=2)),
            textinfo="none",
            hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
        )
    )
    figure.add_annotation(
        text=f"<b>{anomalies:,}</b><br><span style='font-size:11px;color:#64748B'>flagged</span>",
        showarrow=False,
        font=dict(size=20, color="#0F172A"),
    )
    return _apply(figure, height=260)


def missing_values_bar(columns: list[dict[str, Any]], limit: int = 12) -> go.Figure:
    ordered = sorted(columns, key=lambda item: item.get("missing_percentage", 0), reverse=True)[
        :limit
    ]
    ordered = [item for item in ordered if item.get("missing_percentage", 0) > 0]
    if not ordered:
        return _empty_chart("No missing values detected")
    figure = go.Figure(
        go.Bar(
            x=[item["missing_percentage"] for item in ordered],
            y=[html.escape(str(item["name"])) for item in ordered],
            orientation="h",
            marker=dict(color="#F59E0B", opacity=0.85),
            hovertemplate="%{y}<br>Missing: %{x:.2f}%<extra></extra>",
        )
    )
    figure.update_xaxes(title="Missing values (%)")
    figure.update_layout(yaxis=dict(autorange="reversed"))
    return _apply(figure, height=max(240, 28 * len(ordered) + 80))


def severity_bar(anomalies: list[dict[str, Any]], limit: int = 10) -> go.Figure:
    top = anomalies[:limit]
    if not top:
        return _empty_chart("No anomalies to display")
    labels = [f"Row {item['row_number']}" for item in reversed(top)]
    scores = [item["anomaly_score"] for item in reversed(top)]
    figure = go.Figure(
        go.Bar(
            x=scores,
            y=labels,
            orientation="h",
            marker=dict(color="#E11D48", opacity=0.85),
            hovertemplate="%{y}<br>Score: %{x:.4f}<extra></extra>",
        )
    )
    figure.update_xaxes(title="Anomaly score")
    return _apply(figure, height=max(260, 30 * len(top) + 70))


def _empty_chart(message: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(color=_MUTED, size=13),
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return _apply(figure, height=240)
