"""Isolation Forest anomaly detection UI."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from components.charts import anomaly_ratio_pie, anomaly_scores, severity_bar
from components.ui import (
    callout,
    chips,
    format_number,
    format_percentage,
    kv_row,
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
    "Anomaly Detection",
    "Surface unusual multivariate records with Isolation Forest. Results are statistical "
    "outliers — never proof of fraud or invalid data.",
    "Machine learning",
)

numeric_columns = [column["name"] for column in dataset["columns"] if column["kind"] == "numeric"]

if not numeric_columns:
    callout(
        "This dataset has no numeric columns. Anomaly detection needs at least one numeric "
        "feature with variation. Convert a column in Data Cleaning first.",
        "warn",
        "⚠️",
    )
    st.stop()

# Load the latest persisted run once per session.
if "anomaly_result" not in st.session_state:
    try:
        st.session_state["anomaly_result"] = client.latest_anomalies(dataset_id)
    except ApiError as error:
        if error.status_code == 400:
            st.session_state["anomaly_result"] = None
        else:
            show_api_error(error)

config_col, result_col = st.columns([1, 1.9])

with config_col:
    st.markdown("#### Model configuration")
    with st.form("anomaly_form", border=True):
        contamination = st.slider(
            "Contamination (expected outlier share)",
            min_value=0.01,
            max_value=0.25,
            value=0.05,
            step=0.01,
            help="Lower values flag fewer records. Isolation Forest uses this as a prior.",
        )
        n_estimators = st.selectbox("Trees", options=[100, 200, 300], index=0)
        random_state = st.number_input(
            "Random seed", min_value=0, max_value=100000, value=42, step=1
        )
        features = st.multiselect(
            "Numeric features",
            options=numeric_columns,
            default=numeric_columns,
            help="Only numeric columns with variation are used. Missing values are median-imputed.",
        )
        run = st.form_submit_button("Run detection", type="primary", width="stretch")

    callout(
        "The model learns the shape of normal numeric behavior. It does not use labels, "
        "and accuracy cannot be measured without ground truth.",
        "info",
        "🧪",
    )

    if run:
        if not features:
            st.error("Select at least one numeric feature.")
        else:
            with st.spinner("Training Isolation Forest and scoring records…"):
                try:
                    result = client.run_anomalies(
                        dataset_id,
                        {
                            "contamination": contamination,
                            "n_estimators": n_estimators,
                            "random_state": int(random_state),
                            "features": features,
                        },
                    )
                except ApiError as error:
                    show_api_error(error)
                else:
                    st.session_state["anomaly_result"] = result
                    st.success(f"Detected {result['anomalies_detected']:,} anomalous records.")
                    st.rerun()

result = st.session_state.get("anomaly_result")

with result_col:
    if not result:
        st.markdown("#### Results")
        st.markdown(
            """
            <div class="if-empty" style="padding:2rem 1.5rem">
              <div class="if-empty-icon">🎯</div>
              <h3>No detection run yet</h3>
              <p>Choose a contamination rate and run the model. Results are persisted and
              can be downloaded as a CSV report.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("#### Detection summary")
        summary_cols = st.columns(3)
        with summary_cols[0]:
            metric_card(
                "Records analyzed",
                format_number(result["records_analyzed"]),
                f"of {format_number(result['total_records'])} total",
                "🧾",
                "indigo",
            )
        with summary_cols[1]:
            metric_card(
                "Anomalies",
                format_number(result["anomalies_detected"]),
                format_percentage(result["anomaly_percentage"]),
                "🎯",
                "rose",
            )
        with summary_cols[2]:
            metric_card(
                "Features",
                format_number(len(result["features"])),
                f"{result['n_estimators']} trees · seed {result['random_state']}",
                "🔢",
                "teal",
            )

        st.markdown(
            f'<div style="margin:.2rem 0 .7rem;font-size:.78rem;color:#64748B">'
            f"Source: {result['source']} · contamination "
            f"{format_percentage(result['contamination'] * 100)}</div>",
            unsafe_allow_html=True,
        )
        chips(result["features"], "indigo")

        st.write("")
        st.markdown(
            f"""
            <div class="if-card" style="margin:.6rem 0">
              <h4>What the model found</h4>
              <p style="font-size:.85rem">{html.escape(result["interpretation"])}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        callout(result["disclaimer"], "warn", "⚠️")

        chart_left, chart_right = st.columns([1.4, 1])
        with chart_left:
            section_header("Score distribution")
            st.plotly_chart(
                anomaly_scores(result["score_distribution"]),
                width="stretch",
                config={"displayModeBar": False},
            )
        with chart_right:
            section_header("Share flagged")
            st.plotly_chart(
                anomaly_ratio_pie(result["anomalies_detected"], result["total_records"]),
                width="stretch",
                config={"displayModeBar": False},
            )

        section_header("Highest-scoring records")
        anomalies = result["anomalies"]
        if anomalies:
            st.plotly_chart(
                severity_bar(anomalies),
                width="stretch",
                config={"displayModeBar": False},
            )

            rows = []
            for anomaly in anomalies[:200]:
                row = {
                    "Rank": anomaly["rank"],
                    "Row": anomaly["row_number"],
                    "Score": anomaly["anomaly_score"],
                }
                row.update(anomaly["values"])
                rows.append(row)
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
                height=420,
            )
            if result.get("anomalies_truncated"):
                st.caption(f"Showing the first 200 of {len(anomalies):,} stored anomaly records.")

            try:
                csv_bytes, filename = client.download_anomalies_csv(dataset_id)
                st.download_button(
                    "Download anomaly report (CSV)",
                    data=csv_bytes,
                    file_name=filename,
                    mime="text/csv",
                    width="stretch",
                )
            except ApiError as error:
                st.caption(f"CSV export unavailable: {error.message}")
        else:
            st.info("No records were flagged with this configuration.", icon="ℹ️")

st.write("")
with st.expander("Model details and run history"):
    if result:
        details = [
            ("Model", "Isolation Forest (scikit-learn)"),
            ("Contamination", format_percentage(result["contamination"] * 100)),
            ("Estimators", format_number(result["n_estimators"])),
            ("Random state", str(result["random_state"])),
            ("Rows excluded", format_number(result["records_excluded"])),
            ("Preprocessing", "Median imputation + StandardScaler"),
            ("Generated", result["generated_at"]),
        ]
        st.markdown(
            "".join(kv_row(label, value) for label, value in details),
            unsafe_allow_html=True,
        )
        st.caption(
            "Anomaly score is the negated Isolation Forest decision function: "
            "higher means more unusual."
        )
    try:
        history = client.anomaly_history(dataset_id)
    except ApiError as error:
        show_api_error(error)
    else:
        items = history["items"]
        if items:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Run": item["id"],
                            "Records": item["total_records"],
                            "Anomalies": item["anomalies_detected"],
                            "Share %": item["anomaly_percentage"],
                            "Contamination": item["contamination"],
                            "Features": ", ".join(item["features"]),
                            "Created": item["created_at"],
                        }
                        for item in items
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No anomaly runs recorded yet.")
