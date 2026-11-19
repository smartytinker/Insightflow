"""InsightFlow Streamlit application shell.

Navigation, the global dataset selector and design-system styles live here.
Each page talks to the backend through ``services.api_client``.
"""

from __future__ import annotations

import streamlit as st
from components.ui import badge, inject_styles
from services import get_client, health_snapshot
from services.api_client import ApiError

st.set_page_config(
    page_title="InsightFlow · Data Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_styles()

client = get_client()

# --------------------------------------------------------------------- sidebar

st.logo("assets/logo.svg", size="large")

with st.sidebar:
    api_online = False
    llm_configured = False
    try:
        health = health_snapshot()
        api_online = health.get("status") == "ok"
        llm_configured = bool(health.get("llm_configured"))
    except ApiError:
        api_online = False

    dot_color = "#10B981" if api_online else "#EF4444"
    api_label = "API connected" if api_online else "API unavailable"
    ai_label = "AI provider configured" if llm_configured else "AI provider not configured"
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:.45rem;margin:.1rem 0 .9rem;
                    font-size:.75rem;color:#64748B">
          <span class="if-dot" style="background:{dot_color}"></span>{api_label}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-size:.68rem;font-weight:700;letter-spacing:.12em;'
        'text-transform:uppercase;color:#94A3B8;margin-bottom:.35rem">Active dataset</div>',
        unsafe_allow_html=True,
    )

    datasets: list[dict] = []
    if api_online:
        try:
            datasets = client.list_datasets()
        except ApiError:
            datasets = []

    if datasets:
        ids = [dataset["id"] for dataset in datasets]
        current = st.session_state.get("dataset_id")
        index = ids.index(current) if current in ids else 0
        labels = {
            dataset["id"]: (f"{dataset['original_filename']}  ·  {dataset['row_count']:,} rows")
            for dataset in datasets
        }
        selected = st.selectbox(
            "Dataset",
            options=ids,
            index=index,
            format_func=lambda value: labels.get(value, value),
            label_visibility="collapsed",
        )
        if selected != st.session_state.get("dataset_id"):
            st.session_state["dataset_id"] = selected
            for key in (
                "chat_session_id",
                "anomaly_result",
                "preview_offset",
                "cleaning_summary",
                "uploaded_snapshot",
            ):
                st.session_state.pop(key, None)
            st.rerun()

        selected_meta = next(item for item in datasets if item["id"] == selected)
        status = selected_meta.get("processing_status", "ready")
        tone = "teal" if status in {"ready", "cleaned"} else "slate"
        st.markdown(
            f'<div style="margin:.55rem 0 .2rem">'
            f"{badge(status.replace('_', ' ').title(), tone)}"
            f'<span style="font-size:.7rem;color:#94A3B8;margin-left:.4rem">'
            f"{selected_meta['row_count']:,} × {selected_meta['column_count']} "
            f"· {selected_meta.get('cleaned_row_count') or selected_meta['row_count']:,} active rows"
            f"</span></div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No datasets yet. Upload a CSV to begin.")
        if api_online and st.button("Upload a dataset", type="primary", width="stretch"):
            st.switch_page("pages/datasets.py")

    st.divider()
    st.markdown(
        f"""
        <div style="font-size:.72rem;color:#64748B;line-height:1.7">
          <div style="display:flex;justify-content:space-between">
            <span>AI assistant</span>
            <span style="color:{"#0F766E" if llm_configured else "#B45309"};font-weight:600">
              {"ready" if llm_configured else "calc only"}
            </span>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span>Environment</span><span>local MVP</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin-top:.7rem"><a href="{client.public_base_url}/docs" target="_blank" '
        'style="font-size:.72rem;color:#4F46E5;text-decoration:none">API documentation ↗</a></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="if-footer">InsightFlow v1.0 · Built with FastAPI, pandas & scikit-learn</div>',
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------ navigation

navigation = st.navigation(
    {
        "Workspace": [
            st.Page(
                "pages/overview.py",
                title="Overview",
                icon=":material/space_dashboard:",
                default=True,
            ),
            st.Page("pages/datasets.py", title="Datasets", icon=":material/database:"),
            st.Page(
                "pages/cleaning.py", title="Data Cleaning", icon=":material/cleaning_services:"
            ),
            st.Page("pages/analytics.py", title="Analytics", icon=":material/monitoring:"),
        ],
        "Intelligence": [
            st.Page(
                "pages/anomalies.py", title="Anomaly Detection", icon=":material/troubleshoot:"
            ),
            st.Page("pages/assistant.py", title="AI Assistant", icon=":material/chat_bubble:"),
        ],
        "Output": [
            st.Page("pages/reports.py", title="Reports", icon=":material/download:"),
        ],
    }
)

navigation.run()
