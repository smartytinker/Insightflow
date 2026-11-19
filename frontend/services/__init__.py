"""Frontend service helpers."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from services.api_client import InsightFlowClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


@st.cache_resource(show_spinner=False)
def get_client() -> InsightFlowClient:
    """Return a process-wide API client."""
    return InsightFlowClient(
        os.getenv("API_BASE_URL", "http://localhost:8000"),
        public_base_url=os.getenv("PUBLIC_API_BASE_URL"),
    )


@st.cache_data(ttl=10, show_spinner=False)
def health_snapshot() -> dict:
    """Cached health check for the sidebar status indicator."""
    return get_client().health()


def clear_caches() -> None:
    """Clear cached reads after a mutating action."""
    health_snapshot.clear()
