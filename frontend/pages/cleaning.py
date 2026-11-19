"""Data cleaning configuration, results and history."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
from components.ui import (
    callout,
    format_number,
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
    "Data Cleaning",
    "Build a reproducible cleaning recipe. InsightFlow always starts from the untouched "
    "original upload and writes a separate cleaned copy.",
    "Quality workspace",
)

if dataset["is_cleaned"]:
    callout(
        f"A cleaned copy is active ({dataset.get('cleaned_row_count', 0):,} rows). "
        "Running a new recipe replaces the cleaned copy but never changes the original upload.",
        "info",
        "🧼",
    )

columns = dataset["columns"]
column_names = [column["name"] for column in columns]
numeric_names = [column["name"] for column in columns if column["kind"] == "numeric"]
missing_names = [column["name"] for column in columns if column["missing_count"] > 0]

status_cols = st.columns(3)
with status_cols[0]:
    metric_card(
        "Original rows",
        format_number(dataset["row_count"]),
        "Immutable upload",
        "🔒",
        "indigo",
    )
with status_cols[1]:
    metric_card(
        "Active rows",
        format_number(dataset.get("cleaned_row_count") or dataset["row_count"]),
        "Used for analytics",
        "📄",
        "teal",
    )
with status_cols[2]:
    metric_card(
        "Columns with gaps",
        format_number(len(missing_names)),
        "Missing values detected",
        "🩹",
        "amber",
    )

st.write("")
section_header("Cleaning recipe", "Configure once, then run against the original data")

strategy_labels = {
    "none": "Leave missing values as-is",
    "drop_rows": "Drop rows with missing values",
    "fill_mean": "Fill with column mean (numeric)",
    "fill_median": "Fill with column median (numeric)",
    "fill_mode": "Fill with most frequent value",
    "fill_constant": "Fill with a constant value",
    "fill_zero": "Fill with zero",
}
type_options = ["", "numeric", "datetime", "string", "category", "boolean"]

with st.form("cleaning_form", border=True):
    basic_left, basic_right = st.columns(2)
    with basic_left:
        drop_duplicates = st.checkbox("Remove duplicate rows", value=True)
        missing_strategy = st.selectbox(
            "Global missing-value strategy",
            options=list(strategy_labels),
            format_func=lambda key: strategy_labels[key],
            index=0,
        )
        fill_value = st.text_input(
            "Constant fill value",
            placeholder="Only used when the strategy is 'Fill with a constant value'",
            disabled=missing_strategy != "fill_constant",
        )
    with basic_right:
        normalize_columns = st.checkbox("Normalize column names", value=True)
        column_case = st.selectbox(
            "Column name style",
            options=["snake", "lower", "preserve"],
            format_func=lambda value: {
                "snake": "snake_case (recommended)",
                "lower": "lowercase only",
                "preserve": "preserve original",
            }[value],
        )
        drop_columns = st.multiselect("Drop columns", options=column_names)

    if missing_names:
        with st.expander("Per-column missing-value overrides", expanded=False):
            st.caption("Overrides take precedence over the global strategy.")
            overrides: dict[str, str] = {}
            override_columns = st.columns(min(2, len(missing_names)))
            for index, name in enumerate(missing_names[:20]):
                with override_columns[index % len(override_columns)]:
                    choice = st.selectbox(
                        name,
                        options=[
                            "use_global",
                            "none",
                            "drop_rows",
                            "fill_mean",
                            "fill_median",
                            "fill_mode",
                            "fill_zero",
                        ],
                        format_func=lambda value: (
                            "Use global" if value == "use_global" else strategy_labels[value]
                        ),
                        key=f"missing_override_{name}",
                    )
                if choice != "use_global":
                    overrides[name] = choice
    else:
        overrides = {}

    with st.expander("Type conversions", expanded=False):
        conversion_frame = pd.DataFrame(
            {"column": column_names, "target_type": ["" for _ in column_names]}
        )
        edited = st.data_editor(
            conversion_frame,
            hide_index=True,
            width="stretch",
            height=230,
            disabled=["column"],
            column_config={
                "column": st.column_config.TextColumn("Column"),
                "target_type": st.column_config.SelectboxColumn(
                    "Convert to", options=type_options, required=False
                ),
            },
            key="cleaning_type_conversions",
        )
        type_conversions = {
            row["column"]: row["target_type"] for _, row in edited.iterrows() if row["target_type"]
        }
        if type_conversions:
            st.caption(f"{len(type_conversions)} column(s) will be converted.")

    with st.expander("Outlier handling", expanded=False):
        outlier_left, outlier_right = st.columns([1, 1.4])
        with outlier_left:
            outlier_action = st.selectbox(
                "Action",
                options=["none", "clip", "remove"],
                format_func=lambda value: {
                    "none": "Leave outliers unchanged",
                    "clip": "Clip values to IQR bounds",
                    "remove": "Remove rows containing outliers",
                }[value],
            )
            iqr_multiplier = st.number_input(
                "IQR multiplier", min_value=0.5, max_value=10.0, value=1.5, step=0.1
            )
        with outlier_right:
            outlier_columns = st.multiselect(
                "Numeric columns to inspect",
                options=numeric_names,
                disabled=outlier_action == "none",
                help="Leave empty to check every numeric column.",
            )

    submitted = st.form_submit_button("Run cleaning", type="primary", width="stretch")

if submitted:
    payload: dict[str, Any] = {
        "drop_duplicates": drop_duplicates,
        "missing_strategy": missing_strategy,
        "normalize_columns": normalize_columns,
        "column_case": column_case,
        "drop_columns": drop_columns,
        "column_strategies": overrides,
        "type_conversions": type_conversions,
        "outlier_action": outlier_action,
        "outlier_columns": outlier_columns,
        "outlier_iqr_multiplier": float(iqr_multiplier),
    }
    if missing_strategy == "fill_constant" and fill_value.strip():
        raw = fill_value.strip()
        try:
            parsed: Any = float(raw) if "." in raw else int(raw)
        except ValueError:
            parsed = raw
        payload["fill_value"] = parsed

    with st.spinner("Applying the cleaning recipe to a new copy…"):
        try:
            summary = client.clean(dataset_id, payload)
        except ApiError as error:
            show_api_error(error)
        else:
            st.session_state["cleaning_summary"] = summary
            st.success("Cleaning completed. The active dataset now uses the cleaned copy.")
            st.rerun()

summary = st.session_state.get("cleaning_summary")
if summary and summary.get("dataset_id") == dataset_id:
    st.write("")
    section_header("Before and after", "Results recorded for this run")

    result_cols = st.columns(4)
    with result_cols[0]:
        metric_card(
            "Rows",
            format_number(summary["final_row_count"]),
            f"was {format_number(summary['original_row_count'])}",
            "🧾",
            "indigo",
        )
    with result_cols[1]:
        metric_card(
            "Missing cells",
            format_number(summary["missing_values_after"]),
            f"filled {format_number(summary['missing_values_filled'])}",
            "🩹",
            "amber",
        )
    with result_cols[2]:
        metric_card(
            "Duplicates removed",
            format_number(summary["duplicates_removed"]),
            "Exact row matches",
            "🧬",
            "rose",
        )
    with result_cols[3]:
        metric_card(
            "Columns transformed",
            format_number(len(summary["columns_transformed"])),
            "Renamed or converted",
            "🧱",
            "teal",
        )

    if summary["warnings"]:
        with st.expander(f"Warnings ({len(summary['warnings'])})", expanded=True):
            for warning in summary["warnings"]:
                st.warning(warning, icon="⚠️")

    before_tab, after_tab, log_tab = st.tabs(["Before", "After", "Operation log"])
    with before_tab:
        st.caption("First 5 rows of the original upload")
        st.dataframe(pd.DataFrame(summary["before_preview"]), hide_index=True, width="stretch")
    with after_tab:
        st.caption("First 5 rows of the cleaned copy")
        st.dataframe(pd.DataFrame(summary["after_preview"]), hide_index=True, width="stretch")
    with log_tab:
        operations = pd.DataFrame(
            [
                {
                    "Operation": operation["operation_type"].replace("_", " ").title(),
                    "Records affected": operation["records_affected"],
                    "Details": str(operation["operation_details"]),
                    "When": operation["created_at"],
                }
                for operation in summary["operations"]
            ]
        )
        st.dataframe(operations, hide_index=True, width="stretch")

st.write("")
section_header("Cleaning history", "Every run is persisted with the operations it applied")
try:
    history = client.cleaning_history(dataset_id)
except ApiError as error:
    show_api_error(error)
else:
    operations = history["operations"]
    if not operations:
        st.caption("No cleaning operations have been recorded for this dataset yet.")
    else:
        history_frame = pd.DataFrame(
            [
                {
                    "Operation": operation["operation_type"].replace("_", " ").title(),
                    "Records affected": operation["records_affected"],
                    "Details": str(operation["operation_details"]),
                    "Recorded": operation["created_at"],
                }
                for operation in operations
            ]
        )
        st.dataframe(history_frame, hide_index=True, width="stretch")
        st.caption(
            "Runs always start from the original upload. History is append-only for auditing."
        )
