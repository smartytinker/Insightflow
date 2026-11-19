"""Cleaning operation ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType


class CleaningOperation(Base):
    """A single recorded cleaning action applied to a dataset copy."""

    __tablename__ = "cleaning_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_details: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    records_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="cleaning_operations")


from app.models.dataset import Dataset  # noqa: E402
