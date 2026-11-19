"""Grounded natural-language assistant with persisted conversation history."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from components.ui import (
    badge,
    callout,
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
    "AI Assistant",
    "Ask questions in plain language. Numerical answers are calculated by pandas first; "
    "the LLM only explains those facts and never performs the arithmetic.",
    "Conversational analytics",
)

columns = dataset["columns"]
numeric = [column["name"] for column in columns if column["kind"] == "numeric"]
metric = next(
    (
        name
        for token in ("revenue", "sales", "amount", "spend", "value", "price")
        for name in numeric
        if token in name.lower()
    ),
    numeric[0] if numeric else None,
)
categorical = [
    column["name"]
    for column in columns
    if column["kind"] == "categorical"
    and not column["name"].lower().endswith("_id")
    and 1 < column["unique_count"] <= 50
]
dimension = (
    min(categorical, key=lambda name: next(c["unique_count"] for c in columns if c["name"] == name))
    if categorical
    else None
)

if "chat_session_id" not in st.session_state:
    st.session_state["chat_session_id"] = None

try:
    sessions = client.chat_sessions(dataset_id)["items"]
except ApiError as error:
    sessions = []
    show_api_error(error)

current_session = st.session_state.get("chat_session_id")
if current_session is None and sessions:
    current_session = sessions[0]["id"]
    st.session_state["chat_session_id"] = current_session

controls = st.columns([2.4, 1, 1])
with controls[0]:
    if sessions:
        session_ids = [item["id"] for item in sessions]
        if current_session not in session_ids:
            session_ids.insert(0, current_session)
        labels = {
            item["id"]: f"{item['title'][:52]} · {item['message_count']} messages"
            for item in sessions
        }
        selected_session = st.selectbox(
            "Conversation",
            options=session_ids,
            index=session_ids.index(current_session) if current_session in session_ids else 0,
            format_func=lambda value: labels.get(value, "New conversation"),
            label_visibility="collapsed",
        )
        if selected_session != current_session:
            st.session_state["chat_session_id"] = selected_session
            st.rerun()
    else:
        st.caption("No conversations yet — ask the first question below.")
with controls[1]:
    if st.button("New conversation", width="stretch"):
        try:
            session = client.start_chat_session(dataset_id)
        except ApiError as error:
            show_api_error(error)
        else:
            st.session_state["chat_session_id"] = session["id"]
            st.rerun()
with controls[2]:
    st.caption("Facts first, narrative second.")

callout(
    "Only compact statistical summaries and calculated facts are sent to the configured LLM. "
    "The full dataset is never transmitted. If the provider is unavailable, you still get "
    "the deterministic pandas result.",
    "info",
    "🔒",
)

try:
    history = (
        client.chat_history(dataset_id, st.session_state.get("chat_session_id"))
        if st.session_state.get("chat_session_id")
        else {"messages": []}
    )
    messages = history["messages"]
except ApiError as error:
    messages = []
    show_api_error(error)

st.write("")
if not messages:
    section_header(
        "Start with a question", "Suggestions are built from this dataset's actual columns"
    )
    suggestions = []
    if dimension and metric:
        suggestions.append(f"Which {dimension} has the highest {metric}?")
        suggestions.append(f"Which {dimension} contributes the least {metric}?")
    if metric:
        suggestions.append(f"What is the average {metric}?")
    suggestions.append("Summarize the dataset for management.")
    suggestions.append("Are there unusual patterns in the data?")
    suggestions.append("Explain the correlation between the numerical variables.")

    suggestion_cols = st.columns(2)
    for index, suggestion in enumerate(suggestions[:6]):
        with suggestion_cols[index % 2]:
            if st.button(suggestion, key=f"suggestion_{index}", width="stretch"):
                st.session_state["pending_question"] = suggestion
                st.rerun()

for message in messages:
    role = message["role"]
    metadata = message.get("message_metadata") or {}
    with st.chat_message(role, avatar="🧑‍💼" if role == "user" else "✨"):
        st.markdown(message["content"])
        if role == "assistant":
            mode = metadata.get("mode")
            if mode == "llm+calculations":
                st.markdown(
                    badge("Calculated facts + AI interpretation", "indigo"), unsafe_allow_html=True
                )
            else:
                st.markdown(badge("Calculated directly from data", "teal"), unsafe_allow_html=True)
            facts = metadata.get("facts") or []
            if facts:
                with st.expander(f"Calculated facts ({len(facts)})"):
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Fact": fact["label"],
                                    "Value": str(fact["value"]),
                                    "Method": fact["method"],
                                }
                                for fact in facts
                            ]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
            if metadata.get("note"):
                callout(metadata["note"], "warn", "⚠️")


def submit_question(question: str) -> None:
    """Send a question to the API and refresh the conversation."""
    with st.spinner("Calculating from your dataset…"):
        try:
            result = client.chat(
                dataset_id,
                question,
                session_id=st.session_state.get("chat_session_id"),
            )
        except ApiError as error:
            show_api_error(error)
            return
    st.session_state["chat_session_id"] = result["session_id"]
    st.session_state.pop("pending_question", None)
    st.rerun()


pending = st.session_state.pop("pending_question", None)
if pending:
    submit_question(pending)

question = st.chat_input("Ask a question about this dataset…")
if question:
    submit_question(question)

if messages:
    st.caption(
        "Conversations are stored per dataset. Calculated facts are deterministic; "
        "AI interpretation is clearly labelled."
    )
