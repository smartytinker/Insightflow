"""FastAPI dependency providers.

Routes receive services and datasets through these factories, keeping route
handlers thin and making business logic testable in isolation.
"""

from __future__ import annotations

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.dataset import Dataset
from app.repositories.dataset_repository import DatasetRepository
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.chat_service import ChatService
from app.services.cleaning_service import CleaningService
from app.services.ingestion_service import IngestionService
from app.services.report_service import ReportService


def get_dataset(
    dataset_id: str = Path(..., min_length=1, max_length=36, description="Dataset identifier"),
    db: Session = Depends(get_db),
) -> Dataset:
    """Resolve a dataset or raise a consistent 404 error."""
    return DatasetRepository(db).get_required(dataset_id)


def get_ingestion_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> IngestionService:
    return IngestionService(db, settings)


def get_cleaning_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> CleaningService:
    return CleaningService(db, settings)


def get_analytics_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AnalyticsService:
    return AnalyticsService(db, settings)


def get_anomaly_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AnomalyService:
    return AnomalyService(db, settings)


def get_chat_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ChatService:
    return ChatService(db, settings)


def get_report_service(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ReportService:
    return ReportService(db, settings)
