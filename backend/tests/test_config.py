"""Configuration tests for path anchoring and SQLite setup."""

from __future__ import annotations

from pathlib import Path

from app.core.config import REPO_ROOT, Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_relative_sqlite_path_resolves_against_repo_root():
    settings = _settings(database_url="sqlite:///storage/custom.db")
    expected = (REPO_ROOT / "storage" / "custom.db").resolve()
    assert settings.database_url.startswith("sqlite:////")
    assert str(expected) in settings.database_url


def test_relative_sqlite_path_works_from_backend_directory():
    settings = _settings(database_url="sqlite:///storage/insightflow.db")
    assert str((REPO_ROOT / "storage" / "insightflow.db").resolve()) in settings.database_url


def test_absolute_sqlite_path_is_preserved():
    absolute = Path("/tmp/insightflow-absolute.db")
    original = f"sqlite:///{absolute}"
    assert _settings(database_url=original).database_url == original


def test_sqlite_query_parameters_are_preserved():
    normalized = _settings(
        database_url="sqlite:///storage/custom.db?check_same_thread=false"
    ).database_url
    assert normalized.endswith("?check_same_thread=false")
    assert str((REPO_ROOT / "storage" / "custom.db").resolve()) in normalized


def test_memory_sqlite_is_unchanged():
    assert _settings(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"


def test_postgres_url_is_unchanged():
    url = "postgresql+psycopg://user:pass@localhost:5432/insightflow"
    assert _settings(database_url=url).database_url == url


def test_ensure_directories_creates_sqlite_parent(tmp_path):
    database = tmp_path / "nested" / "data" / "insightflow.db"
    settings = _settings(
        database_url=f"sqlite:///{database}",
        storage_dir=tmp_path / "storage",
    )
    settings.ensure_directories()
    assert database.parent.is_dir()
    assert settings.uploads_path.is_dir()
    assert settings.processed_path.is_dir()
