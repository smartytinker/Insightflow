"""Exploratory analytics with interactive Plotly charts."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components.charts import (
    box_plot,
    category_bar,
    correlation_heatmap,
    histogram,
    missing_values_bar,
    time_series,
)
from components.ui import (
    callout,
    chips,
    format_decimal,
    format_number,
    format_percentage,
    metric_card,
    page_header,
    require_dataset,
    section_header,
    show_api_error,
)
from services import get_client
from services.api_client import ApiError

client = get_client()
dataset = require_dataset(client)
dataset_id = dataset["id"]

page_header(
    "Analytics",
    "Automatically profiled statistics, distributions and correlations — computed by pandas "
    "from the active version of your data.",
    "Exploratory analysis",
)

controls_left, controls_right = st.columns([3, 1])
with controls_right:
    refresh = st.button("Recompute profile", width="stretch")

with st.spinner("Profiling your dataset…"):
    try:
        profile = client.profile(dataset_id, refresh=refresh)
    except ApiError as error:
        show_api_error(error)
        st.stop()

if refresh:
    st.success("Profile recomputed from the active dataset.")

overview = profile["overview"]
quality = profile["quality"]

metric_cols = st.columns(4)
with metric_cols[0]:
    metric_card(
        "Rows", format_number(overview["row_count"]), profile["source"] + " version", "🧾", "indigo"
    )
with metric_cols[1]:
    metric_card(
        "Columns",
        format_number(overview["column_count"]),
        f"{overview['numeric_column_count']} numeric",
        "🧱",
        "teal",
    )
with metric_cols[2]:
    metric_card(
        "Missing",
        format_percentage(overview["missing_percentage"]),
        f"{format_number(overview['missing_cells'])} cells",
        "🩹",
        "amber",
    )
with metric_cols[3]:
    metric_card(
        "Duplicates", format_number(overview["duplicate_rows"]), "Exact row matches", "🧬", "rose"
    )

tabs = st.tabs(["Summary", "Numeric", "Categorical", "Correlations", "Time series", "Data quality"])

with tabs[0]:
    st.write("")
    st.markdown(
        f"""
        <div class="if-card" style="margin-bottom:1rem">
          <div style="font-size:.7rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
                      color:#4F46E5;margin-bottom:.4rem">Automated dataset summary</div>
          <div style="font-size:.9rem;line-height:1.7;color:#1E293B">{html.escape(profile["summary"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1])
    with left:
        section_header("Important columns")
        if profile["important_columns"]:
            chips(profile["important_columns"], "indigo")
        else:
            st.caption("No standout columns detected.")

        section_header("Column inventory")
        inventory_rows = []
        for kind, items in (
            ("Numeric", profile["numeric_columns"]),
            ("Categorical", profile["categorical_columns"]),
            ("Datetime", profile["datetime_columns"]),
        ):
            for item in items:
                inventory_rows.append(
                    {
                        "Column": item["name"],
                        "Kind": kind,
                        "Non-null": item["count"],
                        "Missing %": item["missing_percentage"],
                        "Unique": (str(item["unique_count"]) if "unique_count" in item else "—"),
                    }
                )
        inventory = pd.DataFrame(inventory_rows)
        st.dataframe(
            inventory,
            hide_index=True,
            width="stretch",
            height=320,
            column_config={
                "Missing %": st.column_config.ProgressColumn(
                    "Missing %", min_value=0, max_value=100, format="%.2f%%"
                ),
            },
        )
    with right:
        section_header("Quality observations")
        if profile["quality_issues"]:
            for issue in profile["quality_issues"]:
                st.markdown(
                    f'<div class="if-callout warn" style="margin-bottom:.45rem">'
                    f'<div class="if-callout-icon">⚠️</div><div>{html.escape(issue)}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            callout("No major data quality issues were detected.", "success", "✅")
        if profile["top_correlations"]:
            top = profile["top_correlations"][0]
            st.caption(
                f"Strongest association: {top['column_a']} ↔ {top['column_b']} "
                f"(r = {top['correlation']:.3f})."
            )

with tabs[1]:
    st.write("")
    numeric = profile["numeric_columns"]
    if not numeric:
        st.info("No numeric columns were detected in this dataset.", icon="ℹ️")
    else:
        names = [item["name"] for item in numeric]
        selected = st.selectbox("Numeric column", names, key="analytics_numeric_column")
        stats = next(item for item in numeric if item["name"] == selected)

        stats_cols = st.columns(4)
        with stats_cols[0]:
            metric_card(
                "Mean",
                format_decimal(stats["mean"]),
                f"median {format_decimal(stats['median'])}",
                "📐",
                "indigo",
            )
        with stats_cols[1]:
            metric_card(
                "Std. deviation",
                format_decimal(stats["std"]),
                f"{format_number(stats['count'])} values",
                "📏",
                "teal",
            )
        with stats_cols[2]:
            metric_card(
                "Minimum",
                format_decimal(stats["minimum"]),
                f"Q1 {format_decimal(stats['q1'])}",
                "⬇️",
                "amber",
            )
        with stats_cols[3]:
            metric_card(
                "Maximum",
                format_decimal(stats["maximum"]),
                f"Q3 {format_decimal(stats['q3'])}",
                "⬆️",
                "rose",
            )

        chart_left, chart_right = st.columns([1.55, 1])
        with chart_left:
            section_header("Distribution", "Binned counts from non-null values")
            st.plotly_chart(histogram(stats), width="stretch", config={"displayModeBar": False})
        with chart_right:
            section_header("Spread", "Quartiles and IQR-derived whiskers")
            st.plotly_chart(box_plot(stats), width="stretch", config={"displayModeBar": False})
            st.caption(
                f"IQR {format_decimal(stats['iqr'])} · "
                f"{format_number(stats['outlier_count'])} IQR outlier(s) · "
                f"missing {format_percentage(stats['missing_percentage'])}"
            )

with tabs[2]:
    st.write("")
    categorical = profile["categorical_columns"]
    if not categorical:
        st.info("No categorical columns were detected.", icon="ℹ️")
    else:
        names = [item["name"] for item in categorical]
        selected = st.selectbox("Categorical column", names, key="analytics_categorical_column")
        stats = next(item for item in categorical if item["name"] == selected)
        chart_col, table_col = st.columns([1.5, 1])
        with chart_col:
            section_header("Top values", f"{stats['unique_count']:,} distinct values")
            st.plotly_chart(category_bar(stats), width="stretch", config={"displayModeBar": False})
        with table_col:
            section_header("Frequency table")
            frame = pd.DataFrame(stats["top_values"])
            frame.columns = ["Value", "Records", "Share %"]
            st.dataframe(frame, hide_index=True, width="stretch")
            st.caption(
                f"{stats['count']:,} non-null · "
                f"{format_percentage(stats['missing_percentage'])} missing"
            )

with tabs[3]:
    st.write("")
    if not profile["correlations"]:
        st.info("At least two varying numeric columns are required for correlations.", icon="ℹ️")
    else:
        section_header("Pearson correlation matrix", "−1 negative · 0 none · +1 positive")
        st.plotly_chart(
            correlation_heatmap(profile["correlations"]),
            width="stretch",
            config={"displayModeBar": False},
        )
        if profile["top_correlations"]:
            section_header("Strongest associations")
            pairs = pd.DataFrame(profile["top_correlations"])
            pairs.columns = ["Column A", "Column B", "Correlation", "Strength"]
            st.dataframe(pairs, hide_index=True, width="stretch")
        callout(
            "Correlation describes association, not causation. These coefficients are "
            "calculated from non-null pairs in the active dataset.",
            "info",
            "🧠",
        )

with tabs[4]:
    st.write("")
    series = profile["time_series"]
    if not series:
        st.info(
            "No datetime column was detected. Convert a date column in Data Cleaning to "
            "unlock time-series charts.",
            icon="📅",
        )
    else:
        section_header(
            f"{series['aggregation'].title()} of {series['metric_column']}",
            f"{series['date_column']} · {series['granularity']} · {len(series['points'])} points",
        )
        st.plotly_chart(time_series(series), width="stretch", config={"displayModeBar": False})
        points = series["points"]
        if points:
            values = [point["value"] for point in points if point["value"] is not None]
            peak = max(points, key=lambda point: point["value"] or 0)
            metric_cols = st.columns(3)
            with metric_cols[0]:
                metric_card(
                    "Periods", format_number(len(points)), "Observed intervals", "🗓️", "indigo"
                )
            with metric_cols[1]:
                metric_card(
                    "Peak period",
                    peak["period"],
                    f"value {format_decimal(peak['value'])}",
                    "⛰️",
                    "teal",
                )
            with metric_cols[2]:
                metric_card(
                    "Average per period",
                    format_decimal(sum(values) / len(values) if values else None),
                    f"{series['aggregation']} aggregation",
                    "📊",
                    "amber",
                )

with tabs[5]:
    st.write("")
    left, right = st.columns([1.45, 1])
    with left:
        section_header("Missing values by column")
        st.plotly_chart(
            missing_values_bar(
                [
                    {
                        "name": item["name"],
                        "missing_percentage": item["missing_percentage"],
                    }
                    for item in (
                        profile["numeric_columns"]
                        + profile["categorical_columns"]
                        + profile["datetime_columns"]
                    )
                ]
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
    with right:
        section_header("Quality summary")
        rows = [
            ("Rows", format_number(quality["total_rows"])),
            ("Columns", format_number(quality["total_columns"])),
            ("Missing cells", format_number(quality["missing_cells"])),
            ("Missing share", format_percentage(quality["missing_percentage"])),
            ("Duplicate rows", format_number(quality["duplicate_rows"])),
            ("Columns with gaps", format_number(len(quality["columns_with_missing_values"]))),
        ]
        from components.ui import kv_row

        st.markdown(
            "".join(kv_row(label, value) for label, value in rows),
            unsafe_allow_html=True,
        )
        if quality["columns_with_missing_values"]:
            st.caption(
                "Columns with missing values: " + ", ".join(quality["columns_with_missing_values"])
            )
