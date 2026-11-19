"""Analytics and profiling schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel
from app.schemas.dataset import DataQualitySummary


class HistogramBin(APIModel):
    start: float
    end: float
    count: int


class NumericStats(APIModel):
    name: str
    count: int
    missing_count: int
    missing_percentage: float
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    skewness: float | None = None
    outlier_count: int = 0
    histogram: list[HistogramBin] = Field(default_factory=list)


class ValueFrequency(APIModel):
    value: Any
    count: int
    percentage: float


class CategoricalStats(APIModel):
    name: str
    count: int
    missing_count: int
    missing_percentage: float
    unique_count: int
    top_values: list[ValueFrequency] = Field(default_factory=list)
    frequency_distribution: list[ValueFrequency] = Field(default_factory=list)


class DatetimeStats(APIModel):
    name: str
    count: int
    missing_count: int
    missing_percentage: float
    minimum: str | None = None
    maximum: str | None = None
    span_days: float | None = None


class CorrelationMatrix(APIModel):
    columns: list[str]
    matrix: list[list[float | None]]


class CorrelationPair(APIModel):
    column_a: str
    column_b: str
    correlation: float
    strength: str


class TimeSeriesPoint(APIModel):
    period: str
    value: float
    record_count: int


class TimeSeries(APIModel):
    date_column: str
    metric_column: str
    aggregation: str
    granularity: str
    points: list[TimeSeriesPoint]


class DatasetOverview(APIModel):
    row_count: int
    column_count: int
    numeric_column_count: int
    categorical_column_count: int
    datetime_column_count: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    memory_usage_bytes: int


class DatasetProfileResponse(APIModel):
    dataset_id: str
    generated_at: datetime
    source: str
    overview: DatasetOverview
    quality: DataQualitySummary
    numeric_columns: list[NumericStats] = Field(default_factory=list)
    categorical_columns: list[CategoricalStats] = Field(default_factory=list)
    datetime_columns: list[DatetimeStats] = Field(default_factory=list)
    correlations: CorrelationMatrix | None = None
    top_correlations: list[CorrelationPair] = Field(default_factory=list)
    time_series: TimeSeries | None = None
    quality_issues: list[str] = Field(default_factory=list)
    important_columns: list[str] = Field(default_factory=list)
    summary: str


class DatasetStatisticsResponse(APIModel):
    dataset_id: str
    generated_at: datetime
    overview: DatasetOverview
    numeric_columns: list[NumericStats] = Field(default_factory=list)
    categorical_columns: list[CategoricalStats] = Field(default_factory=list)
    datetime_columns: list[DatetimeStats] = Field(default_factory=list)
    correlations: CorrelationMatrix | None = None
    missing_values: dict[str, int] = Field(default_factory=dict)
