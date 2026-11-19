"""Dashboard overview page."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components.ui import (
    empty_state,
    format_datetime,
    format_number,
    info_card,
    metric_card,
    page_header,
    section_header,
    show_api_error,
)
from services import get_client
from services.api_client import ApiError

client = get_client()

page_header(
    "Overview",
    "A live view of every dataset, analysis and AI conversation in your workspace.",
    "Command center",
)

try:
    overview = client.overview()
except ApiError as error:
    show_api_error(error)
    st.stop()

stats = overview["stats"]
datasets = overview["recent_datasets"]
activity = overview["recent_activity"]

if stats["total_datasets"] == 0:
    empty_state(
        "Your workspace is ready",
        "Upload a CSV to profile data quality, clean records, explore interactive charts, "
        "detect statistical anomalies and ask grounded questions with the AI assistant. "
        "Sample sales and marketing datasets are bundled to help you get started.",
        "🚀",
    )
    left, right = st.columns(2)
    with left:
        info_card(
            "1 · Upload & validate",
            "CSV files are validated, size-limited and stored safely. Original uploads are never modified.",
            "📥",
        )
    with right:
        info_card(
            "2 · Analyze & ask",
            "Every metric is calculated by pandas. The assistant explains results without inventing numbers.",
            "💬",
        )
    st.write("")
    if st.button("Upload your first dataset", type="primary"):
        st.switch_page("pages/datasets.py")
    st.stop()

count_cols = st.columns(4)
with count_cols[0]:
    metric_card(
        "Datasets",
        format_number(stats["total_datasets"]),
        "Uploaded and validated",
        "🗂️",
        "indigo",
    )
with count_cols[1]:
    metric_card(
        "Records analyzed",
        format_number(stats["total_records"]),
        "Rows across all uploads",
        "🧾",
        "teal",
    )
with count_cols[2]:
    metric_card(
        "Anomalies detected",
        format_number(stats["total_anomalies"]),
        "Latest Isolation Forest run per dataset",
        "🎯",
        "rose",
    )
with count_cols[3]:
    metric_card(
        "Assistant messages",
        format_number(stats["total_chat_messages"]),
        f"{stats['total_analyses']:,} analyses cached",
        "💬",
        "amber",
    )

st.write("")
left, right = st.columns([1.65, 1])

with left:
    section_header("Recent activity", "Profiles and anomaly runs persisted by the backend")
    if activity:
        for item in activity:
            icon = {
                "anomaly_detection": "🎯",
                "profile": "📈",
                "statistics": "📊",
            }.get(item["activity_type"], "⚡")
            st.markdown(
                f"""
                <div class="if-card" style="margin-bottom:.55rem;padding:.8rem 1rem">
                  <div class="if-card-row" style="align-items:center">
                    <div class="if-icon-tile">{icon}</div>
                    <div style="flex:1">
                      <div style="font-weight:600;font-size:.86rem">{html.escape(item["dataset_name"])}</div>
                      <div style="color:#64748B;font-size:.78rem">{html.escape(item["description"])}</div>
                    </div>
                    <div style="color:#94A3B8;font-size:.72rem;white-space:nowrap">
                      {format_datetime(item["created_at"])}
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info(
            "No analyses yet. Open Analytics to profile a dataset or run anomaly detection.",
            icon="ℹ️",
        )
        if st.button("Explore analytics", type="primary"):
            st.switch_page("pages/analytics.py")

with right:
    section_header("Workspace")
    st.markdown(
        """
        <div class="if-card" style="margin-bottom:.75rem">
          <h4>Continue where you left off</h4>
          <p>Cleaning preserves originals; anomaly detection scores numeric patterns;
          the assistant grounds every number in pandas calculations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open dataset explorer", width="stretch"):
        st.switch_page("pages/datasets.py")
    if st.button("Review data quality", width="stretch"):
        st.switch_page("pages/cleaning.py")
    if st.button("Ask the assistant", width="stretch"):
        st.switch_page("pages/assistant.py")

section_header("Recent datasets")
frame = pd.DataFrame(
    [
        {
            "Dataset": item["original_filename"],
            "Rows": item["row_count"],
            "Columns": item["column_count"],
            "Status": item["processing_status"].title(),
            "Active rows": item.get("cleaned_row_count") or item["row_count"],
            "Uploaded": format_datetime(item["upload_timestamp"]),
        }
        for item in datasets
    ]
)
st.dataframe(
    frame,
    hide_index=True,
    width="stretch",
    column_config={
        "Rows": st.column_config.NumberColumn(format="%d"),
        "Columns": st.column_config.NumberColumn(format="%d"),
        "Active rows": st.column_config.NumberColumn(format="%d"),
    },
)

st.caption(
    "All values on this page come from persisted dataset and analysis records — "
    "nothing is hardcoded."
)
