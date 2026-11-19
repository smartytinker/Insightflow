"""AI assistant endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_chat_service, get_dataset
from app.models.dataset import Dataset
from app.schemas.chat import (
    ChatHistoryResponse,
    ChatMessageRead,
    ChatRequest,
    ChatResponse,
    ChatSessionListResponse,
    ChatSessionSummary,
    GroundedFact,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/datasets", tags=["assistant"])


@router.post(
    "/{dataset_id}/chat",
    response_model=ChatResponse,
    summary="Ask a natural-language question about a dataset",
)
def ask_question(
    request: ChatRequest,
    dataset: Dataset = Depends(get_dataset),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    result = service.ask(dataset, request.question, request.session_id)
    return ChatResponse(
        session_id=result["session_id"],
        message_id=result["message_id"],
        answer=result["answer"],
        mode=result["mode"],
        calculated_facts=[GroundedFact.model_validate(fact) for fact in result["calculated_facts"]],
        question_type=result["question_type"],
        llm_error=result["llm_error"],
        note=result["note"],
        created_at=result["created_at"],
    )


@router.get(
    "/{dataset_id}/chat/history",
    response_model=ChatHistoryResponse,
    summary="Get conversation history",
)
def chat_history(
    dataset: Dataset = Depends(get_dataset),
    service: ChatService = Depends(get_chat_service),
    session_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=200, ge=1, le=500),
) -> ChatHistoryResponse:
    result = service.history(dataset, session_id=session_id, limit=limit)
    return ChatHistoryResponse(
        dataset_id=result["dataset_id"],
        session_id=result["session_id"],
        messages=[ChatMessageRead.model_validate(message) for message in result["messages"]],
    )


@router.get(
    "/{dataset_id}/chat/sessions",
    response_model=ChatSessionListResponse,
    summary="List chat sessions for a dataset",
)
def chat_sessions(
    dataset: Dataset = Depends(get_dataset),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionListResponse:
    return ChatSessionListResponse(
        dataset_id=dataset.id,
        items=[ChatSessionSummary.model_validate(item) for item in service.list_sessions(dataset)],
    )


@router.post(
    "/{dataset_id}/chat/sessions",
    response_model=ChatSessionSummary,
    status_code=201,
    summary="Start a new chat session",
)
def create_chat_session(
    dataset: Dataset = Depends(get_dataset),
    service: ChatService = Depends(get_chat_service),
) -> ChatSessionSummary:
    return ChatSessionSummary.model_validate(service.start_session(dataset))
