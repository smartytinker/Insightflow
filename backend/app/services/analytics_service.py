"""Exploratory data analysis and dataset profiling.

All statistics are computed from the actual dataset; nothing is hardcoded.
Results are cached per dataset version and persisted as JSON.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.dataset import Dataset
from app.repositories.analysis_repository import AnalysisRepository
from app.utils.data_validation import (
    categorical_columns,
    datetime_columns,
    load_dataframe,
    numeric_columns,
    quality_summary,
)
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)

_HISTOGRAM_BINS = 12
_TOP_VALUES = 10
_MAX_TIME_POINTS = 500
_CACHE_VERSION = 3


class AnalyticsService:
    """Computes profiles, descriptive statistics and chart-ready data."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repo = AnalysisRepository(db)

    # ------------------------------------------------------------------ public

    def profile(self, dataset: Dataset, use_cache: bool = True) -> dict[str, Any]:
        """Return a full dataset profile, using a cached result when valid."""
        cached = self._cached(dataset, "profile", use_cache)
        if cached is not None:
            return cached

        df = load_dataframe(dataset.active_path, self.settings)
        if df.empty:
            raise ValidationAppError("The dataset has no rows to analyze.")

        result = self._build_profile(dataset, df)
        self._store(dataset, "profile", result)
        return result

    def statistics(self, dataset: Dataset, use_cache: bool = True) -> dict[str, Any]:
        """Return descriptive statistics; derived from the cached profile."""
        cached = self._cached(dataset, "statistics", use_cache)
        if cached is not None:
            return cached

        profile = self.profile(dataset, use_cache=use_cache)
        result = {
            "dataset_id": profile["dataset_id"],
            "generated_at": datetime.now(UTC).isoformat(),
            "overview": profile["overview"],
            "numeric_columns": profile["numeric_columns"],
            "categorical_columns": profile["categorical_columns"],
            "datetime_columns": profile["datetime_columns"],
            "correlations": profile["correlations"],
            "missing_values": profile["quality"]["columns_with_missing_values"],
        }
        # Missing values mapping should be column -> count, not a list.
        df = load_dataframe(dataset.active_path, self.settings)
        result["missing_values"] = {
            str(column): int(count) for column, count in df.isna().sum().items() if count > 0
        }
        self._store(dataset, "statistics", result)
        return result

    def invalidate(self, dataset: Dataset) -> None:
        """Drop cached analyses after a cleaning run changes the dataset."""
        # Cached results are also validated by file mtime, so this is best-effort.
        logger.debug("Analysis cache invalidation requested for dataset %s", dataset.id)

    # ----------------------------------------------------------------- internal

    def _cached(
        self, dataset: Dataset, analysis_type: str, use_cache: bool
    ) -> dict[str, Any] | None:
        if not use_cache:
            return None
        record = self.repo.latest(dataset.id, analysis_type)
        if record is None:
            return None
        payload = record.result_json or {}
        if payload.get("cache_version") != _CACHE_VERSION:
            return None
        if payload.get("source_path") != dataset.active_path:
            return None
        try:
            current_mtime = Path(dataset.active_path).stat().st_mtime
        except OSError:
            return None
        if abs(float(payload.get("source_mtime", -1)) - current_mtime) > 0.001:
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    def _store(self, dataset: Dataset, analysis_type: str, result: dict[str, Any]) -> None:
        try:
            mtime = Path(dataset.active_path).stat().st_mtime
        except OSError:
            mtime = 0.0
        try:
            self.repo.save(
                dataset.id,
                analysis_type,
                {
                    "cache_version": _CACHE_VERSION,
                    "source_path": dataset.active_path,
                    "source_mtime": mtime,
                    "result": result,
                },
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.warning(
                "Could not cache %s analysis for %s", analysis_type, dataset.id, exc_info=True
            )

    def _build_profile(self, dataset: Dataset, df: pd.DataFrame) -> dict[str, Any]:
        quality = quality_summary(df)
        numeric_cols = numeric_columns(df)
        date_cols = datetime_columns(df)
        category_cols = categorical_columns(df)

        numeric_stats = [self._numeric_stats(df[column]) for column in numeric_cols]
        categorical_stats = [self._categorical_stats(df[column]) for column in category_cols]
        datetime_stats = [self._datetime_stats(df[column]) for column in date_cols]
        correlations, top_correlations = self._correlations(df, numeric_cols)
        time_series = self._time_series(df, date_cols, numeric_cols)

        overview = {
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "numeric_column_count": len(numeric_cols),
            "categorical_column_count": len(category_cols),
            "datetime_column_count": len(date_cols),
            "missing_cells": quality.missing_cells,
            "missing_percentage": quality.missing_percentage,
            "duplicate_rows": quality.duplicate_rows,
            "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
        }
        quality_issues = self._quality_issues(df, numeric_stats, categorical_stats, quality)
        important_columns = self._important_columns(
            numeric_stats, categorical_stats, datetime_stats
        )
        summary = self._summary(
            df, numeric_stats, categorical_stats, datetime_stats, top_correlations, quality
        )

        return {
            "dataset_id": dataset.id,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "cleaned" if dataset.is_cleaned else "original",
            "overview": overview,
            "quality": quality.model_dump(),
            "numeric_columns": numeric_stats,
            "categorical_columns": categorical_stats,
            "datetime_columns": datetime_stats,
            "correlations": correlations,
            "top_correlations": top_correlations,
            "time_series": time_series,
            "quality_issues": quality_issues,
            "important_columns": important_columns,
            "summary": summary,
        }

    def _numeric_stats(self, series: pd.Series) -> dict[str, Any]:
        total = len(series)
        non_null = pd.to_numeric(series, errors="coerce").dropna()
        missing = total - len(non_null)
        base: dict[str, Any] = {
            "name": str(series.name),
            "count": int(len(non_null)),
            "missing_count": int(missing),
            "missing_percentage": round(missing / max(total, 1) * 100, 2),
            "mean": None,
            "median": None,
            "std": None,
            "minimum": None,
            "maximum": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "skewness": None,
            "outlier_count": 0,
            "histogram": [],
        }
        if non_null.empty:
            return base

        q1 = float(non_null.quantile(0.25))
        q3 = float(non_null.quantile(0.75))
        iqr = q3 - q1
        outlier_count = 0
        if iqr > 0:
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outlier_count = int(((non_null < lower) | (non_null > upper)).sum())

        base.update(
            {
                "mean": json_safe(non_null.mean()),
                "median": json_safe(non_null.median()),
                "std": json_safe(non_null.std()),
                "minimum": json_safe(non_null.min()),
                "maximum": json_safe(non_null.max()),
                "q1": q1,
                "q3": q3,
                "iqr": iqr,
                "skewness": json_safe(non_null.skew()) if len(non_null) > 2 else None,
                "outlier_count": outlier_count,
                "histogram": self._histogram(non_null),
            }
        )
        return base

    @staticmethod
    def _histogram(values: pd.Series) -> list[dict[str, Any]]:
        try:
            counts, edges = np.histogram(values.to_numpy(dtype=float), bins=_HISTOGRAM_BINS)
        except (ValueError, TypeError):
            return []
        return [
            {"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ]

    @staticmethod
    def _categorical_stats(series: pd.Series) -> dict[str, Any]:
        total = len(series)
        non_null = series.dropna()
        missing = total - len(non_null)
        try:
            unique_count = int(non_null.nunique())
        except TypeError:
            unique_count = int(non_null.astype(str).nunique())
        counts = non_null.value_counts(dropna=True).head(_TOP_VALUES)
        denominator = max(len(non_null), 1)
        top_values = [
            {
                "value": json_safe(value),
                "count": int(count),
                "percentage": round(int(count) / denominator * 100, 2),
            }
            for value, count in counts.items()
        ]
        return {
            "name": str(series.name),
            "count": int(len(non_null)),
            "missing_count": int(missing),
            "missing_percentage": round(missing / max(total, 1) * 100, 2),
            "unique_count": unique_count,
            "top_values": top_values,
            "frequency_distribution": top_values,
        }

    @staticmethod
    def _datetime_stats(series: pd.Series) -> dict[str, Any]:
        total = len(series)
        non_null = series.dropna()
        missing = total - len(non_null)
        minimum = non_null.min() if not non_null.empty else None
        maximum = non_null.max() if not non_null.empty else None
        span_days = None
        if minimum is not None and maximum is not None:
            span_days = float((maximum - minimum).total_seconds() / 86400)
        return {
            "name": str(series.name),
            "count": int(len(non_null)),
            "missing_count": int(missing),
            "missing_percentage": round(missing / max(total, 1) * 100, 2),
            "minimum": json_safe(minimum),
            "maximum": json_safe(maximum),
            "span_days": span_days,
        }

    @staticmethod
    def _correlations(
        df: pd.DataFrame, numeric_cols: list[str]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        usable = [column for column in numeric_cols if df[column].nunique(dropna=True) > 1]
        if len(usable) < 2:
            return None, []
        matrix = df[usable].corr(numeric_only=True)
        columns = [str(column) for column in matrix.columns]
        values = [
            [json_safe(matrix.iloc[row, col]) for col in range(len(columns))]
            for row in range(len(columns))
        ]
        pairs: list[dict[str, Any]] = []
        for i, column_a in enumerate(columns):
            for j in range(i + 1, len(columns)):
                value = matrix.iloc[i, j]
                if pd.isna(value):
                    continue
                strength = AnalyticsService._correlation_strength(float(value))
                pairs.append(
                    {
                        "column_a": column_a,
                        "column_b": columns[j],
                        "correlation": round(float(value), 4),
                        "strength": strength,
                    }
                )
        pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)
        return {"columns": columns, "matrix": values}, pairs[:8]

    @staticmethod
    def _correlation_strength(value: float) -> str:
        magnitude = abs(value)
        if magnitude >= 0.8:
            return "very strong"
        if magnitude >= 0.6:
            return "strong"
        if magnitude >= 0.4:
            return "moderate"
        if magnitude >= 0.2:
            return "weak"
        return "very weak"

    def _time_series(
        self, df: pd.DataFrame, date_cols: list[str], numeric_cols: list[str]
    ) -> dict[str, Any] | None:
        if not date_cols:
            return None
        date_column = next((c for c in date_cols if "date" in str(c).lower()), date_cols[0])
        metric_candidates = [
            c
            for c in numeric_cols
            if any(
                token in str(c).lower()
                for token in ("revenue", "sales", "amount", "total", "value")
            )
        ]
        metric_column = (
            metric_candidates[0]
            if metric_candidates
            else (numeric_cols[0] if numeric_cols else None)
        )
        dates = pd.to_datetime(df[date_column], errors="coerce")
        if dates.dropna().empty:
            return None
        span_days = (dates.max() - dates.min()).total_seconds() / 86400
        granularity = "D" if span_days <= 90 else "M"
        resample_rule = "D" if granularity == "D" else "ME"

        frame = pd.DataFrame({"date": dates})
        if metric_column:
            frame["value"] = pd.to_numeric(df[metric_column], errors="coerce")
            grouped = frame.set_index("date").resample(resample_rule)
            values = grouped["value"].sum(min_count=0)
            counts = grouped.size()
            aggregation = "sum"
        else:
            grouped = frame.set_index("date").resample(resample_rule)
            values = grouped.size().astype(float)
            counts = grouped.size()
            aggregation = "count"

        points = [
            {
                "period": self._period_label(index, granularity),
                "value": json_safe(value),
                "record_count": int(counts.loc[index]),
            }
            for index, value in values.items()
            if int(counts.loc[index]) > 0
        ]
        if len(points) > _MAX_TIME_POINTS:
            step = int(np.ceil(len(points) / _MAX_TIME_POINTS))
            points = points[::step]
        return {
            "date_column": str(date_column),
            "metric_column": str(metric_column) if metric_column else "record_count",
            "aggregation": aggregation,
            "granularity": "day" if granularity == "D" else "month",
            "points": points,
        }

    @staticmethod
    def _period_label(index: pd.Timestamp, granularity: str) -> str:
        return index.strftime("%Y-%m") if granularity == "M" else index.strftime("%Y-%m-%d")

    def _quality_issues(
        self,
        df: pd.DataFrame,
        numeric_stats: list[dict[str, Any]],
        categorical_stats: list[dict[str, Any]],
        quality: Any,
    ) -> list[str]:
        issues: list[str] = []
        if quality.missing_cells:
            worst = sorted(
                ((column, float(df[column].isna().mean() * 100)) for column in df.columns),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
            for column, percentage in worst:
                if percentage >= 20:
                    issues.append(f"Column '{column}' has {percentage:.1f}% missing values.")
        if quality.duplicate_rows:
            issues.append(
                f"{quality.duplicate_rows:,} duplicate row(s) detected "
                f"({quality.duplicate_rows / max(quality.total_rows, 1) * 100:.2f}% of rows)."
            )
        for column in df.columns:
            if df[column].isna().all():
                issues.append(f"Column '{column}' contains no usable values.")
            elif df[column].nunique(dropna=True) == 1:
                issues.append(f"Column '{column}' has a single constant value.")
        for stats in numeric_stats:
            if stats["outlier_count"] and stats["count"]:
                share = stats["outlier_count"] / stats["count"] * 100
                if share >= 2:
                    issues.append(
                        f"Column '{stats['name']}' contains {stats['outlier_count']:,} "
                        f"IQR outlier(s) ({share:.1f}% of values)."
                    )
        for stats in categorical_stats:
            if stats["count"] and stats["unique_count"] > 50:
                ratio = stats["unique_count"] / stats["count"]
                if ratio > 0.5:
                    issues.append(
                        f"Column '{stats['name']}' is high-cardinality "
                        f"({stats['unique_count']:,} unique values)."
                    )
        return issues[:10]

    @staticmethod
    def _important_columns(
        numeric_stats: list[dict[str, Any]],
        categorical_stats: list[dict[str, Any]],
        datetime_stats: list[dict[str, Any]],
    ) -> list[str]:
        important: list[str] = []
        for stats in numeric_stats[:4]:
            important.append(stats["name"])
        for stats in sorted(categorical_stats, key=lambda s: s["unique_count"])[:2]:
            if 1 < stats["unique_count"] <= 50:
                important.append(stats["name"])
        for stats in datetime_stats[:1]:
            important.append(stats["name"])
        return list(dict.fromkeys(important))

    @staticmethod
    def _summary(
        df: pd.DataFrame,
        numeric_stats: list[dict[str, Any]],
        categorical_stats: list[dict[str, Any]],
        datetime_stats: list[dict[str, Any]],
        top_correlations: list[dict[str, Any]],
        quality: Any,
    ) -> str:
        parts = [
            f"The dataset contains {df.shape[0]:,} rows and {df.shape[1]} columns "
            f"({len(numeric_stats)} numeric, {len(categorical_stats)} categorical, "
            f"{len(datetime_stats)} datetime)."
        ]
        if quality.missing_cells:
            parts.append(
                f"{quality.missing_cells:,} cells ({quality.missing_percentage:.2f}%) are missing "
                f"across {len(quality.columns_with_missing_values)} column(s)."
            )
        else:
            parts.append("No missing values were detected.")
        if quality.duplicate_rows:
            parts.append(f"{quality.duplicate_rows:,} duplicate rows are present.")
        else:
            parts.append("No duplicate rows were detected.")

        for stats in categorical_stats[:2]:
            if (
                stats["top_values"]
                and stats["unique_count"] <= 50
                and not str(stats["name"]).lower().endswith("_id")
            ):
                top = stats["top_values"][0]
                parts.append(
                    f"The most frequent value in '{stats['name']}' is "
                    f"{top['value']!r} ({top['percentage']:.1f}% of non-null values)."
                )
        if top_correlations:
            pair = top_correlations[0]
            parts.append(
                f"The strongest correlation is between '{pair['column_a']}' and "
                f"'{pair['column_b']}' (r={pair['correlation']:.3f}, {pair['strength']})."
            )
        if datetime_stats and datetime_stats[0]["minimum"]:
            parts.append(
                f"Time coverage spans {str(datetime_stats[0]['minimum'])[:10]} to "
                f"{str(datetime_stats[0]['maximum'])[:10]}."
            )
        return " ".join(parts)
