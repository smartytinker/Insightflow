"""Tests for Isolation Forest anomaly detection."""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.core.exceptions import ValidationAppError
from app.schemas.anomaly import AnomalyRequest
from app.services.anomaly_service import AnomalyService
from app.services.ingestion_service import IngestionService
from tests.helpers import CATEGORICAL_ONLY_CSV, anomaly_csv


def _dataset(db, content: str, name: str = "numbers.csv"):
    dataset, _, _ = IngestionService(db, settings).upload(name, content.encode())
    return dataset


def test_detects_extreme_observations(db):
    dataset = _dataset(db, anomaly_csv(60))
    service = AnomalyService(db, settings)
    result = service.detect(dataset, AnomalyRequest(contamination=0.05, n_estimators=100))

    assert result["total_records"] == 62
    assert result["records_analyzed"] == 62
    assert result["anomalies_detected"] >= 1
    assert result["anomaly_percentage"] == pytest.approx(
        result["anomalies_detected"] / 62 * 100, abs=0.01
    )
    assert result["features"] == ["value", "quantity"]
    values = [anomaly["values"]["value"] for anomaly in result["anomalies"]]
    assert any(value >= 900 for value in values)
    assert "statistical outliers" in result["disclaimer"]
    assert result["id"] is not None


def test_results_are_persisted_and_retrievable(db):
    dataset = _dataset(db, anomaly_csv(40))
    service = AnomalyService(db, settings)
    created = service.detect(dataset, AnomalyRequest(contamination=0.1))

    latest = service.latest(dataset)
    assert latest["id"] == created["id"]
    assert latest["anomalies_detected"] == created["anomalies_detected"]

    specific = service.get(dataset, created["id"])
    assert specific["anomalies_detected"] == created["anomalies_detected"]

    history = service.history(dataset)
    assert len(history) == 1
    assert history[0]["features"] == ["value", "quantity"]


def test_reproducible_with_fixed_seed(db):
    dataset = _dataset(db, anomaly_csv(60))
    service = AnomalyService(db, settings)
    first = service.detect(dataset, AnomalyRequest(random_state=7, contamination=0.05))
    second = service.detect(dataset, AnomalyRequest(random_state=7, contamination=0.05))
    assert [item["row_number"] for item in first["anomalies"]] == [
        item["row_number"] for item in second["anomalies"]
    ]
    assert [item["anomaly_score"] for item in first["anomalies"]] == [
        item["anomaly_score"] for item in second["anomalies"]
    ]


def test_different_seed_changes_model_output_for_large_data(db):
    dataset = _dataset(db, anomaly_csv(60))
    service = AnomalyService(db, settings)
    service.detect(dataset, AnomalyRequest(random_state=1))
    service.detect(dataset, AnomalyRequest(random_state=2))
    assert len(service.history(dataset)) == 2


def test_insufficient_numeric_columns(db):
    dataset = _dataset(db, CATEGORICAL_ONLY_CSV)
    with pytest.raises(ValidationAppError, match="numeric column"):
        AnomalyService(db, settings).detect(dataset, AnomalyRequest())


def test_constant_numeric_column_is_not_usable(db):
    dataset = _dataset(db, "value,label\n5,a\n5,b\n5,c\n5,d\n5,e\n5,f\n")
    with pytest.raises(ValidationAppError, match="variation"):
        AnomalyService(db, settings).detect(dataset, AnomalyRequest())


def test_too_few_rows(db):
    dataset = _dataset(db, "value,quantity\n1,2\n2,3\n3,4\n")
    with pytest.raises(ValidationAppError, match="At least"):
        AnomalyService(db, settings).detect(dataset, AnomalyRequest())


def test_unknown_feature_rejected(db):
    dataset = _dataset(db, anomaly_csv(20))
    with pytest.raises(ValidationAppError, match="Unknown feature"):
        AnomalyService(db, settings).detect(dataset, AnomalyRequest(features=["does_not_exist"]))


def test_non_numeric_feature_rejected(db):
    dataset = _dataset(db, anomaly_csv(20))
    with pytest.raises(ValidationAppError, match="numeric"):
        AnomalyService(db, settings).detect(dataset, AnomalyRequest(features=["label"]))


def test_missing_values_are_imputed_and_partial_rows_kept(db):
    content = "value,quantity,label\n10,1,a\n,2,b\n30,3,c\n40,,d\n,,\n60,6,f\n70,7,g\n"
    dataset = _dataset(db, content)
    result = AnomalyService(db, settings).detect(dataset, AnomalyRequest(contamination=0.1))
    assert result["total_records"] == 7
    # The row with both features missing is excluded from training.
    assert result["records_excluded"] == 1
    assert result["records_analyzed"] == 6
