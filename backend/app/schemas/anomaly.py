"""Anomaly detection schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class AnomalyRequest(APIModel):
    """Configuration for an Isolation Forest run.

    Lower contamination means fewer records are labelled anomalous.
    """

    contamination: float = Field(default=0.05, gt=0, lt=0.5)
    n_estimators: int = Field(default=100, ge=10, le=1000)
    random_state: int = Field(default=42, ge=0)
    features: list[str] | None = None

    @field_validator("features")
    @classmethod
    def _clean_features(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))


class AnomalyRecord(APIModel):
    row_number: int
    anomaly_score: float
    is_anomaly: bool
    rank: int
    values: dict[str, Any]


class AnomalyDistributionBucket(APIModel):
    start: float
    end: float
    count: int


class AnomalyResponse(APIModel):
    id: int | None = None
    dataset_id: str
    generated_at: datetime
    source: str
    total_records: int
    anomalies_detected: int
    anomaly_percentage: float
    contamination: float
    n_estimators: int
    random_state: int
    features: list[str]
    records_analyzed: int
    records_excluded: int = 0
    anomalies: list[AnomalyRecord] = Field(default_factory=list)
    anomalies_returned: int = 0
    anomalies_truncated: bool = False
    score_distribution: list[AnomalyDistributionBucket] = Field(default_factory=list)
    feature_statistics: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    interpretation: str
    disclaimer: str


class AnomalySummary(APIModel):
    id: int
    dataset_id: str
    contamination: float
    n_estimators: int
    random_state: int
    total_records: int
    anomalies_detected: int
    anomaly_percentage: float
    features: list[str]
    created_at: datetime


class AnomalyHistoryResponse(APIModel):
    dataset_id: str
    items: list[AnomalySummary]
