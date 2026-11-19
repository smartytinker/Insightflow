"""Dataset ingestion service: validation, storage and metadata extraction."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.dataset import Dataset, new_uuid
from app.repositories.dataset_repository import DatasetRepository
from app.utils.data_validation import (
    column_metadata,
    load_dataframe,
    quality_summary,
    resolve_storage_path,
)
from app.utils.file_validation import (
    compute_checksum,
    parse_csv_bytes,
    validate_uploads,
)
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)


class IngestionService:
    """Handles CSV uploads and dataset metadata.

    The original file is written once and never modified. Cleaning writes a
    separate copy under ``storage/processed``.
    """

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repo = DatasetRepository(db)

    def upload(
        self,
        filename: str | None,
        content: bytes,
        content_type: str | None = None,
    ) -> tuple[Dataset, dict[str, Any], list[dict[str, Any]]]:
        """Validate, store and register an uploaded CSV.

        Returns the dataset, its quality summary and column metadata.
        """
        safe_name = validate_uploads(filename, content, self.settings, content_type)
        df, encoding = parse_csv_bytes(content, self.settings)
        columns = column_metadata(df)
        quality = quality_summary(df)

        dataset_id = new_uuid()
        stored_name = f"{dataset_id}_{safe_name}"
        upload_path = self.settings.uploads_path / stored_name
        upload_path = upload_path.resolve()
        self._assert_within_storage(upload_path)

        dataset: Dataset | None = None
        try:
            self.settings.ensure_directories()
            self._atomic_write(upload_path, content)
            dataset = Dataset(
                id=dataset_id,
                filename=stored_name,
                original_filename=safe_name,
                file_size=len(content),
                row_count=int(df.shape[0]),
                column_count=int(df.shape[1]),
                checksum=compute_checksum(content),
                processing_status="ready",
                storage_path=str(upload_path),
                column_metadata=columns,
            )
            self.repo.add(dataset)
            self.db.commit()
            self.db.refresh(dataset)
        except Exception:
            self.db.rollback()
            if upload_path.exists():
                upload_path.unlink(missing_ok=True)
            raise

        logger.info(
            "Ingested dataset %s (%s rows x %s cols, encoding=%s)",
            dataset.id,
            df.shape[0],
            df.shape[1],
            encoding,
        )
        return dataset, quality.model_dump(), columns

    def get_dataframe(self, dataset: Dataset) -> pd.DataFrame:
        """Load the active dataset version (cleaned copy if available)."""
        return load_dataframe(dataset.active_path, self.settings)

    def preview(self, dataset: Dataset, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        """Return a paginated, JSON-safe preview of the active dataset."""
        path = resolve_storage_path(dataset.active_path, self.settings)
        rows: list[dict[str, Any]] = []
        total_rows = dataset.cleaned_row_count or dataset.row_count

        try:
            # Read only the requested window plus the header to avoid loading
            # the entire dataset into memory.
            skip = range(1, offset + 1) if offset else None
            names: list[str] = []
            frame: pd.DataFrame | None = None
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    names = list(pd.read_csv(path, nrows=0, encoding=encoding).columns)
                    frame = pd.read_csv(
                        path,
                        nrows=limit,
                        skiprows=skip,
                        encoding=encoding,
                        low_memory=False,
                    )
                    break
                except UnicodeDecodeError:
                    continue
            if frame is None:
                raise ValidationAppError("The dataset preview could not be decoded.")
        except (pd.errors.ParserError, OSError) as exc:
            raise ValidationAppError("The dataset preview could not be generated.") from exc

        for record in frame.to_dict(orient="records"):
            rows.append({str(key): json_safe(value) for key, value in record.items()})

        return {
            "dataset_id": dataset.id,
            "columns": names,
            "rows": rows,
            "total_rows": total_rows,
            "limit": limit,
            "offset": offset,
            "source": "cleaned" if dataset.is_cleaned else "original",
        }

    def delete(self, dataset: Dataset) -> None:
        """Delete a dataset and all files it owns."""
        paths = [Path(dataset.storage_path)]
        if dataset.cleaned_path:
            paths.append(Path(dataset.cleaned_path))
        try:
            self.repo.delete(dataset)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for path in paths:
            try:
                resolved = resolve_storage_path(path, self.settings)
                if resolved.exists():
                    resolved.unlink()
            except (ValidationAppError, OSError):
                logger.warning("Could not remove dataset file %s", path, exc_info=True)

    def _assert_within_storage(self, path: Path) -> None:
        try:
            path.relative_to(self.settings.storage_dir.resolve())
        except ValueError as exc:
            raise ValidationAppError("Invalid storage path.") from exc

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        """Write bytes atomically to avoid partial uploads on failure."""
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_bytes(content)
        os.replace(temp_path, path)
