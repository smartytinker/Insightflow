"""Isolation Forest anomaly detection.

Detected anomalies are statistical outliers relative to the selected numeric
features. They are not necessarily errors, fraud, or invalid records; the
service never claims accuracy because no ground-truth labels are available.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.dataset import Dataset
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.anomaly import AnomalyRequest
from app.utils.data_validation import load_dataframe, numeric_columns
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)

_MIN_ROWS = 5
_MAX_STORED_ANOMALIES = 2000
_DISCLAIMER = (
    "Anomalies are statistical outliers detected by an unsupervised Isolation Forest model. "
    "They are not proof of fraud, errors or invalid records. No accuracy metric is reported "
    "because this dataset has no labeled ground truth."
)


class AnomalyService:
    """Trains an Isolation Forest and persists scored results."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repo = AnalysisRepository(db)

    def detect(self, dataset: Dataset, request: AnomalyRequest) -> dict[str, Any]:
        df = load_dataframe(dataset.active_path, self.settings)
        if df.empty:
            raise ValidationAppError("The dataset has no rows to analyze.")
        if len(df) < _MIN_ROWS:
            raise ValidationAppError(
                f"At least {_MIN_ROWS} rows are required for anomaly detection.",
                details={"rows": len(df), "minimum_rows": _MIN_ROWS},
            )

        available_numeric = [
            column
            for column in numeric_columns(df)
            if df[column].notna().any() and df[column].nunique(dropna=True) > 1
        ]
        if not available_numeric:
            raise ValidationAppError(
                "Anomaly detection requires at least one numeric column with variation.",
                details={"numeric_columns": numeric_columns(df)},
            )

        if request.features:
            missing = [c for c in request.features if c not in df.columns]
            if missing:
                raise ValidationAppError(
                    f"Unknown feature columns: {', '.join(missing)}.",
                    details={"missing_columns": missing},
                )
            non_numeric = [c for c in request.features if c not in available_numeric]
            if non_numeric:
                raise ValidationAppError(
                    "All selected features must be numeric columns with more than one value.",
                    details={"invalid_features": non_numeric, "valid_features": available_numeric},
                )
            features = list(request.features)
        else:
            features = available_numeric

        frame = df[features].apply(pd.to_numeric, errors="coerce")
        frame = frame.replace([np.inf, -np.inf], np.nan)
        usable_mask = frame.notna().any(axis=1)
        frame = frame[usable_mask]
        excluded = int((~usable_mask).sum())
        if len(frame) < _MIN_ROWS:
            raise ValidationAppError(
                f"At least {_MIN_ROWS} rows with numeric values are required after "
                "excluding rows where every selected feature is missing.",
                details={"usable_rows": len(frame)},
            )

        # Median imputation is robust to outliers and keeps rows usable.
        imputed = frame.fillna(frame.median(numeric_only=True))
        imputed = imputed.fillna(0.0)
        scaler = StandardScaler()
        matrix = scaler.fit_transform(imputed.to_numpy(dtype=float))

        model = IsolationForest(
            n_estimators=request.n_estimators,
            contamination=request.contamination,
            random_state=request.random_state,
            n_jobs=-1,
        )
        labels = model.fit_predict(matrix)
        raw_scores = model.decision_function(matrix)
        # Higher score = more anomalous. Negating the decision function gives
        # an intuitive scale while preserving ordering.
        anomaly_scores = -raw_scores

        positions = np.flatnonzero(usable_mask)
        is_anomaly = labels == -1
        anomaly_indices = np.flatnonzero(is_anomaly)
        order = anomaly_indices[np.argsort(anomaly_scores[anomaly_indices])[::-1]]

        # Feature contribution: mean absolute deviation in scaled space.
        z_scores = np.abs(matrix)
        anomaly_z = z_scores[is_anomaly]
        contributions = anomaly_z.mean(axis=0) if len(anomaly_z) else np.zeros(len(features))
        top_feature_order = np.argsort(contributions)[::-1]

        records: list[dict[str, Any]] = []
        for rank, position in enumerate(order, start=1):
            dataframe_index = int(positions[position])
            records.append(
                {
                    "row_number": dataframe_index + 2,  # +1 for header, +1 for 0-based index
                    "anomaly_score": round(float(anomaly_scores[position]), 6),
                    "is_anomaly": True,
                    "rank": rank,
                    "values": {
                        str(column): json_safe(df.iloc[dataframe_index][column])
                        for column in df.columns
                    },
                }
            )

        all_scores = [float(score) for score in anomaly_scores]
        distribution = self._score_histogram(all_scores)
        feature_statistics = self._feature_statistics(imputed, is_anomaly)

        truncated = len(records) > _MAX_STORED_ANOMALIES
        stored_records = records[:_MAX_STORED_ANOMALIES]
        anomaly_count = int(is_anomaly.sum())
        anomaly_pct = round(anomaly_count / len(df) * 100, 2)
        top_features = [features[i] for i in top_feature_order[:3]]
        interpretation = (
            f"The model analysed {len(frame):,} records across {len(features)} numeric "
            f"feature(s) and flagged {anomaly_count:,} records as statistical outliers "
            f"({anomaly_pct:.2f}% of the dataset). The features contributing most to flagged "
            f"records were {', '.join(top_features)}. Review these records in context before "
            "taking action."
        )

        generated_at = datetime.now(UTC).isoformat()
        result = {
            "dataset_id": dataset.id,
            "generated_at": generated_at,
            "source": "cleaned" if dataset.is_cleaned else "original",
            "total_records": int(len(df)),
            "anomalies_detected": anomaly_count,
            "anomaly_percentage": anomaly_pct,
            "contamination": request.contamination,
            "n_estimators": request.n_estimators,
            "random_state": request.random_state,
            "features": features,
            "records_analyzed": int(len(frame)),
            "records_excluded": excluded,
            "anomalies": stored_records,
            "anomalies_returned": len(stored_records),
            "anomalies_truncated": truncated,
            "score_distribution": distribution,
            "feature_statistics": {
                "mean": {},
                "std": {},
                "min": {},
                "max": {},
                "anomaly_mean": {},
            },
            "interpretation": interpretation,
            "disclaimer": _DISCLAIMER,
        }
        for column in features:
            series = df[column].apply(pd.to_numeric, errors="coerce")
            result["feature_statistics"]["mean"][column] = json_safe(series.mean())
            result["feature_statistics"]["std"][column] = json_safe(series.std())
            result["feature_statistics"]["min"][column] = json_safe(series.min())
            result["feature_statistics"]["max"][column] = json_safe(series.max())
            result["feature_statistics"]["anomaly_mean"][column] = feature_statistics[column]

        try:
            record = self.repo.save_anomaly(
                dataset_id=dataset.id,
                contamination=request.contamination,
                n_estimators=request.n_estimators,
                random_state=request.random_state,
                total_records=int(len(df)),
                anomalies_detected=anomaly_count,
                anomaly_percentage=anomaly_pct,
                features=features,
                result_json=result,
            )
            self.db.commit()
            result["id"] = record.id
        except Exception:
            self.db.rollback()
            raise

        logger.info(
            "Anomaly run %s for dataset %s: %s anomalies in %s rows",
            result.get("id"),
            dataset.id,
            anomaly_count,
            len(df),
        )
        return result

    def latest(self, dataset: Dataset) -> dict[str, Any]:
        """Return the most recent persisted anomaly run for a dataset."""
        record = self.repo.latest_anomaly(dataset.id)
        if record is None:
            raise ValidationAppError(
                "No anomaly detection run exists for this dataset yet.",
                details={"dataset_id": dataset.id},
            )
        return self._result_with_id(record)

    def get(self, dataset: Dataset, anomaly_id: int) -> dict[str, Any]:
        return self._result_with_id(self.repo.get_anomaly(dataset.id, anomaly_id))

    def history(self, dataset: Dataset) -> list[dict[str, Any]]:
        records = self.repo.anomaly_history(dataset.id)
        return [
            {
                "id": record.id,
                "dataset_id": record.dataset_id,
                "contamination": record.contamination,
                "n_estimators": record.n_estimators,
                "random_state": record.random_state,
                "total_records": record.total_records,
                "anomalies_detected": record.anomalies_detected,
                "anomaly_percentage": record.anomaly_percentage,
                "features": record.features,
                "created_at": record.created_at,
            }
            for record in records
        ]

    @staticmethod
    def _result_with_id(record: Any) -> dict[str, Any]:
        result = dict(record.result_json or {})
        result["id"] = record.id
        return result

    @staticmethod
    def _score_histogram(scores: list[float]) -> list[dict[str, Any]]:
        if not scores:
            return []
        try:
            counts, edges = np.histogram(np.asarray(scores, dtype=float), bins=15)
        except (ValueError, TypeError):
            return []
        return [
            {"start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ]

    @staticmethod
    def _feature_statistics(
        imputed: pd.DataFrame, is_anomaly: np.ndarray
    ) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        anomaly_rows = imputed[is_anomaly]
        for column in imputed.columns:
            value = anomaly_rows[column].mean() if len(anomaly_rows) else None
            result[str(column)] = json_safe(value)
        return result
