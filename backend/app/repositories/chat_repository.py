"""Chat session and message persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.chat import ChatMessage, ChatSession


class ChatRepository:
    """Database access for dataset-scoped conversations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def latest_session(self, dataset_id: str) -> ChatSession | None:
        stmt = (
            select(ChatSession)
            .where(ChatSession.dataset_id == dataset_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def get_session(self, dataset_id: str, session_id: str) -> ChatSession:
        stmt = select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.dataset_id == dataset_id
        )
        session = self.db.scalar(stmt)
        if session is None:
            raise NotFoundError(
                f"Chat session '{session_id}' was not found for this dataset.",
                details={"session_id": session_id, "dataset_id": dataset_id},
            )
        return session

    def get_or_create_session(
        self, dataset_id: str, session_id: str | None = None, title: str | None = None
    ) -> ChatSession:
        if session_id:
            return self.get_session(dataset_id, session_id)
        existing = self.latest_session(dataset_id)
        if existing is not None:
            return existing
        return self.create_session(dataset_id, title)

    def create_session(self, dataset_id: str, title: str | None = None) -> ChatSession:
        """Create a new empty conversation for a dataset."""
        session = ChatSession(
            dataset_id=dataset_id,
            title=(title or "Dataset conversation")[:255],
        )
        self.db.add(session)
        self.db.flush()
        self.db.refresh(session)
        return session

    def add_message(
        self,
        session: ChatSession,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        if role not in {"user", "assistant"}:
            raise ValidationAppError("Unsupported chat message role.")
        message = ChatMessage(
            session_id=session.id,
            role=role,
            content=content,
            message_metadata=metadata or {},
        )
        self.db.add(message)
        # Touch the session so it sorts as the most recent conversation.
        session.updated_at = datetime.now(UTC)
        self.db.flush()
        self.db.refresh(message)
        return message

    def history(self, session_id: str, limit: int = 200) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def list_sessions(self, dataset_id: str) -> list[tuple[ChatSession, int]]:
        stmt = (
            select(ChatSession, func.count(ChatMessage.id))
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.dataset_id == dataset_id)
            .group_by(ChatSession.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        )
        return [(session, int(count)) for session, count in self.db.execute(stmt).all()]

    def session_with_messages(self, session_id: str) -> ChatSession | None:
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        return self.db.scalar(stmt)
