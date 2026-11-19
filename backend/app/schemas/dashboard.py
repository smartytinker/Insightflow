"""Dashboard overview schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.dataset import DatasetSummary


class ActivityItem(APIModel):
    dataset_id: str
    dataset_name: str
    activity_type: str
    description: str
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class OverviewStats(APIModel):
    total_datasets: int
    total_records: int
    total_anomalies: int
    datasets_with_analysis: int
    total_analyses: int
    total_chat_messages: int


class OverviewResponse(APIModel):
    stats: OverviewStats
    recent_datasets: list[DatasetSummary] = Field(default_factory=list)
    recent_activity: list[ActivityItem] = Field(default_factory=list)
