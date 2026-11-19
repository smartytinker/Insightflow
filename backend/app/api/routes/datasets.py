"""Dataset management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_dataset, get_ingestion_service
from app.core.config import Settings, get_settings
from app.core.exceptions import FileTooLargeError
from app.db.session import get_db
from app.models.dataset import Dataset
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.dataset import (
    ColumnInfo,
    DatasetDetail,
    DatasetListResponse,
    DatasetPreviewResponse,
    DatasetSummary,
    DatasetUploadResponse,
)
from app.services.ingestion_service import IngestionService

router = APIRouter(prefix="/datasets", tags=["datasets"])


async def _read_limited(upload: UploadFile, settings: Settings) -> bytes:
    """Read an upload while enforcing the size limit before buffering everything."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_size_bytes:
            raise FileTooLargeError(
                f"The file exceeds the {settings.max_upload_size_mb} MB upload limit.",
                details={"max_size_mb": settings.max_upload_size_mb},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/upload",
    response_model=DatasetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV dataset",
)
async def upload_dataset(
    file: Annotated[UploadFile, File(description="CSV file to ingest")],
    service: IngestionService = Depends(get_ingestion_service),
    settings: Settings = Depends(get_settings),
) -> DatasetUploadResponse:
    content = await _read_limited(file, settings)
    try:
        dataset, quality, columns = service.upload(
            filename=file.filename,
            content=content,
            content_type=file.content_type,
        )
    finally:
        await file.close()
    return DatasetUploadResponse(
        dataset=DatasetSummary.model_validate(dataset),
        quality=quality,
        columns=[ColumnInfo.model_validate(column) for column in columns],
    )


@router.get("", response_model=DatasetListResponse, summary="List datasets")
def list_datasets(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DatasetListResponse:
    repo = DatasetRepository(db)
    datasets = repo.list(limit=limit, offset=offset)
    return DatasetListResponse(
        items=[DatasetSummary.model_validate(dataset) for dataset in datasets],
        total=repo.count(),
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetDetail, summary="Get dataset metadata")
def get_dataset_detail(
    dataset: Dataset = Depends(get_dataset),
) -> DatasetDetail:
    summary = DatasetSummary.model_validate(dataset).model_dump()
    return DatasetDetail(
        **summary,
        columns=[ColumnInfo.model_validate(column) for column in dataset.column_metadata],
        quality=None,
        checksum=dataset.checksum,
    )


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dataset and its files",
)
def delete_dataset(
    dataset: Dataset = Depends(get_dataset),
    service: IngestionService = Depends(get_ingestion_service),
) -> None:
    service.delete(dataset)


@router.get(
    "/{dataset_id}/preview",
    response_model=DatasetPreviewResponse,
    summary="Preview dataset rows",
)
def preview_dataset(
    dataset: Dataset = Depends(get_dataset),
    service: IngestionService = Depends(get_ingestion_service),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DatasetPreviewResponse:
    return DatasetPreviewResponse.model_validate(
        service.preview(dataset, limit=limit, offset=offset)
    )
