"""Reusable UI primitives and the InsightFlow design system."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import streamlit as st
from services.api_client import ApiError, InsightFlowClient

INDIGO = "#4F46E5"
TEAL = "#0D9488"
SKY = "#0284C7"
AMBER = "#D97706"
ROSE = "#E11D48"

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --if-bg: #F6F7FB;
  --if-surface: #FFFFFF;
  --if-ink: #0F172A;
  --if-muted: #64748B;
  --if-border: #E6E9F2;
  --if-primary: #4F46E5;
  --if-primary-soft: #EEF0FF;
  --if-teal: #0D9488;
  --if-teal-soft: #E6F7F5;
  --if-amber: #D97706;
  --if-rose: #E11D48;
  --if-radius: 16px;
  --if-shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.04);
}

html, body, [data-testid="stAppViewContainer"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: var(--if-ink);
}
.stApp {
  background:
    radial-gradient(1200px 500px at 85% -10%, rgba(79,70,229,.07), transparent 60%),
    radial-gradient(900px 400px at 0% 0%, rgba(13,148,136,.05), transparent 55%),
    var(--if-bg);
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3.5rem; max-width: 1240px; }

h1, h2, h3, h4 { color: var(--if-ink); letter-spacing: -0.025em; }
h1 { font-weight: 800; }
h2 { font-weight: 700; }
p, label, span { color: inherit; }
a { color: var(--if-primary); }

/* Sidebar */
[data-testid="stSidebar"] {
  background: #FFFFFF;
  border-right: 1px solid var(--if-border);
}
[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
[data-testid="stSidebarNav"] { padding-top: .35rem; }
[data-testid="stSidebarNav"] a {
  border-radius: 9px;
  padding: .42rem .6rem;
  color: #334155;
  font-weight: 500;
}
[data-testid="stSidebarNav"] a:hover { background: #F4F5FA; }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: var(--if-primary-soft);
  color: var(--if-primary);
  font-weight: 600;
}

/* Header */
.if-brand { display:flex; align-items:center; gap:.7rem; padding:.2rem 0 1.1rem; }
.if-logo {
  width: 38px; height: 38px; border-radius: 11px;
  background: linear-gradient(135deg, #4F46E5 0%, #0EA5E9 100%);
  color:#fff; font-weight:800; font-size:.78rem; letter-spacing:.02em;
  display:flex; align-items:center; justify-content:center;
  box-shadow: 0 6px 16px rgba(79,70,229,.30);
}
.if-brand-name { font-weight: 800; font-size: 1.06rem; line-height:1.1; color: var(--if-ink); }
.if-brand-sub { font-size:.7rem; color: var(--if-muted); letter-spacing:.12em; text-transform:uppercase; }

.if-page-head { margin-bottom: 1.5rem; }
.if-eyebrow {
  display:inline-flex; align-items:center; gap:.35rem;
  font-size:.7rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
  color: var(--if-primary); background: var(--if-primary-soft);
  padding:.3rem .6rem; border-radius:999px; margin-bottom:.7rem;
}
.if-page-title { font-size:1.95rem; font-weight:800; letter-spacing:-.035em; margin:0; line-height:1.15; }
.if-page-sub { color: var(--if-muted); font-size:.92rem; margin-top:.45rem; max-width:760px; line-height:1.55; }

/* Cards */
.if-metric {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: var(--if-radius); padding: 1rem 1.1rem; min-height: 122px;
  box-shadow: var(--if-shadow); position: relative; overflow: hidden;
}
.if-metric::after {
  content:""; position:absolute; inset:0 auto auto 0; width:100%; height:3px;
  background: linear-gradient(90deg, var(--if-primary), #0EA5E9);
  opacity:.85;
}
.if-metric.tone-teal::after { background: linear-gradient(90deg, #0D9488, #22C55E); }
.if-metric.tone-amber::after { background: linear-gradient(90deg, #D97706, #F59E0B); }
.if-metric.tone-rose::after { background: linear-gradient(90deg, #E11D48, #F97316); }
.if-metric-label { font-size:.73rem; font-weight:600; color: var(--if-muted); text-transform:uppercase; letter-spacing:.08em; }
.if-metric-value { font-size:1.8rem; font-weight:800; letter-spacing:-.03em; margin-top:.35rem; line-height:1.05; }
.if-metric-help { font-size:.73rem; color: var(--if-muted); margin-top:.3rem; }
.if-metric-icon { position:absolute; right:1rem; top:1rem; font-size:1rem; opacity:.55; }

.if-card {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: var(--if-radius); padding: 1.15rem 1.25rem; box-shadow: var(--if-shadow);
}
.if-card h4 { margin:0 0 .35rem; font-size:.95rem; }
.if-card p { margin:0; color: var(--if-muted); font-size:.83rem; line-height:1.55; }
.if-card-row { display:flex; gap:1rem; align-items:flex-start; }
.if-icon-tile {
  width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center;
  background: var(--if-primary-soft); color: var(--if-primary); flex:0 0 36px; font-size:1rem;
}

.if-section { margin: 1.6rem 0 .75rem; }
.if-section-title { font-size:1.05rem; font-weight:700; letter-spacing:-.02em; margin:0; }
.if-section-sub { font-size:.8rem; color:var(--if-muted); margin-top:.2rem; }

/* Badges & callouts */
.if-badge {
  display:inline-flex; align-items:center; gap:.3rem; font-size:.7rem; font-weight:600;
  padding:.22rem .55rem; border-radius:999px; border:1px solid transparent; letter-spacing:.01em;
}
.if-badge.indigo { background:#EEF0FF; color:#4338CA; border-color:#E0E3FF; }
.if-badge.teal { background:#E6F7F5; color:#0F766E; border-color:#CCEFEA; }
.if-badge.amber { background:#FFF7E6; color:#B45309; border-color:#FDE9BF; }
.if-badge.rose { background:#FFF0F3; color:#BE123C; border-color:#FFDCE4; }
.if-badge.slate { background:#F1F5F9; color:#475569; border-color:#E2E8F0; }

.if-callout {
  display:flex; gap:.75rem; align-items:flex-start;
  border-radius: 13px; padding:.85rem 1rem; font-size:.83rem; line-height:1.55;
  border:1px solid; background:#fff;
}
.if-callout.info { background:#F5F7FF; border-color:#DDE3FF; color:#3730A3; }
.if-callout.warn { background:#FFFAEB; border-color:#FDE9BF; color:#92400E; }
.if-callout.danger { background:#FFF5F7; border-color:#FFDCE4; color:#9F1239; }
.if-callout.success { background:#F0FDF9; border-color:#CCFBEF; color:#115E59; }
.if-callout .if-callout-icon { font-size:1rem; line-height:1.2; }

.if-empty {
  background: linear-gradient(180deg, #FFFFFF 0%, #FAFBFF 100%);
  border:1px dashed #D8DCEA; border-radius: 18px; padding:2.6rem 2rem;
  text-align:center; box-shadow: var(--if-shadow);
}
.if-empty-icon {
  width:56px; height:56px; border-radius:16px; margin:0 auto .9rem;
  display:flex; align-items:center; justify-content:center;
  background: var(--if-primary-soft); font-size:1.5rem;
}
.if-empty h3 { margin:0 0 .35rem; font-size:1.08rem; }
.if-empty p { margin:0 auto; color:var(--if-muted); font-size:.86rem; max-width:520px; line-height:1.6; }

.if-kv { display:flex; justify-content:space-between; gap:1rem; padding:.42rem 0; border-bottom:1px dashed #EEF1F7; font-size:.82rem; }
.if-kv:last-child { border-bottom:none; }
.if-kv .k { color:var(--if-muted); }
.if-kv .v { font-weight:600; text-align:right; }

.if-chip {
  display:inline-flex; align-items:center; gap:.35rem; padding:.28rem .6rem;
  background:#F8FAFC; border:1px solid var(--if-border); border-radius:8px;
  font-size:.75rem; color:#334155; margin:0 .35rem .35rem 0;
}
.if-dot { width:7px; height:7px; border-radius:999px; display:inline-block; }

/* Streamlit widgets */
.stButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; border:1px solid var(--if-border);
  padding:.48rem .95rem; transition: all .15s ease; font-size:.85rem;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color:#C7CCE0; box-shadow: 0 4px 12px rgba(16,24,40,.06); transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #4F46E5, #4338CA); border: none; color:#fff;
  box-shadow: 0 6px 16px rgba(79,70,229,.25);
}
.stButton > button[kind="primary"]:hover { box-shadow: 0 8px 22px rgba(79,70,229,.32); }

[data-testid="stForm"] {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: var(--if-radius); padding: 1.3rem 1.35rem; box-shadow: var(--if-shadow);
}
[data-testid="stExpander"] {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: 13px; box-shadow: none;
}
[data-testid="stDataFrame"] { border:1px solid var(--if-border); border-radius:12px; overflow:hidden; }
.stTabs [data-baseweb="tab-list"] { gap:.35rem; border-bottom:1px solid var(--if-border); }
.stTabs [data-baseweb="tab"] {
  padding:.55rem .8rem; border-radius:8px 8px 0 0; font-weight:600; font-size:.85rem; color:var(--if-muted);
}
.stTabs [aria-selected="true"] { color:var(--if-primary) !important; background:var(--if-primary-soft); }

[data-testid="stChatMessage"] {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: 14px; padding: .9rem 1rem; box-shadow: var(--if-shadow); margin-bottom:.65rem;
}
[data-testid="stChatInput"] textarea { border-radius: 12px; }

[data-testid="stFileUploader"] {
  background:#FBFCFF; border:1px dashed #C9CFE3; border-radius:14px; padding:.6rem;
}
[data-testid="stMetric"] {
  background: var(--if-surface); border:1px solid var(--if-border);
  border-radius: 14px; padding: .85rem 1rem; box-shadow: var(--if-shadow);
}
[data-testid="stMetricValue"] { font-weight:800; letter-spacing:-.03em; }

.stAlert { border-radius: 12px; }
hr { border-color: var(--if-border); }
.if-footer { text-align:center; color:#94A3B8; font-size:.72rem; padding:2rem 0 .5rem; }
</style>
"""


def inject_styles() -> None:
    """Inject the design system styles into the page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def brand() -> str:
    return """
    <div class="if-brand">
      <div class="if-logo">IF</div>
      <div>
        <div class="if-brand-name">InsightFlow</div>
        <div class="if-brand-sub">Data intelligence</div>
      </div>
    </div>
    """


def page_header(title: str, subtitle: str, eyebrow: str | None = None) -> None:
    """Render a page title block."""
    eyebrow_html = f'<div class="if-eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""
    st.markdown(
        f"""
        <div class="if-page-head">
          {eyebrow_html}
          <h1 class="if-page-title">{html.escape(title)}</h1>
          <div class="if-page-sub">{html.escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str | None = None) -> None:
    subtitle_html = f'<div class="if-section-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="if-section"><div class="if-section-title">{html.escape(title)}</div>'
        f"{subtitle_html}</div>",
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: str,
    help_text: str = "",
    icon: str = "",
    tone: str = "indigo",
) -> None:
    """Render a metric tile with an accent bar."""
    st.markdown(
        f"""
        <div class="if-metric tone-{html.escape(tone)}">
          <div class="if-metric-icon">{icon}</div>
          <div class="if-metric-label">{html.escape(label)}</div>
          <div class="if-metric-value">{html.escape(value)}</div>
          <div class="if-metric-help">{html.escape(help_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "indigo") -> str:
    return f'<span class="if-badge {html.escape(tone)}">{html.escape(text)}</span>'


def status_badge(status: str) -> str:
    mapping = {
        "ready": "teal",
        "uploaded": "indigo",
        "cleaned": "indigo",
        "failed": "rose",
        "profiled": "teal",
    }
    return badge(status.replace("_", " ").title(), mapping.get(status, "slate"))


def callout(message: str, tone: str = "info", icon: str = "ℹ️") -> None:
    safe_message = html.escape(str(message))
    st.markdown(
        f"""
        <div class="if-callout {html.escape(tone)}">
          <div class="if-callout-icon">{icon}</div>
          <div>{safe_message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(title: str, message: str, icon: str = "📊") -> None:
    st.markdown(
        f"""
        <div class="if-empty">
          <div class="if-empty-icon">{icon}</div>
          <h3>{html.escape(title)}</h3>
          <p>{html.escape(message)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_card(title: str, body: str, icon: str = "✨") -> None:
    st.markdown(
        f"""
        <div class="if-card">
          <div class="if-card-row">
            <div class="if-icon-tile">{icon}</div>
            <div>
              <h4>{html.escape(title)}</h4>
              <p>{html.escape(body)}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chips(values: list[str], tone: str = "slate") -> None:
    html_values = "".join(
        f'<span class="if-chip"><span class="if-dot" style="background:{INDIGO if tone == "indigo" else "#94A3B8"}"></span>'
        f"{html.escape(str(value))}</span>"
        for value in values
    )
    st.markdown(html_values, unsafe_allow_html=True)


def kv_row(label: str, value: str) -> str:
    return (
        f'<div class="if-kv"><span class="k">{html.escape(label)}</span>'
        f'<span class="v">{html.escape(value)}</span></div>'
    )


def format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def format_decimal(value: Any, places: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{places}f}"
    except (TypeError, ValueError):
        return str(value)


def format_percentage(value: Any, places: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{places}f}%"
    except (TypeError, ValueError):
        return str(value)


def format_bytes(size: Any) -> str:
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value):,} B"
        value /= 1024
    return f"{value:,.1f} GB"


def format_datetime(value: Any) -> str:
    if not value:
        return "—"
    try:
        cleaned = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%d %b %Y, %H:%M")
    except (ValueError, TypeError):
        return str(value)


def show_api_error(error: Exception) -> None:
    """Render a clean error state for API failures."""
    if isinstance(error, ApiError):
        st.error(error.message)
        if error.details:
            with st.expander("Error details"):
                st.json(error.details)
    else:
        st.error(f"Something went wrong: {error}")


def require_dataset(client: InsightFlowClient) -> dict[str, Any]:
    """Stop the page with a helpful empty state when no dataset is active."""
    dataset_id = st.session_state.get("dataset_id")
    if not dataset_id:
        empty_state(
            "No dataset selected",
            "Upload a CSV from the Datasets page to start analyzing. "
            "Every insight in InsightFlow is computed from your uploaded data.",
            "🗂️",
        )
        if st.button("Go to Datasets", type="primary"):
            st.switch_page("pages/datasets.py")
        st.stop()
    try:
        return client.get_dataset(dataset_id)
    except ApiError as error:
        st.session_state.pop("dataset_id", None)
        show_api_error(error)
        st.stop()
    return {}
