"""Data cleaning endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_cleaning_service, get_dataset
from app.models.dataset import Dataset
from app.schemas.dataset import (
    CleaningHistoryResponse,
    CleaningOperationRead,
    CleaningRequest,
    CleaningSummary,
)
from app.services.cleaning_service import CleaningService

router = APIRouter(prefix="/datasets", tags=["cleaning"])


@router.post(
    "/{dataset_id}/clean",
    response_model=CleaningSummary,
    summary="Apply cleaning operations to a dataset copy",
)
def clean_dataset(
    request: CleaningRequest,
    dataset: Dataset = Depends(get_dataset),
    service: CleaningService = Depends(get_cleaning_service),
) -> CleaningSummary:
    return CleaningSummary.model_validate(service.clean(dataset, request))


@router.get(
    "/{dataset_id}/cleaning-history",
    response_model=CleaningHistoryResponse,
    summary="List cleaning operations",
)
def cleaning_history(
    dataset: Dataset = Depends(get_dataset),
    service: CleaningService = Depends(get_cleaning_service),
) -> CleaningHistoryResponse:
    operations = service.history(dataset)
    return CleaningHistoryResponse(
        dataset_id=dataset.id,
        operations=[CleaningOperationRead.model_validate(operation) for operation in operations],
    )
