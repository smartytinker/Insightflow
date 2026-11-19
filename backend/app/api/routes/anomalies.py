"""Anomaly detection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, status

from app.api.deps import get_anomaly_service, get_dataset
from app.models.dataset import Dataset
from app.schemas.anomaly import (
    AnomalyHistoryResponse,
    AnomalyRequest,
    AnomalyResponse,
    AnomalySummary,
)
from app.services.anomaly_service import AnomalyService

router = APIRouter(prefix="/datasets", tags=["anomalies"])


@router.post(
    "/{dataset_id}/anomalies",
    response_model=AnomalyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Train Isolation Forest and detect anomalies",
)
def detect_anomalies(
    dataset: Dataset = Depends(get_dataset),
    service: AnomalyService = Depends(get_anomaly_service),
    request: AnomalyRequest = Body(default_factory=AnomalyRequest),
) -> AnomalyResponse:
    return AnomalyResponse.model_validate(service.detect(dataset, request))


@router.get(
    "/{dataset_id}/anomalies",
    response_model=AnomalyResponse,
    summary="Get the latest anomaly results",
)
def latest_anomalies(
    dataset: Dataset = Depends(get_dataset),
    service: AnomalyService = Depends(get_anomaly_service),
) -> AnomalyResponse:
    return AnomalyResponse.model_validate(service.latest(dataset))


@router.get(
    "/{dataset_id}/anomalies/history",
    response_model=AnomalyHistoryResponse,
    summary="List anomaly detection runs",
)
def anomaly_history(
    dataset: Dataset = Depends(get_dataset),
    service: AnomalyService = Depends(get_anomaly_service),
) -> AnomalyHistoryResponse:
    return AnomalyHistoryResponse(
        dataset_id=dataset.id,
        items=[AnomalySummary.model_validate(item) for item in service.history(dataset)],
    )


@router.get(
    "/{dataset_id}/anomalies/{anomaly_id}",
    response_model=AnomalyResponse,
    summary="Get a specific anomaly run",
)
def get_anomaly_run(
    anomaly_id: int,
    dataset: Dataset = Depends(get_dataset),
    service: AnomalyService = Depends(get_anomaly_service),
) -> AnomalyResponse:
    return AnomalyResponse.model_validate(service.get(dataset, anomaly_id))
