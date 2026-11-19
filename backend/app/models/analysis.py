"""Analysis and anomaly result ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType


class AnalysisResult(Base):
    """Cached output of an analysis (profile, statistics, summary)."""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="analysis_results")

    __table_args__ = (Index("ix_analysis_results_dataset_type", "dataset_id", "analysis_type"),)


class AnomalyResult(Base):
    """Summary and record-level output of an Isolation Forest run."""

    __tablename__ = "anomaly_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contamination: Mapped[float] = mapped_column(Float, nullable=False)
    n_estimators: Mapped[int] = mapped_column(Integer, nullable=False)
    random_state: Mapped[int] = mapped_column(Integer, nullable=False)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False)
    anomalies_detected: Mapped[int] = mapped_column(Integer, nullable=False)
    anomaly_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    features: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="anomaly_results")

    __table_args__ = (Index("ix_anomaly_results_dataset_created", "dataset_id", "created_at"),)


from app.models.dataset import Dataset  # noqa: E402
