"""Dataset ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType


def new_uuid() -> str:
    """Generate a string UUID primary key."""
    return str(uuid4())


class Dataset(Base):
    """Metadata for an uploaded dataset.

    Raw files live on disk; the database stores only metadata and controlled
    storage paths. Original uploads are never mutated by cleaning operations.
    """

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uploaded", index=True
    )
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    cleaned_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cleaned_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_metadata: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, nullable=False, default=list
    )

    cleaning_operations: Mapped[list["CleaningOperation"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    anomaly_results: Mapped[list["AnomalyResult"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def active_path(self) -> str:
        """Path to the dataset version used for analysis (cleaned if present)."""
        return self.cleaned_path or self.storage_path

    @property
    def is_cleaned(self) -> bool:
        return self.cleaned_path is not None


# Imports at module end avoid circular imports while registering relationships.
from app.models.analysis import AnalysisResult, AnomalyResult  # noqa: E402
from app.models.chat import ChatSession  # noqa: E402
from app.models.cleaning import CleaningOperation  # noqa: E402
