"""Analytics, profiling and statistics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_analytics_service, get_dataset
from app.models.dataset import Dataset
from app.schemas.analytics import DatasetProfileResponse, DatasetStatisticsResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/datasets", tags=["analytics"])


@router.get(
    "/{dataset_id}/profile",
    response_model=DatasetProfileResponse,
    summary="Profile the dataset (statistics, correlations, chart data)",
)
def get_profile(
    dataset: Dataset = Depends(get_dataset),
    service: AnalyticsService = Depends(get_analytics_service),
    refresh: bool = Query(default=False, description="Recompute instead of using cached results"),
) -> DatasetProfileResponse:
    return DatasetProfileResponse.model_validate(service.profile(dataset, use_cache=not refresh))


@router.get(
    "/{dataset_id}/statistics",
    response_model=DatasetStatisticsResponse,
    summary="Get descriptive statistics",
)
def get_statistics(
    dataset: Dataset = Depends(get_dataset),
    service: AnalyticsService = Depends(get_analytics_service),
    refresh: bool = Query(default=False),
) -> DatasetStatisticsResponse:
    return DatasetStatisticsResponse.model_validate(
        service.statistics(dataset, use_cache=not refresh)
    )
