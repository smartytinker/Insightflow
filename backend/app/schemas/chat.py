"""Chat and AI assistant schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class ChatRequest(APIModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=36)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question must not be empty.")
        return cleaned


class GroundedFact(APIModel):
    """A deterministic calculation used to ground the answer."""

    label: str
    value: Any
    method: str


class ChatMessageRead(APIModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    message_metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(APIModel):
    session_id: str
    message_id: int
    answer: str
    mode: Literal["llm+calculations", "calculations_only"]
    calculated_facts: list[GroundedFact] = Field(default_factory=list)
    question_type: str
    llm_error: str | None = None
    note: str | None = None
    created_at: datetime


class ChatHistoryResponse(APIModel):
    dataset_id: str
    session_id: str | None
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatSessionSummary(APIModel):
    id: str
    dataset_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(APIModel):
    dataset_id: str
    items: list[ChatSessionSummary]
