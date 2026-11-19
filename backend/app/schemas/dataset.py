"""Dataset, cleaning and preview schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel, PaginatedResponse

ColumnKind = Literal["numeric", "categorical", "datetime", "boolean", "other"]
MissingStrategy = Literal[
    "none", "drop_rows", "fill_mean", "fill_median", "fill_mode", "fill_constant", "fill_zero"
]
OutlierAction = Literal["none", "remove", "clip"]
ColumnCase = Literal["preserve", "lower", "snake"]


class ColumnInfo(APIModel):
    """Detected column metadata."""

    name: str
    dtype: str
    kind: ColumnKind
    missing_count: int = 0
    missing_percentage: float = 0.0
    unique_count: int = 0
    sample_values: list[Any] = Field(default_factory=list)
    is_numeric: bool = False
    is_datetime: bool = False


class DataQualitySummary(APIModel):
    """At-a-glance data quality information."""

    total_rows: int
    total_columns: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    columns_with_missing_values: list[str] = Field(default_factory=list)
    columns_with_duplicate_names: int = 0


class DatasetSummary(APIModel):
    """Dataset metadata returned by list and detail endpoints."""

    id: str
    filename: str
    original_filename: str
    file_size: int
    row_count: int
    column_count: int
    upload_timestamp: datetime
    processing_status: str
    is_cleaned: bool = False
    cleaned_row_count: int | None = None


class DatasetDetail(DatasetSummary):
    """Dataset metadata plus column details and quality flags."""

    columns: list[ColumnInfo] = Field(default_factory=list)
    quality: DataQualitySummary | None = None
    checksum: str | None = None


class DatasetListResponse(PaginatedResponse):
    items: list[DatasetSummary]


class DatasetPreviewResponse(APIModel):
    """Paginated rows from the active dataset version."""

    dataset_id: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    limit: int
    offset: int
    source: Literal["original", "cleaned"]


class DatasetUploadResponse(APIModel):
    dataset: DatasetSummary
    quality: DataQualitySummary
    columns: list[ColumnInfo]


class ColumnStrategy(APIModel):
    """Per-column cleaning override."""

    strategy: MissingStrategy
    fill_value: Any | None = None


class CleaningRequest(APIModel):
    """Configuration for a cleaning run.

    Cleaning always operates on a copy. Original files are never modified.
    """

    drop_duplicates: bool = True
    missing_strategy: MissingStrategy = "none"
    fill_value: Any | None = None
    column_strategies: dict[str, MissingStrategy] = Field(default_factory=dict)
    type_conversions: dict[str, Literal["numeric", "datetime", "string", "category", "boolean"]] = (
        Field(default_factory=dict)
    )
    normalize_columns: bool = True
    column_case: ColumnCase = "snake"
    drop_columns: list[str] = Field(default_factory=list)
    outlier_action: OutlierAction = "none"
    outlier_columns: list[str] = Field(default_factory=list)
    outlier_iqr_multiplier: float = Field(default=1.5, gt=0, le=10)

    @field_validator("drop_columns", "outlier_columns")
    @classmethod
    def _unique_columns(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for column in value:
            if column not in seen:
                seen.append(column)
        return seen


class CleaningOperationRead(APIModel):
    id: int
    operation_type: str
    operation_details: dict[str, Any]
    records_affected: int
    created_at: datetime


class CleaningSummary(APIModel):
    dataset_id: str
    original_row_count: int
    final_row_count: int
    original_column_count: int
    final_column_count: int
    missing_values_before: int
    missing_values_after: int
    missing_values_filled: int
    duplicates_removed: int
    columns_transformed: list[str] = Field(default_factory=list)
    operations: list[CleaningOperationRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    before_preview: list[dict[str, Any]] = Field(default_factory=list)
    after_preview: list[dict[str, Any]] = Field(default_factory=list)
    cleaned_file_available: bool = True
    generated_at: datetime


class CleaningHistoryResponse(APIModel):
    dataset_id: str
    operations: list[CleaningOperationRead]


class ColumnMetadataResponse(APIModel):
    dataset_id: str
    columns: list[ColumnInfo]
