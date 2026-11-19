"""Dataset persistence operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.dataset import Dataset


class DatasetRepository:
    """Database access for dataset metadata."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, dataset: Dataset) -> Dataset:
        self.db.add(dataset)
        self.db.flush()
        self.db.refresh(dataset)
        return dataset

    def get(self, dataset_id: str) -> Dataset | None:
        return self.db.get(Dataset, dataset_id)

    def get_required(self, dataset_id: str) -> Dataset:
        dataset = self.get(dataset_id)
        if dataset is None:
            raise NotFoundError(
                f"Dataset '{dataset_id}' was not found.",
                details={"dataset_id": dataset_id},
            )
        return dataset

    def list(self, limit: int = 50, offset: int = 0) -> list[Dataset]:
        stmt = select(Dataset).order_by(Dataset.upload_timestamp.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def list_recent(self, limit: int = 5) -> list[Dataset]:
        return self.list(limit=limit, offset=0)

    def count(self) -> int:
        return int(self.db.scalar(select(func.count(Dataset.id))) or 0)

    def total_rows(self) -> int:
        return int(self.db.scalar(select(func.coalesce(func.sum(Dataset.row_count), 0))) or 0)

    def delete(self, dataset: Dataset) -> None:
        self.db.delete(dataset)
        self.db.flush()

    def update(self, dataset: Dataset, **fields: Any) -> Dataset:
        for key, value in fields.items():
            setattr(dataset, key, value)
        self.db.flush()
        self.db.refresh(dataset)
        return dataset
