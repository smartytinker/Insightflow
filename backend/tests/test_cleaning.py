"""Tests for the cleaning engine and preservation guarantees."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
from app.core.config import settings
from app.core.exceptions import ValidationAppError
from app.schemas.dataset import CleaningRequest
from app.services.cleaning_service import CleaningService, normalize_column_name
from app.services.ingestion_service import IngestionService
from tests.helpers import CLEANING_CSV, anomaly_csv


def _dataset(db, content: str, name: str = "test.csv"):
    service = IngestionService(db, settings)
    dataset, _, _ = service.upload(name, content.encode())
    return dataset


def test_fill_missing_with_median(db):
    dataset = _dataset(db, "value,label\n10,a\n20,b\n,c\n40,d\n")
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(drop_duplicates=False, missing_strategy="fill_median"),
    )
    assert summary["missing_values_before"] == 1
    assert summary["missing_values_after"] == 0
    assert summary["missing_values_filled"] == 1
    cleaned = pd.read_csv(dataset.cleaned_path)
    assert cleaned.loc[2, "value"] == 20


def test_drop_duplicates(db):
    dataset = _dataset(db, CLEANING_CSV)
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(drop_duplicates=True, normalize_columns=False),
    )
    assert summary["duplicates_removed"] == 1
    assert summary["final_row_count"] == 4
    assert dataset.cleaned_row_count == 4


def test_missing_rows_strategy(db):
    dataset = _dataset(db, "value,label\n10,a\n,b\n,c\n40,d\n")
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(drop_duplicates=False, missing_strategy="drop_rows"),
    )
    assert summary["final_row_count"] == 2
    assert any("removed" in warning for warning in summary["warnings"])


def test_type_conversion_reports_invalid_values(db):
    dataset = _dataset(db, CLEANING_CSV)
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(
            drop_duplicates=False,
            type_conversions={"Value": "numeric"},
            normalize_columns=False,
        ),
    )
    assert "Value" in summary["columns_transformed"]
    assert any("could not be converted" in warning for warning in summary["warnings"])
    cleaned = pd.read_csv(dataset.cleaned_path)
    assert pd.api.types.is_numeric_dtype(cleaned["Value"])
    assert cleaned["Value"].isna().sum() == 2  # empty + invalid text


def test_original_upload_is_never_modified(db):
    dataset = _dataset(db, CLEANING_CSV)
    original_path = Path(dataset.storage_path)
    before = hashlib.sha256(original_path.read_bytes()).hexdigest()
    service = CleaningService(db, settings)
    service.clean(
        dataset,
        CleaningRequest(
            drop_duplicates=True,
            missing_strategy="fill_mode",
            normalize_columns=True,
            column_case="snake",
        ),
    )
    after = hashlib.sha256(original_path.read_bytes()).hexdigest()
    assert before == after
    assert Path(dataset.cleaned_path).exists()
    assert Path(dataset.cleaned_path) != original_path


def test_column_normalization_and_collision_handling(db):
    dataset = _dataset(db, "Unit Price,Unit-Price,Category\n10,1,A\n20,2,B\n")
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(drop_duplicates=False, normalize_columns=True),
    )
    cleaned = pd.read_csv(dataset.cleaned_path)
    assert "unit_price" in cleaned.columns
    assert "unit_price_2" in cleaned.columns
    assert "unit_price" in summary["columns_transformed"]


def test_outlier_removal(db):
    dataset = _dataset(db, anomaly_csv(40))
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(
            drop_duplicates=False,
            outlier_action="remove",
            outlier_columns=["value"],
        ),
    )
    assert summary["final_row_count"] < summary["original_row_count"]
    cleaned = pd.read_csv(dataset.cleaned_path)
    assert cleaned["value"].max() < 1000


def test_outlier_clipping(db):
    dataset = _dataset(db, anomaly_csv(40))
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(
            drop_duplicates=False,
            outlier_action="clip",
            outlier_columns=["value"],
        ),
    )
    cleaned = pd.read_csv(dataset.cleaned_path)
    assert cleaned["value"].max() < 1000
    assert summary["final_row_count"] == summary["original_row_count"]


def test_cleaning_history_is_recorded(db):
    dataset = _dataset(db, CLEANING_CSV)
    service = CleaningService(db, settings)
    service.clean(
        dataset,
        CleaningRequest(drop_duplicates=True, normalize_columns=True),
    )
    first = service.history(dataset)
    assert first
    assert {operation.operation_type for operation in first} >= {
        "drop_duplicates",
        "normalize_columns",
    }

    service.clean(
        dataset,
        CleaningRequest(drop_duplicates=False, missing_strategy="fill_mode"),
    )
    second = service.history(dataset)
    assert len(second) > len(first)


def test_unknown_drop_column_rejected(db):
    dataset = _dataset(db, CLEANING_CSV)
    service = CleaningService(db, settings)
    with pytest.raises(ValidationAppError, match="unknown columns"):
        service.clean(
            dataset,
            CleaningRequest(drop_duplicates=False, drop_columns=["missing_column"]),
        )


def test_missing_value_warning_for_text_mean(db):
    dataset = _dataset(db, "label,value\na,1\n,2\nc,3\n")
    service = CleaningService(db, settings)
    summary = service.clean(
        dataset,
        CleaningRequest(
            drop_duplicates=False,
            missing_strategy="fill_mean",
        ),
    )
    assert summary["missing_values_after"] == 1
    assert any("not numeric" in warning for warning in summary["warnings"])


def test_unknown_override_columns_rejected(db):
    dataset = _dataset(db, CLEANING_CSV)
    service = CleaningService(db, settings)
    with pytest.raises(ValidationAppError, match="Unknown cleaning columns"):
        service.clean(
            dataset,
            CleaningRequest(
                drop_duplicates=False,
                column_strategies={"ghost_column": "fill_zero"},
            ),
        )


def test_normalize_column_name_helper():
    assert normalize_column_name("Total Revenue ($)") == "total_revenue"
    assert normalize_column_name("  Mixed CASE ", "lower") == "mixed case"
    assert normalize_column_name("Keep Me", "preserve") == "Keep Me"
