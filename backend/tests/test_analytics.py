"""Tests for profiling, statistics and chart-ready aggregates."""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.core.exceptions import ValidationAppError
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.dataset import CleaningRequest
from app.services.analytics_service import AnalyticsService
from app.services.cleaning_service import CleaningService
from app.services.ingestion_service import IngestionService
from tests.helpers import ANALYTICS_CSV, SAMPLE_CSV


def _dataset(db, content: str, name: str = "analytics.csv"):
    dataset, _, _ = IngestionService(db, settings).upload(name, content.encode())
    return dataset


def test_numeric_statistics_are_correct(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    profile = AnalyticsService(db, settings).profile(dataset)
    value_stats = next(item for item in profile["numeric_columns"] if item["name"] == "value")

    assert value_stats["count"] == 5
    assert value_stats["missing_count"] == 1
    assert value_stats["missing_percentage"] == pytest.approx(16.67, abs=0.01)
    assert value_stats["mean"] == pytest.approx(30.0)
    assert value_stats["median"] == pytest.approx(30.0)
    assert value_stats["minimum"] == 10
    assert value_stats["maximum"] == 50
    assert value_stats["q1"] == pytest.approx(20.0)
    assert value_stats["q3"] == pytest.approx(40.0)
    assert sum(bin_["count"] for bin_ in value_stats["histogram"]) == 5


def test_categorical_distribution(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    profile = AnalyticsService(db, settings).profile(dataset)
    group_stats = next(item for item in profile["categorical_columns"] if item["name"] == "group")
    assert group_stats["unique_count"] == 3
    counts = {item["value"]: item["count"] for item in group_stats["top_values"]}
    assert counts == {"B": 3, "A": 2, "C": 1}
    assert group_stats["top_values"][0]["percentage"] == pytest.approx(50.0)


def test_correlation_matrix(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    profile = AnalyticsService(db, settings).profile(dataset)
    assert profile["correlations"] is not None
    columns = profile["correlations"]["columns"]
    assert "value" in columns and "quantity" in columns
    index_value = columns.index("value")
    index_quantity = columns.index("quantity")
    correlation = profile["correlations"]["matrix"][index_value][index_quantity]
    assert correlation == pytest.approx(1.0, abs=0.001)
    assert profile["top_correlations"][0]["strength"] == "very strong"


def test_overview_and_quality(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    profile = AnalyticsService(db, settings).profile(dataset)
    assert profile["overview"]["row_count"] == 6
    assert profile["overview"]["numeric_column_count"] == 2
    assert profile["overview"]["categorical_column_count"] == 1
    assert profile["overview"]["datetime_column_count"] == 1
    assert profile["quality"]["missing_cells"] == 1
    assert "6 rows" in profile["summary"]


def test_time_series_detection(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    profile = AnalyticsService(db, settings).profile(dataset)
    series = profile["time_series"]
    assert series is not None
    assert series["date_column"] == "when"
    assert series["metric_column"] == "value"
    assert series["aggregation"] == "sum"
    assert len(series["points"]) == 6
    assert series["points"][0]["period"] == "2024-01"


def test_profile_uses_cache_and_refresh_recomputes(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    service = AnalyticsService(db, settings)
    service.profile(dataset)
    service.profile(dataset)
    repo = AnalysisRepository(db)
    cached = repo.list_for_dataset(dataset.id, "profile")
    assert len(cached) == 1

    service.profile(dataset, use_cache=False)
    assert len(repo.list_for_dataset(dataset.id, "profile")) == 2


def test_profile_cache_invalidated_after_cleaning(db):
    dataset = _dataset(db, ANALYTICS_CSV)
    service = AnalyticsService(db, settings)
    first = service.profile(dataset)
    assert first["source"] == "original"

    CleaningService(db, settings).clean(
        dataset,
        CleaningRequest(drop_duplicates=True, missing_strategy="fill_median"),
    )
    refreshed = service.profile(dataset)
    assert refreshed["source"] == "cleaned"
    assert refreshed["overview"]["missing_cells"] == 0


def test_works_with_different_column_names(db):
    dataset = _dataset(db, "amount,segment\n5,Retail\n15,Wholesale\n25,Retail\n", "other.csv")
    profile = AnalyticsService(db, settings).profile(dataset)
    assert profile["numeric_columns"][0]["name"] == "amount"
    assert profile["numeric_columns"][0]["mean"] == 15
    assert profile["categorical_columns"][0]["name"] == "segment"


def test_sample_dataset_profile_calculates_actual_values(db):
    dataset = _dataset(db, SAMPLE_CSV, "sales.csv")
    profile = AnalyticsService(db, settings).profile(dataset)
    revenue = next(item for item in profile["numeric_columns"] if item["name"] == "revenue")
    # Verified from the fixture: one missing revenue value among 11 rows.
    assert revenue["count"] == 10
    assert revenue["missing_count"] == 1
    assert revenue["mean"] == pytest.approx(148.6, abs=0.01)
    assert profile["overview"]["duplicate_rows"] == 1
    assert profile["time_series"] is not None


def test_empty_dataset_raises(db):
    dataset = _dataset(db, "value\n1\n")
    # Force an empty active file through a manual dataset record.
    from pathlib import Path

    path = Path(dataset.storage_path)
    path.write_text("value\n")
    with pytest.raises(ValidationAppError):
        AnalyticsService(db, settings).profile(dataset, use_cache=False)
