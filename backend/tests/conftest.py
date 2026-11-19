"""Pytest fixtures configured before importing the application.

A temporary SQLite database and storage directory keep tests hermetic and
independent from any local PostgreSQL instance or paid LLM provider.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="insightflow-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEMP_ROOT / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_TEMP_ROOT / "storage")
os.environ["MAX_UPLOAD_SIZE_MB"] = "2"
os.environ["MAX_DATASET_ROWS"] = "10000"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = "https://llm.invalid/v1"
os.environ["LLM_MODEL"] = "test-model"

import app.models  # noqa: F401,E402  (register models)
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_database() -> Generator[None, None, None]:
    """Recreate the schema and storage contents for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    for directory in (settings.uploads_path, settings.processed_path):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    settings.max_upload_size_mb = 2
    yield


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def uploaded(client: TestClient) -> dict:
    from tests.helpers import SAMPLE_CSV, upload

    return upload(client, SAMPLE_CSV)
