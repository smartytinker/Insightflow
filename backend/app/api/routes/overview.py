"""Dashboard overview endpoint backed entirely by real persisted data."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.analysis import AnalysisResult
from app.models.chat import ChatMessage
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.dashboard import ActivityItem, OverviewResponse, OverviewStats
from app.schemas.dataset import DatasetSummary
from app.utils.serialization import json_safe

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewResponse, summary="Dashboard overview metrics")
def overview(db: Session = Depends(get_db)) -> OverviewResponse:
    dataset_repo = DatasetRepository(db)
    analysis_repo = AnalysisRepository(db)

    total_datasets = dataset_repo.count()
    total_records = dataset_repo.total_rows()
    _, total_anomalies = analysis_repo.latest_anomaly_totals()
    total_analyses = int(db.scalar(select(func.count(AnalysisResult.id))) or 0)
    datasets_with_analysis = int(
        db.scalar(select(func.count(func.distinct(AnalysisResult.dataset_id)))) or 0
    )
    total_chat_messages = int(db.scalar(select(func.count(ChatMessage.id))) or 0)

    recent_datasets = [
        DatasetSummary.model_validate(dataset) for dataset in dataset_repo.list_recent(5)
    ]

    activity: list[ActivityItem] = []
    for analysis, dataset in analysis_repo.recent(8):
        activity.append(
            ActivityItem(
                dataset_id=dataset.id,
                dataset_name=dataset.original_filename,
                activity_type=analysis.analysis_type,
                description=f"{analysis.analysis_type.title()} analysis completed",
                created_at=analysis.created_at,
                details={"analysis_id": analysis.id},
            )
        )
    for anomaly, dataset in analysis_repo.recent_anomalies(5):
        activity.append(
            ActivityItem(
                dataset_id=dataset.id,
                dataset_name=dataset.original_filename,
                activity_type="anomaly_detection",
                description=(
                    f"{anomaly.anomalies_detected:,} anomalies detected in "
                    f"{anomaly.total_records:,} records"
                ),
                created_at=anomaly.created_at,
                details={
                    "anomaly_id": anomaly.id,
                    "anomaly_percentage": json_safe(anomaly.anomaly_percentage),
                },
            )
        )
    activity.sort(key=lambda item: item.created_at, reverse=True)

    return OverviewResponse(
        stats=OverviewStats(
            total_datasets=total_datasets,
            total_records=total_records,
            total_anomalies=total_anomalies,
            datasets_with_analysis=datasets_with_analysis,
            total_analyses=total_analyses,
            total_chat_messages=total_chat_messages,
        ),
        recent_datasets=recent_datasets,
        recent_activity=activity[:10],
    )
