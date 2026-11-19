"""Column metadata, data quality and safe dataset loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api import types as ptypes

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.schemas.dataset import ColumnInfo, DataQualitySummary
from app.utils.serialization import json_safe

_SAMPLE_SIZE = 5
_DATE_VALUE_PATTERN = re.compile(
    r"^\s*(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
)


def detect_column_kind(series: pd.Series) -> str:
    """Classify a pandas Series as numeric, datetime, boolean, categorical or other."""
    if ptypes.is_bool_dtype(series):
        return "boolean"
    if ptypes.is_numeric_dtype(series):
        return "numeric"
    if ptypes.is_datetime64_any_dtype(series):
        return "datetime"
    if (
        ptypes.is_categorical_dtype(series)
        or ptypes.is_object_dtype(series)
        or ptypes.is_string_dtype(series)
    ):
        return "categorical"
    return "other"


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Return numeric column names excluding booleans."""
    return [
        column
        for column in df.columns
        if ptypes.is_numeric_dtype(df[column]) and not ptypes.is_bool_dtype(df[column])
    ]


def datetime_columns(df: pd.DataFrame) -> list[str]:
    """Return datetime column names."""
    return [column for column in df.columns if ptypes.is_datetime64_any_dtype(df[column])]


def categorical_columns(df: pd.DataFrame) -> list[str]:
    """Return categorical-like column names (object/string/category/bool)."""
    return [column for column in df.columns if detect_column_kind(df[column]) == "categorical"]


def column_metadata(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Build serializable metadata for every column."""
    total = max(len(df), 1)
    metadata: list[dict[str, Any]] = []
    for column in df.columns:
        series = df[column]
        missing_count = int(series.isna().sum())
        kind = detect_column_kind(series)
        non_null = series.dropna()
        try:
            unique_count = int(non_null.nunique())
        except TypeError:
            unique_count = int(non_null.astype(str).nunique())
        samples = [json_safe(value) for value in non_null.unique()[:_SAMPLE_SIZE]]
        metadata.append(
            {
                "name": str(column),
                "dtype": str(series.dtype),
                "kind": kind,
                "missing_count": missing_count,
                "missing_percentage": round(missing_count / total * 100, 2),
                "unique_count": unique_count,
                "sample_values": samples,
                "is_numeric": kind == "numeric",
                "is_datetime": kind == "datetime",
            }
        )
    return metadata


def build_column_info(metadata: list[dict[str, Any]]) -> list[ColumnInfo]:
    """Validate stored column metadata into response schemas."""
    return [ColumnInfo.model_validate(item) for item in metadata]


def quality_summary(df: pd.DataFrame) -> DataQualitySummary:
    """Compute missingness, duplicates and general data quality information."""
    total_rows, total_columns = df.shape
    total_cells = max(total_rows * total_columns, 1)
    missing_cells = int(df.isna().sum().sum())
    missing_by_column = df.isna().sum()
    columns_with_missing = [
        str(column) for column, count in missing_by_column.items() if int(count) > 0
    ]
    return DataQualitySummary(
        total_rows=int(total_rows),
        total_columns=int(total_columns),
        missing_cells=missing_cells,
        missing_percentage=round(missing_cells / total_cells * 100, 2),
        duplicate_rows=int(df.duplicated().sum()),
        columns_with_missing_values=columns_with_missing,
        columns_with_duplicate_names=0,
    )


def resolve_storage_path(path: str | Path, settings: Settings) -> Path:
    """Resolve a stored path and ensure it stays inside the storage directory.

    Protects against path traversal in database values or configuration.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (settings.storage_dir / candidate).resolve()
    else:
        candidate = candidate.resolve()
    storage_root = settings.storage_dir.resolve()
    try:
        candidate.relative_to(storage_root)
    except ValueError as exc:
        raise ValidationAppError("The dataset file path is outside the storage directory.") from exc
    return candidate


def infer_datetime_columns(df: pd.DataFrame, threshold: float = 0.95) -> pd.DataFrame:
    """Parse date-like columns into datetime without coercing other text.

    A column is parsed when its name suggests a date/time value or when a large
    share of its sampled strings match a common date pattern. Free-text
    categorical fields are left intact.
    """
    for column in df.columns:
        series = df[column]
        if not (ptypes.is_object_dtype(series) or ptypes.is_string_dtype(series)):
            continue
        lowered = str(column).lower()
        name_hint = any(
            token in lowered
            for token in ("date", "time", "month", "year", "day", "timestamp", "period")
        )
        non_null = series.dropna()
        if non_null.empty:
            continue
        value_hint = False
        if not name_hint:
            sample = non_null.head(50).astype(str)
            value_hint = bool(sample.str.match(_DATE_VALUE_PATTERN).mean() >= 0.9)
        if not (name_hint or value_hint):
            continue
        try:
            parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
        except (ValueError, TypeError):
            continue
        if parsed.notna().mean() >= threshold:
            df[column] = pd.to_datetime(series, errors="coerce", format="mixed")
    return df


def load_dataframe(path: str | Path, settings: Settings) -> pd.DataFrame:
    """Load a stored CSV safely with encoding fallback.

    Raises a domain error if the file is missing or unreadable. Callers should
    use the returned DataFrame without mutating the on-disk file.
    """
    resolved = resolve_storage_path(path, settings)
    if not resolved.exists() or not resolved.is_file():
        raise ValidationAppError("The dataset file is missing from storage.")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            frame = pd.read_csv(resolved, encoding=encoding, low_memory=False)
            return infer_datetime_columns(frame)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise ValidationAppError("The stored dataset is empty.") from exc
        except (pd.errors.ParserError, OSError) as exc:
            raise ValidationAppError("The stored dataset could not be read.") from exc
    raise ValidationAppError("The stored dataset encoding is not supported.") from last_error


def ensure_columns_exist(df: pd.DataFrame, columns: list[str], context: str = "request") -> None:
    """Validate that referenced columns exist, with a helpful error message."""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValidationAppError(
            f"Unknown {context} columns: {', '.join(missing)}.",
            details={"missing_columns": missing, "available_columns": list(df.columns)},
        )


def is_numeric_convertible(series: pd.Series, threshold: float = 0.9) -> bool:
    """Return True when most non-null values look numeric."""
    non_null = series.dropna()
    if non_null.empty:
        return False
    converted = pd.to_numeric(
        non_null.astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    return bool(converted.notna().mean() >= threshold)


def column_value_counts(series: pd.Series, limit: int = 10) -> list[tuple[Any, int]]:
    """Return the most common values for a column, tolerating unhashable data."""
    try:
        counts = series.value_counts(dropna=True).head(limit)
        return [(json_safe(index), int(count)) for index, count in counts.items()]
    except TypeError:
        counts = series.astype(str).value_counts(dropna=True).head(limit)
        return [(str(index), int(count)) for index, count in counts.items()]
