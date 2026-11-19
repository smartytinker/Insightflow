"""Report generation for datasets, analysis and anomaly exports."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.chat import ChatMessage, ChatSession
from app.models.dataset import Dataset
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.cleaning_repository import CleaningRepository
from app.services.analytics_service import AnalyticsService
from app.utils.data_validation import load_dataframe
from app.utils.serialization import json_safe


class ReportService:
    """Builds consolidated JSON reports and CSV exports."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.analytics = AnalyticsService(db, settings)
        self.analysis_repo = AnalysisRepository(db)
        self.cleaning_repo = CleaningRepository(db)

    def build_report(self, dataset: Dataset) -> dict[str, Any]:
        """Assemble a report from stored and freshly computed analytical data."""
        report: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset": {
                "id": dataset.id,
                "filename": dataset.original_filename,
                "file_size": dataset.file_size,
                "row_count": dataset.row_count,
                "column_count": dataset.column_count,
                "upload_timestamp": json_safe(dataset.upload_timestamp),
                "processing_status": dataset.processing_status,
                "is_cleaned": dataset.is_cleaned,
                "cleaned_row_count": dataset.cleaned_row_count,
                "checksum": dataset.checksum,
            },
            "cleaning_history": [
                {
                    "id": operation.id,
                    "operation_type": operation.operation_type,
                    "operation_details": json_safe(operation.operation_details),
                    "records_affected": operation.records_affected,
                    "created_at": json_safe(operation.created_at),
                }
                for operation in self.cleaning_repo.list_for_dataset(dataset.id)
            ],
            "profile": None,
            "anomalies": None,
            "chat": self._chat_activity(dataset.id),
            "downloads": {
                "dataset_csv": f"/api/v1/datasets/{dataset.id}/report/dataset.csv",
                "anomalies_csv": f"/api/v1/datasets/{dataset.id}/report/anomalies.csv",
            },
        }

        try:
            profile = self.analytics.profile(dataset)
            report["profile"] = profile
        except ValidationAppError:
            report["profile"] = None

        latest_anomaly = self.analysis_repo.latest_anomaly(dataset.id)
        if latest_anomaly is not None:
            payload = latest_anomaly.result_json or {}
            report["anomalies"] = {
                "id": latest_anomaly.id,
                "created_at": json_safe(latest_anomaly.created_at),
                "total_records": latest_anomaly.total_records,
                "anomalies_detected": latest_anomaly.anomalies_detected,
                "anomaly_percentage": latest_anomaly.anomaly_percentage,
                "contamination": latest_anomaly.contamination,
                "n_estimators": latest_anomaly.n_estimators,
                "random_state": latest_anomaly.random_state,
                "features": latest_anomaly.features,
                "interpretation": payload.get("interpretation"),
                "disclaimer": payload.get("disclaimer"),
            }
        return report

    def anomaly_csv(self, dataset: Dataset) -> tuple[bytes, str]:
        """Export the stored anomaly records as CSV."""
        record = self.analysis_repo.latest_anomaly(dataset.id)
        if record is None:
            raise ValidationAppError(
                "No anomaly detection run exists for this dataset. Run anomaly detection first."
            )
        payload = record.result_json or {}
        anomalies = payload.get("anomalies") or []
        if not anomalies:
            raise ValidationAppError("The latest anomaly run contains no anomalous records.")

        value_columns: list[str] = []
        for anomaly in anomalies:
            for column in anomaly.get("values") or {}:
                if column not in value_columns:
                    value_columns.append(column)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["row_number", "anomaly_score", "rank", *value_columns])
        for anomaly in anomalies:
            values = anomaly.get("values") or {}
            writer.writerow(
                [
                    anomaly.get("row_number"),
                    anomaly.get("anomaly_score"),
                    anomaly.get("rank"),
                    *[json_safe(values.get(column)) for column in value_columns],
                ]
            )
        filename = f"insightflow_anomalies_{dataset.id[:8]}.csv"
        return buffer.getvalue().encode("utf-8"), filename

    def dataset_csv(self, dataset: Dataset) -> tuple[bytes, str]:
        """Export the active (original or cleaned) dataset as CSV."""
        from app.utils.data_validation import resolve_storage_path

        path = resolve_storage_path(dataset.active_path, self.settings)
        if not path.exists():
            raise ValidationAppError("The dataset file is no longer available.")
        prefix = "cleaned" if dataset.is_cleaned else "original"
        filename = f"insightflow_{prefix}_{dataset.id[:8]}.csv"
        return path.read_bytes(), filename

    def _chat_activity(self, dataset_id: str) -> dict[str, Any]:
        session_count = int(
            self.db.scalar(
                select(func.count(ChatSession.id)).where(ChatSession.dataset_id == dataset_id)
            )
            or 0
        )
        message_count = int(
            self.db.scalar(
                select(func.count(ChatMessage.id))
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatSession.dataset_id == dataset_id)
            )
            or 0
        )
        return {"session_count": session_count, "message_count": message_count}

    def data_quality_rows(self, dataset: Dataset) -> list[dict[str, Any]]:
        """Return per-column quality information for CSV exports."""
        df = load_dataframe(dataset.active_path, self.settings)
        rows = []
        for column in df.columns:
            series = df[column]
            rows.append(
                {
                    "column": str(column),
                    "dtype": str(series.dtype),
                    "missing_count": int(series.isna().sum()),
                    "missing_percentage": round(float(series.isna().mean() * 100), 2),
                    "unique_count": int(series.nunique(dropna=True)),
                }
            )
        return rows
