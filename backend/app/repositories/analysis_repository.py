"""Analysis and anomaly result persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.analysis import AnalysisResult, AnomalyResult
from app.models.dataset import Dataset


class AnalysisRepository:
    """Database access for analytical results and anomaly runs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, dataset_id: str, analysis_type: str, result: dict[str, Any]) -> AnalysisResult:
        record = AnalysisResult(
            dataset_id=dataset_id, analysis_type=analysis_type, result_json=result
        )
        self.db.add(record)
        self.db.flush()
        self.db.refresh(record)
        return record

    def latest(self, dataset_id: str, analysis_type: str) -> AnalysisResult | None:
        stmt = (
            select(AnalysisResult)
            .where(
                AnalysisResult.dataset_id == dataset_id,
                AnalysisResult.analysis_type == analysis_type,
            )
            .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_for_dataset(
        self, dataset_id: str, analysis_type: str | None = None
    ) -> list[AnalysisResult]:
        stmt = select(AnalysisResult).where(AnalysisResult.dataset_id == dataset_id)
        if analysis_type:
            stmt = stmt.where(AnalysisResult.analysis_type == analysis_type)
        stmt = stmt.order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc())
        return list(self.db.scalars(stmt).all())

    def recent(self, limit: int = 10) -> list[tuple[AnalysisResult, Dataset]]:
        stmt = (
            select(AnalysisResult, Dataset)
            .join(Dataset, Dataset.id == AnalysisResult.dataset_id)
            .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).all())

    def save_anomaly(self, **fields: Any) -> AnomalyResult:
        record = AnomalyResult(**fields)
        self.db.add(record)
        self.db.flush()
        self.db.refresh(record)
        return record

    def get_anomaly(self, dataset_id: str, anomaly_id: int) -> AnomalyResult:
        stmt = select(AnomalyResult).where(
            AnomalyResult.id == anomaly_id, AnomalyResult.dataset_id == dataset_id
        )
        record = self.db.scalar(stmt)
        if record is None:
            raise NotFoundError(
                f"Anomaly run '{anomaly_id}' was not found for this dataset.",
                details={"anomaly_id": anomaly_id, "dataset_id": dataset_id},
            )
        return record

    def latest_anomaly(self, dataset_id: str) -> AnomalyResult | None:
        stmt = (
            select(AnomalyResult)
            .where(AnomalyResult.dataset_id == dataset_id)
            .order_by(AnomalyResult.created_at.desc(), AnomalyResult.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def anomaly_history(self, dataset_id: str, limit: int = 20) -> list[AnomalyResult]:
        stmt = (
            select(AnomalyResult)
            .where(AnomalyResult.dataset_id == dataset_id)
            .order_by(AnomalyResult.created_at.desc(), AnomalyResult.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def recent_anomalies(self, limit: int = 10) -> list[tuple[AnomalyResult, Dataset]]:
        stmt = (
            select(AnomalyResult, Dataset)
            .join(Dataset, Dataset.id == AnomalyResult.dataset_id)
            .order_by(AnomalyResult.created_at.desc(), AnomalyResult.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).all())

    def latest_anomaly_totals(self) -> tuple[int, int]:
        """Return (datasets with anomaly runs, anomalies in latest run per dataset)."""
        latest_ids = (
            select(func.max(AnomalyResult.id).label("id"))
            .group_by(AnomalyResult.dataset_id)
            .subquery()
        )
        stmt = select(
            func.count(AnomalyResult.id),
            func.coalesce(func.sum(AnomalyResult.anomalies_detected), 0),
        ).join(latest_ids, AnomalyResult.id == latest_ids.c.id)
        count, anomalies = self.db.execute(stmt).one()
        return int(count or 0), int(anomalies or 0)
