"""Tests for CSV ingestion, validation and safe storage."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.exceptions import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    ValidationAppError,
)
from app.services.ingestion_service import IngestionService
from tests.helpers import SAMPLE_CSV, upload


@pytest.fixture()
def service(db):
    from app.core.config import settings

    return IngestionService(db, settings)


def test_valid_upload(service):
    dataset, quality, columns = service.upload("sales.csv", SAMPLE_CSV.encode(), "text/csv")

    assert dataset.id
    assert dataset.row_count == 11
    assert dataset.column_count == 6
    assert dataset.processing_status == "ready"
    assert dataset.original_filename == "sales.csv"
    assert len(dataset.checksum or "") == 64
    assert quality["duplicate_rows"] == 1
    assert quality["missing_cells"] == 2
    stored = Path(dataset.storage_path)
    assert stored.exists()
    assert stored.read_bytes() == SAMPLE_CSV.encode()
    assert stored.resolve().is_relative_to(service.settings.storage_dir.resolve())
    kinds = {column["name"]: column["kind"] for column in columns}
    assert kinds["revenue"] == "numeric"
    assert kinds["transaction_date"] == "datetime"
    assert kinds["category"] == "categorical"


def test_preview_pagination(service):
    dataset, _, _ = service.upload("sales.csv", SAMPLE_CSV.encode())
    page = service.preview(dataset, limit=2, offset=2)
    assert len(page["rows"]) == 2
    assert page["total_rows"] == 11
    assert page["offset"] == 2
    assert page["source"] == "original"
    # Offset rows should be the third and fourth records.
    assert page["rows"][0]["category"] == "Home"


def test_unsupported_extension(service):
    with pytest.raises(UnsupportedFileTypeError):
        service.upload("data.xlsx", b"whatever", "application/vnd.ms-excel")


def test_empty_file(service):
    with pytest.raises(ValidationAppError):
        service.upload("empty.csv", b"", "text/csv")


def test_header_only(service):
    with pytest.raises(ValidationAppError, match="no data rows"):
        service.upload("header.csv", b"a,b,c\n", "text/csv")


def test_missing_header(service):
    with pytest.raises(ValidationAppError, match="empty column names"):
        service.upload("bad.csv", b"a,,c\n1,2,3\n", "text/csv")


def test_duplicate_columns(service):
    with pytest.raises(ValidationAppError, match="duplicate column") as error:
        service.upload("dup.csv", b"a,b,a\n1,2,3\n", "text/csv")
    assert error.value.details["duplicate_columns"] == ["a"]


def test_oversized_upload(service, monkeypatch):
    monkeypatch.setattr(service.settings, "max_upload_size_mb", 1)
    content = b"a,b\n" + b"1,2\n" * 300_000
    with pytest.raises(FileTooLargeError) as error:
        service.upload("big.csv", content, "text/csv")
    assert error.value.status_code == 413


def test_path_traversal_is_sanitized(service):
    dataset, _, _ = service.upload("../../etc/passwd.csv", SAMPLE_CSV.encode())
    assert "/" not in dataset.original_filename
    assert ".." not in dataset.original_filename
    stored = Path(dataset.storage_path).resolve()
    assert stored.is_relative_to(service.settings.storage_dir.resolve())


def test_binary_content_rejected(service):
    with pytest.raises(ValidationAppError, match="binary"):
        service.upload("binary.csv", b"\x00\x01\x02\x03", "text/csv")


def test_latin1_encoding_supported(service):
    dataset, quality, _ = service.upload(
        "latin.csv", "name,value\nCafé,10\n".encode("latin-1"), "text/csv"
    )
    assert dataset.row_count == 1


def test_original_file_never_modified_by_api_upload(client, uploaded):
    dataset = uploaded["dataset"]
    response = client.get(f"/api/v1/datasets/{dataset['id']}/preview")
    assert response.status_code == 200
    assert response.json()["rows"][0]["category"] == "Electronics"

    listing = client.get("/api/v1/datasets")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["original_filename"] == "test.csv"


def test_preview_rejects_paths_outside_storage(service):
    dataset, _, _ = service.upload("sales.csv", SAMPLE_CSV.encode())
    dataset.storage_path = str(Path("/etc/passwd"))
    service.db.commit()
    with pytest.raises(ValidationAppError, match="outside the storage"):
        service.preview(dataset)


def test_upload_api_returns_quality_and_columns(client):
    payload = upload(client, SAMPLE_CSV)
    assert payload["quality"]["duplicate_rows"] == 1
    assert payload["dataset"]["row_count"] == 11
    assert {column["name"] for column in payload["columns"]} == {
        "transaction_date",
        "category",
        "region",
        "revenue",
        "quantity",
        "customer_id",
    }
