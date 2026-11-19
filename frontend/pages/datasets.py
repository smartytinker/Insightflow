"""Dataset explorer: upload, inspect, preview and manage datasets."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from components.ui import (
    callout,
    empty_state,
    format_bytes,
    format_datetime,
    format_number,
    format_percentage,
    kv_row,
    metric_card,
    page_header,
    section_header,
    show_api_error,
    status_badge,
)
from services import get_client
from services.api_client import ApiError

client = get_client()

page_header(
    "Datasets",
    "Upload validated CSVs, inspect schema and quality, and preview rows before analysis.",
    "Data explorer",
)

MAX_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "25"))

upload_col, sample_col = st.columns([1.6, 1])

with upload_col, st.container(border=True):
    st.markdown("#### Upload a CSV")
    st.caption(
        f"UTF-8 or Latin-1 text CSV · up to {MAX_MB} MB · headers required · "
        "original files are preserved."
    )
    uploaded_file = st.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        size = uploaded_file.size
        if size > MAX_MB * 1024 * 1024:
            st.error(f"This file is {format_bytes(size)}, above the {MAX_MB} MB limit.")
            upload_disabled = True
        else:
            st.caption(f"Selected: **{uploaded_file.name}** · {format_bytes(size)}")
            upload_disabled = False
    else:
        upload_disabled = True

    if st.button("Upload dataset", type="primary", disabled=upload_disabled):
        with st.spinner("Validating and storing your dataset…"):
            try:
                result = client.upload_dataset(uploaded_file.name, uploaded_file.getvalue())
            except ApiError as error:
                show_api_error(error)
            else:
                st.session_state["dataset_id"] = result["dataset"]["id"]
                st.session_state["uploaded_snapshot"] = result
                st.session_state.pop("preview_offset", None)
                st.success(
                    f"Ingested {result['dataset']['original_filename']} — "
                    f"{result['dataset']['row_count']:,} rows × "
                    f"{result['dataset']['column_count']} columns."
                )
                st.rerun()

with sample_col, st.container(border=True):
    st.markdown("#### Try a sample")
    st.caption(
        "Bundled, reproducible datasets include missing values, duplicates and "
        "deliberate outliers so every feature has something to find."
    )
    sample_choice = st.selectbox(
        "Sample dataset",
        options=["sales.csv", "marketing_campaigns.csv"],
        format_func=lambda name: {
            "sales.csv": "Sales · 759 rows",
            "marketing_campaigns.csv": "Marketing · 420 rows",
        }[name],
        label_visibility="collapsed",
    )
    if st.button("Load sample", width="stretch"):
        try:
            content = client.load_sample(sample_choice)
            with st.spinner("Uploading sample dataset…"):
                result = client.upload_dataset(sample_choice, content)
        except FileNotFoundError:
            st.warning(
                "Bundled sample data is not available in this deployment. "
                "Upload a CSV file instead.",
                icon="📂",
            )
        except ApiError as error:
            show_api_error(error)
        else:
            st.session_state["dataset_id"] = result["dataset"]["id"]
            st.session_state["uploaded_snapshot"] = result
            st.session_state.pop("preview_offset", None)
            st.success(f"Sample **{sample_choice}** loaded.")
            st.rerun()

snapshot = st.session_state.get("uploaded_snapshot")
if snapshot:
    st.write("")
    section_header("Ingestion quality snapshot", snapshot["dataset"]["original_filename"])
    cols = st.columns(4)
    with cols[0]:
        metric_card(
            "Rows",
            format_number(snapshot["dataset"]["row_count"]),
            "Parsed records",
            "🧾",
            "indigo",
        )
    with cols[1]:
        metric_card(
            "Columns",
            format_number(snapshot["dataset"]["column_count"]),
            "Detected fields",
            "🧱",
            "teal",
        )
    with cols[2]:
        metric_card(
            "Missing cells",
            format_number(snapshot["quality"]["missing_cells"]),
            format_percentage(snapshot["quality"]["missing_percentage"]),
            "🩹",
            "amber",
        )
    with cols[3]:
        metric_card(
            "Duplicate rows",
            format_number(snapshot["quality"]["duplicate_rows"]),
            "Exact duplicates detected",
            "🧬",
            "rose",
        )
    with st.expander("Detected columns"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Column": item["name"],
                        "Type": item["dtype"],
                        "Kind": item["kind"],
                        "Missing": item["missing_count"],
                        "Unique": item["unique_count"],
                        "Samples": ", ".join(str(value) for value in item["sample_values"][:3]),
                    }
                    for item in snapshot["columns"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )

st.write("")
try:
    datasets = client.list_datasets()
except ApiError as error:
    show_api_error(error)
    st.stop()

section_header("Dataset library", f"{len(datasets)} dataset(s) in this workspace")

if not datasets:
    empty_state(
        "No datasets yet",
        "Upload your own CSV or load a bundled sample above. Validation happens before "
        "anything is persisted.",
        "📂",
    )
    st.stop()

library = pd.DataFrame(
    [
        {
            "Dataset": item["original_filename"],
            "Rows": item["row_count"],
            "Columns": item["column_count"],
            "Status": item["processing_status"].title(),
            "Uploaded": format_datetime(item["upload_timestamp"]),
        }
        for item in datasets
    ]
)
st.dataframe(
    library,
    hide_index=True,
    width="stretch",
    column_config={
        "Rows": st.column_config.NumberColumn(format="%d"),
        "Columns": st.column_config.NumberColumn(format="%d"),
    },
)

ids = [item["id"] for item in datasets]
current = st.session_state.get("dataset_id")
if current not in ids:
    current = ids[0]
    st.session_state["dataset_id"] = current

selected_id = st.selectbox(
    "Inspect dataset",
    options=ids,
    index=ids.index(current),
    format_func=lambda value: next(
        f"{item['original_filename']} · {item['row_count']:,} rows · {item['id'][:8]}"
        for item in datasets
        if item["id"] == value
    ),
)
if selected_id != current:
    st.session_state["dataset_id"] = selected_id
    st.session_state.pop("preview_offset", None)
    st.session_state.pop("uploaded_snapshot", None)
    st.rerun()

try:
    detail = client.get_dataset(selected_id)
except ApiError as error:
    show_api_error(error)
    st.stop()

st.write("")
section_header("Dataset details", detail["original_filename"])

meta_col, quality_col = st.columns([1.05, 1])

with meta_col, st.container(border=True):
    rows = [
        ("Dataset ID", detail["id"]),
        ("File size", format_bytes(detail["file_size"])),
        ("Original rows", format_number(detail["row_count"])),
        ("Columns", format_number(detail["column_count"])),
        ("Active version", "Cleaned copy" if detail["is_cleaned"] else "Original upload"),
        ("Active rows", format_number(detail.get("cleaned_row_count") or detail["row_count"])),
        ("Uploaded", format_datetime(detail["upload_timestamp"])),
        ("SHA-256", (detail.get("checksum") or "—")[:16] + "…"),
    ]
    st.markdown(
        "".join(kv_row(label, str(value)) for label, value in rows),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin-top:.7rem">{status_badge(detail["processing_status"])}</div>',
        unsafe_allow_html=True,
    )

with quality_col, st.container(border=True):
    st.markdown("**Column schema**")
    columns_frame = pd.DataFrame(
        [
            {
                "Column": column["name"],
                "Kind": column["kind"].title(),
                "Type": column["dtype"],
                "Missing": column["missing_count"],
                "Unique": column["unique_count"],
            }
            for column in detail["columns"]
        ]
    )
    st.dataframe(
        columns_frame,
        hide_index=True,
        width="stretch",
        height=260,
        column_config={
            "Missing": st.column_config.NumberColumn(format="%d"),
            "Unique": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.caption("Double-click a cell to inspect it. Missing values come from ingestion metadata.")

st.write("")
with st.spinner("Computing data quality profile…"):
    try:
        profile = client.profile(selected_id)
    except ApiError as error:
        profile = None
        st.warning(f"Profile unavailable: {error.message}")

if profile:
    quality = profile["quality"]
    cols = st.columns(4)
    with cols[0]:
        metric_card(
            "Missing cells",
            format_number(quality["missing_cells"]),
            format_percentage(quality["missing_percentage"]),
            "🩹",
            "amber",
        )
    with cols[1]:
        metric_card(
            "Duplicate rows",
            format_number(quality["duplicate_rows"]),
            "Exact row matches",
            "🧬",
            "rose",
        )
    with cols[2]:
        metric_card(
            "Numeric columns",
            format_number(profile["overview"]["numeric_column_count"]),
            "Eligible for ML",
            "🔢",
            "indigo",
        )
    with cols[3]:
        metric_card(
            "Time coverage",
            format_number(len(profile["datetime_columns"])),
            "Datetime columns detected",
            "📅",
            "teal",
        )

    if profile["quality_issues"]:
        with st.expander(f"Data quality observations ({len(profile['quality_issues'])})"):
            for issue in profile["quality_issues"]:
                st.markdown(f"- {issue}")

section_header("Row preview", "Paginated preview of the active dataset version")
page_size = 20
offset = int(st.session_state.get("preview_offset", 0))
try:
    preview = client.preview(selected_id, limit=page_size, offset=offset)
except ApiError as error:
    show_api_error(error)
    st.stop()

if preview["rows"]:
    frame = pd.DataFrame(preview["rows"])
    st.dataframe(frame, hide_index=True, width="stretch", height=430)
    start = offset + 1
    end = offset + len(preview["rows"])
    nav_left, nav_mid, nav_right = st.columns([1, 2, 1])
    with nav_left:
        if st.button("← Previous", disabled=offset == 0, width="stretch"):
            st.session_state["preview_offset"] = max(0, offset - page_size)
            st.rerun()
    with nav_mid:
        st.caption(
            f"Showing {start:,}–{end:,} of {preview['total_rows']:,} rows "
            f"· source: {preview['source']}"
        )
    with nav_right:
        if st.button(
            "Next →",
            disabled=end >= preview["total_rows"],
            width="stretch",
        ):
            st.session_state["preview_offset"] = offset + page_size
            st.rerun()
else:
    st.info("This dataset currently has no rows to preview.")

section_header("Danger zone")
with st.expander("Delete this dataset"):
    callout(
        "Deleting removes the uploaded file, cleaned copy, analysis results, anomaly runs "
        "and chat history. This cannot be undone.",
        "danger",
        "⚠️",
    )
    confirm = st.checkbox("I understand this permanently deletes the dataset and its analyses.")
    if st.button("Delete dataset", type="primary", disabled=not confirm):
        try:
            client.delete_dataset(selected_id)
        except ApiError as error:
            show_api_error(error)
        else:
            for key in (
                "dataset_id",
                "uploaded_snapshot",
                "preview_offset",
                "chat_session_id",
                "anomaly_result",
            ):
                st.session_state.pop(key, None)
            st.success("Dataset deleted.")
            st.rerun()
