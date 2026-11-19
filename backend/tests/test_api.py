"""End-to-end API tests covering the required endpoints and error contracts."""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from tests.helpers import ANALYTICS_CSV, SAMPLE_CSV, upload


def test_health_and_root(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert health.headers["X-Request-ID"]

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"


def test_upload_list_detail_preview_and_delete(client, db):
    payload = upload(client, SAMPLE_CSV)
    dataset_id = payload["dataset"]["id"]

    listing = client.get("/api/v1/datasets?limit=10&offset=0")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    detail = client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert detail.json()["columns"][0]["name"] == "transaction_date"
    assert detail.json()["quality"] is None

    preview = client.get(f"/api/v1/datasets/{dataset_id}/preview?limit=3&offset=1")
    assert preview.status_code == 200
    assert len(preview.json()["rows"]) == 3
    assert preview.json()["source"] == "original"

    from app.models.dataset import Dataset

    dataset = db.get(Dataset, dataset_id)
    stored = Path(dataset.storage_path)

    deleted = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    db.expire_all()
    assert not stored.exists()


def test_unknown_dataset_error_envelope(client):
    response = client.get("/api/v1/datasets/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]
    assert "Traceback" not in response.text


def test_unsupported_file_type(client):
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("data.txt", b"a,b\n1,2\n", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_empty_upload_and_duplicate_columns(client):
    empty = client.post("/api/v1/datasets/upload", files={"file": ("empty.csv", b"", "text/csv")})
    assert empty.status_code == 400

    duplicate = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("dup.csv", b"a,a\n1,2\n", "text/csv")},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["details"]["duplicate_columns"] == ["a"]


def test_oversized_upload_returns_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    content = b"a,b\n" + b"1,2\n" * 300_000
    response = client.post(
        "/api/v1/datasets/upload", files={"file": ("big.csv", content, "text/csv")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_cleaning_endpoint_and_history(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/clean",
        json={
            "drop_duplicates": True,
            "missing_strategy": "fill_median",
            "normalize_columns": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["duplicates_removed"] == 1
    assert body["final_row_count"] == 10
    assert body["cleaned_file_available"] is True
    assert body["after_preview"]

    history = client.get(f"/api/v1/datasets/{dataset_id}/cleaning-history")
    assert history.status_code == 200
    assert len(history.json()["operations"]) >= 2

    preview = client.get(f"/api/v1/datasets/{dataset_id}/preview")
    assert preview.json()["source"] == "cleaned"


def test_cleaning_invalid_column_returns_400(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/clean",
        json={"drop_duplicates": False, "drop_columns": ["nope"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_profile_and_statistics_endpoints(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    profile = client.get(f"/api/v1/datasets/{dataset_id}/profile")
    assert profile.status_code == 200
    body = profile.json()
    assert body["overview"]["row_count"] == 11
    assert body["numeric_columns"]
    assert body["summary"]

    stats = client.get(f"/api/v1/datasets/{dataset_id}/statistics")
    assert stats.status_code == 200
    assert stats.json()["overview"]["row_count"] == 11
    assert "revenue" in stats.json()["missing_values"]

    refreshed = client.get(f"/api/v1/datasets/{dataset_id}/profile?refresh=true")
    assert refreshed.status_code == 200


def test_anomaly_endpoints(client):
    upload(client, ANALYTICS_CSV, "analytics.csv")
    dataset_id = client.get("/api/v1/datasets").json()["items"][0]["id"]

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/anomalies",
        json={"contamination": 0.1, "n_estimators": 50, "random_state": 42},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["anomalies_detected"] >= 1
    assert body["features"]
    assert body["disclaimer"]

    latest = client.get(f"/api/v1/datasets/{dataset_id}/anomalies")
    assert latest.status_code == 200
    assert latest.json()["id"] == body["id"]

    specific = client.get(f"/api/v1/datasets/{dataset_id}/anomalies/{body['id']}")
    assert specific.status_code == 200

    history = client.get(f"/api/v1/datasets/{dataset_id}/anomalies/history")
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1


def test_anomalies_unavailable_before_run(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.get(f"/api/v1/datasets/{dataset_id}/anomalies")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_chat_fallback_is_grounded_and_persisted(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/chat",
        json={"question": "Which category has the highest revenue?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "calculations_only"
    assert body["question_type"] == "group_aggregate"
    assert body["note"]
    fact_labels = {fact["label"] for fact in body["calculated_facts"]}
    assert "Grouped by" in fact_labels
    # Deterministic result: Electronics revenue = 100 + 250.5 + 310 + 200 + 200 = 1060.5
    assert "1,060.5" in body["answer"]
    assert body["session_id"]

    history = client.get(f"/api/v1/datasets/{dataset_id}/chat/history")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["message_metadata"]["facts"]

    sessions = client.get(f"/api/v1/datasets/{dataset_id}/chat/sessions")
    assert sessions.status_code == 200
    assert sessions.json()["items"][0]["message_count"] == 2


def test_chat_validation_error(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(f"/api/v1/datasets/{dataset_id}/chat", json={"question": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_chat_session_creation(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(f"/api/v1/datasets/{dataset_id}/chat/sessions")
    assert response.status_code == 201
    session = response.json()
    assert session["message_count"] == 0
    assert session["id"]

    listing = client.get(f"/api/v1/datasets/{dataset_id}/chat/sessions")
    assert any(item["id"] == session["id"] for item in listing.json()["items"])

    history = client.get(
        f"/api/v1/datasets/{dataset_id}/chat/history",
        params={"session_id": session["id"]},
    )
    assert history.status_code == 200
    assert history.json()["messages"] == []


def test_reports_and_csv_downloads(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    report = client.get(f"/api/v1/datasets/{dataset_id}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["dataset"]["id"] == dataset_id
    assert body["profile"]["overview"]["row_count"] == 11

    csv_response = client.get(f"/api/v1/datasets/{dataset_id}/report/dataset.csv")
    assert csv_response.status_code == 200
    assert "attachment" in csv_response.headers["content-disposition"]
    assert csv_response.text.startswith("transaction_date")

    quality = client.get(f"/api/v1/datasets/{dataset_id}/report/quality.csv")
    assert quality.status_code == 200
    assert "missing_percentage" in quality.text

    no_anomalies = client.get(f"/api/v1/datasets/{dataset_id}/report/anomalies.csv")
    assert no_anomalies.status_code == 400


def test_anomaly_csv_download(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    client.post(f"/api/v1/datasets/{dataset_id}/anomalies", json={"contamination": 0.1})
    response = client.get(f"/api/v1/datasets/{dataset_id}/report/anomalies.csv")
    assert response.status_code == 200
    assert response.text.splitlines()[0].startswith("row_number,anomaly_score,rank")


def test_overview_metrics(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    client.get(f"/api/v1/datasets/{dataset_id}/profile")
    client.post(f"/api/v1/datasets/{dataset_id}/anomalies", json={"contamination": 0.1})
    client.post(
        f"/api/v1/datasets/{dataset_id}/chat",
        json={"question": "What is the average revenue?"},
    )

    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    stats = overview.json()["stats"]
    assert stats["total_datasets"] == 1
    assert stats["total_records"] == 11
    assert stats["total_analyses"] >= 1
    assert stats["total_chat_messages"] == 2
    assert overview.json()["recent_datasets"][0]["id"] == dataset_id
    assert overview.json()["recent_activity"]


def test_delete_cascades_related_records(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    client.post(f"/api/v1/datasets/{dataset_id}/anomalies", json={"contamination": 0.1})
    assert client.delete(f"/api/v1/datasets/{dataset_id}").status_code == 204
    assert client.get(f"/api/v1/datasets/{dataset_id}/anomalies").status_code == 404
    assert client.get("/api/v1/overview").json()["stats"]["total_anomalies"] == 0


def test_cleaning_without_changes_still_creates_a_copy(client, uploaded):
    dataset_id = uploaded["dataset"]["id"]
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/clean",
        json={"drop_duplicates": False, "normalize_columns": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["final_row_count"] == body["original_row_count"]
    assert body["cleaned_file_available"]
