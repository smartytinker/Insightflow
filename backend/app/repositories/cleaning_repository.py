"""Cleaning operation persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cleaning import CleaningOperation


class CleaningRepository:
    """Database access for cleaning history."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        dataset_id: str,
        operation_type: str,
        operation_details: dict[str, Any],
        records_affected: int,
    ) -> CleaningOperation:
        operation = CleaningOperation(
            dataset_id=dataset_id,
            operation_type=operation_type,
            operation_details=operation_details,
            records_affected=records_affected,
        )
        self.db.add(operation)
        self.db.flush()
        return operation

    def list_for_dataset(self, dataset_id: str, limit: int = 100) -> list[CleaningOperation]:
        stmt = (
            select(CleaningOperation)
            .where(CleaningOperation.dataset_id == dataset_id)
            .order_by(CleaningOperation.created_at.desc(), CleaningOperation.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())
