"""Reusable data cleaning engine.

Cleaning always starts from the original upload and writes a new CSV copy.
The original file is never modified, so a user can re-run cleaning with a
different configuration without compounding earlier transformations.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.dataset import Dataset
from app.repositories.cleaning_repository import CleaningRepository
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.dataset import CleaningRequest
from app.utils.data_validation import load_dataframe, numeric_columns
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")
_TRUE_VALUES = {"true", "1", "yes", "y", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "f"}


def normalize_column_name(name: str, case: str = "snake") -> str:
    """Normalize a column name into a safe identifier.

    ``snake`` lowercases and replaces separators with underscores; ``lower``
    only lowercases; ``preserve`` keeps the trimmed original name.
    """
    cleaned = str(name).strip()
    if case == "preserve":
        return cleaned or "column"
    result = cleaned.lower() if case == "lower" else _NON_ALNUM.sub("_", cleaned).strip("_").lower()
    return result or "column"


class CleaningService:
    """Applies configurable, recorded cleaning operations to a dataset copy."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.dataset_repo = DatasetRepository(db)
        self.cleaning_repo = CleaningRepository(db)

    def clean(self, dataset: Dataset, request: CleaningRequest) -> dict[str, Any]:
        """Run the configured cleaning pipeline and persist a new version."""
        original = load_dataframe(dataset.storage_path, self.settings)
        if original.empty:
            raise ValidationAppError("The dataset has no rows to clean.")

        unknown_strategies = [c for c in request.column_strategies if c not in original.columns]
        unknown_outliers = [c for c in request.outlier_columns if c not in original.columns]
        if unknown_strategies or unknown_outliers:
            unknown = sorted(set(unknown_strategies + unknown_outliers))
            raise ValidationAppError(
                f"Unknown cleaning columns: {', '.join(unknown)}.",
                details={"missing_columns": unknown},
            )

        before_preview = self._preview(original)
        original_row_count, original_column_count = original.shape
        missing_before = int(original.isna().sum().sum())

        df = original.copy(deep=True)
        operations: list[dict[str, Any]] = []
        warnings: list[str] = []
        transformed_columns: list[str] = []

        # 1. Column removal
        if request.drop_columns:
            missing = [c for c in request.drop_columns if c not in df.columns]
            if missing:
                raise ValidationAppError(
                    f"Cannot drop unknown columns: {', '.join(missing)}.",
                    details={"missing_columns": missing},
                )
            df = df.drop(columns=request.drop_columns)
            operations.append(
                {
                    "operation_type": "drop_columns",
                    "operation_details": {"columns": request.drop_columns},
                    "records_affected": 0,
                }
            )

        # 2. Type conversions
        if request.type_conversions:
            missing = [c for c in request.type_conversions if c not in df.columns]
            if missing:
                raise ValidationAppError(
                    f"Cannot convert unknown columns: {', '.join(missing)}.",
                    details={"missing_columns": missing},
                )
            converted: list[str] = []
            for column, target in request.type_conversions.items():
                series, invalid = self._convert_series(df[column], target)
                df[column] = series
                converted.append(column)
                if invalid:
                    warnings.append(
                        f"{invalid} value(s) in '{column}' could not be converted to {target} "
                        "and were set to missing."
                    )
            transformed_columns.extend(converted)
            operations.append(
                {
                    "operation_type": "convert_types",
                    "operation_details": {
                        "columns": request.type_conversions,
                    },
                    "records_affected": len(converted),
                }
            )

        # 3. Duplicate removal
        duplicates_removed = 0
        if request.drop_duplicates:
            duplicates_removed = int(df.duplicated().sum())
            if duplicates_removed:
                df = df.drop_duplicates(keep="first").reset_index(drop=True)
            operations.append(
                {
                    "operation_type": "drop_duplicates",
                    "operation_details": {"kept": "first"},
                    "records_affected": duplicates_removed,
                }
            )

        # 4. Missing values (global strategy with per-column overrides)
        df, missing_operations, rows_removed, cells_filled = self._handle_missing_values(
            df, request, warnings
        )
        operations.extend(missing_operations)

        # 5. Outliers
        outlier_operation = self._handle_outliers(df, request, warnings)
        if outlier_operation:
            operations.append(outlier_operation)

        # 6. Column normalization (last so configuration uses original names)
        if request.normalize_columns:
            df, rename_map = self._normalize_columns(df, request.column_case)
            if rename_map:
                transformed_columns.extend(rename_map.values())
                operations.append(
                    {
                        "operation_type": "normalize_columns",
                        "operation_details": {"renamed": rename_map},
                        "records_affected": 0,
                    }
                )

        if df.shape[1] == 0:
            raise ValidationAppError("Cleaning would remove every column.")
        if df.empty:
            warnings.append("Cleaning removed every row. The cleaned dataset is empty.")

        # 7. Persist the cleaned copy
        processed_path = (self.settings.processed_path / f"{dataset.id}_cleaned.csv").resolve()
        try:
            processed_path.relative_to(self.settings.storage_dir.resolve())
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValidationAppError("Invalid processing path.") from exc

        stored_operations: list[Any] = []
        try:
            self.settings.ensure_directories()
            self._atomic_write_csv(df, processed_path)
            for operation in operations:
                stored_operations.append(
                    self.cleaning_repo.add(
                        dataset_id=dataset.id,
                        operation_type=operation["operation_type"],
                        operation_details=operation["operation_details"],
                        records_affected=operation["records_affected"],
                    )
                )
            self.dataset_repo.update(
                dataset,
                cleaned_path=str(processed_path),
                cleaned_row_count=int(df.shape[0]),
                column_count=int(df.shape[1]),
                processing_status="cleaned",
                column_metadata=self._column_metadata(df),
            )
            self.db.commit()
            for operation in stored_operations:
                self.db.refresh(operation)
        except Exception:
            self.db.rollback()
            processed_path.unlink(missing_ok=True)
            raise

        if rows_removed:
            warnings.append(f"{rows_removed} row(s) were removed because of missing values.")
        summary = {
            "dataset_id": dataset.id,
            "original_row_count": int(original_row_count),
            "final_row_count": int(df.shape[0]),
            "original_column_count": int(original_column_count),
            "final_column_count": int(df.shape[1]),
            "missing_values_before": missing_before,
            "missing_values_after": int(df.isna().sum().sum()),
            "missing_values_filled": cells_filled,
            "duplicates_removed": duplicates_removed,
            "columns_transformed": sorted(set(transformed_columns)),
            "operations": [self._operation_dict(op) for op in stored_operations],
            "warnings": warnings,
            "before_preview": before_preview,
            "after_preview": self._preview(df),
            "cleaned_file_available": processed_path.exists(),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        logger.info(
            "Cleaned dataset %s: %s -> %s rows, %s operations",
            dataset.id,
            original_row_count,
            df.shape[0],
            len(operations),
        )
        return summary

    def history(self, dataset: Dataset) -> list[Any]:
        """Return recorded cleaning operations for a dataset, newest first."""
        return self.cleaning_repo.list_for_dataset(dataset.id)

    def _handle_missing_values(
        self, df: pd.DataFrame, request: CleaningRequest, warnings: list[str]
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], int, int]:
        """Apply global and per-column missing value strategies.

        Returns the transformed frame, recorded operations, rows removed and
        individual cells filled.
        """
        strategy_map: dict[str, tuple[str, Any]] = {}
        for column in df.columns:
            if request.missing_strategy != "none":
                strategy_map[column] = (request.missing_strategy, request.fill_value)
            if column in request.column_strategies:
                strategy_map[column] = (
                    request.column_strategies[column],
                    request.fill_value,
                )

        grouped: dict[tuple[str, Any], list[str]] = defaultdict(list)
        for column, (strategy, fill_value) in strategy_map.items():
            if strategy == "none":
                continue
            grouped[(strategy, fill_value)].append(column)

        operations: list[dict[str, Any]] = []
        rows_removed = 0
        cells_filled_total = 0

        for (strategy, fill_value), columns in grouped.items():
            columns = [c for c in columns if c in df.columns and df[c].isna().any()]
            if not columns:
                continue

            if strategy == "drop_rows":
                before = len(df)
                df = df.dropna(subset=columns).reset_index(drop=True)
                rows_removed += before - len(df)
                operations.append(
                    {
                        "operation_type": "drop_missing_rows",
                        "operation_details": {"columns": columns},
                        "records_affected": before - len(df),
                    }
                )
                continue

            cells_filled = 0
            applied: list[str] = []
            for column in columns:
                series = df[column]
                filled: pd.Series | None = None
                if strategy == "fill_mean":
                    if not pd.api.types.is_numeric_dtype(series):
                        warnings.append(
                            f"Cannot fill '{column}' with the mean (not numeric); skipped."
                        )
                        continue
                    filled = series.fillna(series.mean())
                elif strategy == "fill_median":
                    if not pd.api.types.is_numeric_dtype(series):
                        warnings.append(
                            f"Cannot fill '{column}' with the median (not numeric); skipped."
                        )
                        continue
                    filled = series.fillna(series.median())
                elif strategy == "fill_mode":
                    mode = series.mode(dropna=True)
                    if mode.empty:
                        warnings.append(
                            f"Cannot fill '{column}' with the mode (no values); skipped."
                        )
                        continue
                    filled = series.fillna(mode.iloc[0])
                elif strategy == "fill_constant":
                    if fill_value is None:
                        warnings.append(
                            f"Cannot fill '{column}' with a constant (no fill value); skipped."
                        )
                        continue
                    filled = series.fillna(fill_value)
                elif strategy == "fill_zero":
                    zero: Any = 0 if pd.api.types.is_numeric_dtype(series) else "0"
                    filled = series.fillna(zero)

                if filled is None:
                    continue
                missing_before = int(series.isna().sum())
                df[column] = filled
                filled_count = missing_before - int(df[column].isna().sum())
                cells_filled += filled_count
                if filled_count:
                    applied.append(column)
            cells_filled_total += cells_filled

            if applied:
                operations.append(
                    {
                        "operation_type": "fill_missing",
                        "operation_details": {
                            "strategy": strategy,
                            "columns": applied,
                            **({"fill_value": fill_value} if strategy == "fill_constant" else {}),
                        },
                        "records_affected": cells_filled,
                    }
                )

        return df, operations, rows_removed, cells_filled_total

    def _handle_outliers(
        self, df: pd.DataFrame, request: CleaningRequest, warnings: list[str]
    ) -> dict[str, Any] | None:
        if request.outlier_action == "none":
            return None
        candidates = request.outlier_columns or numeric_columns(df)
        candidates = [c for c in candidates if c in df.columns]
        if not candidates:
            warnings.append("No numeric columns were available for outlier handling.")
            return None

        bounds: dict[str, dict[str, float]] = {}
        affected = 0
        if request.outlier_action == "remove":
            mask = pd.Series(False, index=df.index)
            for column in candidates:
                series = pd.to_numeric(df[column], errors="coerce")
                if series.dropna().empty:
                    continue
                q1, q3 = series.quantile(0.25), series.quantile(0.75)
                iqr = q3 - q1
                if iqr == 0:
                    continue
                lower = float(q1 - request.outlier_iqr_multiplier * iqr)
                upper = float(q3 + request.outlier_iqr_multiplier * iqr)
                bounds[column] = {"lower": lower, "upper": upper}
                mask |= (series < lower) | (series > upper)
            affected = int(mask.sum())
            if affected:
                df.drop(index=df.index[mask], inplace=True)
                df.reset_index(drop=True, inplace=True)
            operation_type = "remove_outliers"
        else:  # clip
            for column in candidates:
                series = pd.to_numeric(df[column], errors="coerce")
                if series.dropna().empty:
                    continue
                q1, q3 = series.quantile(0.25), series.quantile(0.75)
                iqr = q3 - q1
                if iqr == 0:
                    continue
                lower = float(q1 - request.outlier_iqr_multiplier * iqr)
                upper = float(q3 + request.outlier_iqr_multiplier * iqr)
                bounds[column] = {"lower": lower, "upper": upper}
                clipped = (series < lower) | (series > upper)
                affected += int(clipped.sum())
                df[column] = series.clip(lower=lower, upper=upper)
            operation_type = "clip_outliers"

        if not bounds:
            warnings.append("Outlier handling skipped: no numeric column had sufficient spread.")
            return None
        return {
            "operation_type": operation_type,
            "operation_details": {
                "method": "IQR",
                "multiplier": request.outlier_iqr_multiplier,
                "bounds": bounds,
            },
            "records_affected": affected,
        }

    def _normalize_columns(
        self, df: pd.DataFrame, case: str
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        rename_map: dict[str, str] = {}
        used: set[str] = set()
        for column in df.columns:
            candidate = normalize_column_name(column, case)
            unique = candidate
            suffix = 2
            while unique in used:
                unique = f"{candidate}_{suffix}"
                suffix += 1
            used.add(unique)
            if unique != column:
                rename_map[str(column)] = unique
        if rename_map:
            df = df.rename(columns=rename_map)
        return df, rename_map

    @staticmethod
    def _convert_series(series: pd.Series, target: str) -> tuple[pd.Series, int]:
        original_missing = int(series.isna().sum())
        invalid = 0
        if target == "numeric":
            cleaned = series
            if series.dtype == object:
                cleaned = series.astype(str).str.replace(",", "", regex=False)
                cleaned = cleaned.replace({"": None, "nan": None, "None": None})
            converted = pd.to_numeric(cleaned, errors="coerce")
            invalid = int(converted.isna().sum() - original_missing)
            return converted, max(invalid, 0)
        if target == "datetime":
            converted = pd.to_datetime(series, errors="coerce", format="mixed")
            invalid = int(converted.isna().sum() - original_missing)
            return converted, max(invalid, 0)
        if target == "string":
            return series.astype("string"), 0
        if target == "category":
            return series.astype("category"), 0
        if target == "boolean":
            mapping = {**{v: True for v in _TRUE_VALUES}, **{v: False for v in _FALSE_VALUES}}
            lowered = series.astype(str).str.strip().str.lower().map(mapping)
            converted = lowered.astype("boolean")
            invalid = int(converted.isna().sum() - original_missing)
            return converted, max(invalid, 0)
        return series, 0

    @staticmethod
    def _preview(df: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {str(key): json_safe(value) for key, value in record.items()}
            for record in df.head(limit).to_dict(orient="records")
        ]

    @staticmethod
    def _column_metadata(df: pd.DataFrame) -> list[dict[str, Any]]:
        from app.utils.data_validation import column_metadata

        return column_metadata(df)

    @staticmethod
    def _operation_dict(operation: Any) -> dict[str, Any]:
        return {
            "id": operation.id,
            "operation_type": operation.operation_type,
            "operation_details": json_safe(operation.operation_details),
            "records_affected": operation.records_affected,
            "created_at": operation.created_at,
        }

    @staticmethod
    def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        df.to_csv(temp_path, index=False)
        os.replace(temp_path, path)
