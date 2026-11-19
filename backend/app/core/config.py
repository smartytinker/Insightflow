"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: <repo>/backend/app/core/config.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings for the InsightFlow backend.

    All values can be overridden with environment variables or a ``.env`` file.
    Paths are resolved against the repository root so the application behaves
    consistently regardless of the working directory.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "InsightFlow"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Database
    database_url: str = f"sqlite:///{REPO_ROOT / 'storage' / 'insightflow.db'}"

    # Storage
    storage_dir: Path = REPO_ROOT / "storage"
    upload_dir: Path | None = None
    processed_dir: Path | None = None
    max_upload_size_mb: int = Field(default=25, ge=1, le=512)
    max_dataset_rows: int = Field(default=500_000, ge=1)

    # LLM
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    llm_max_tokens: int = Field(default=800, ge=64, le=4096)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)

    # CORS (comma separated origins, "*" allowed for local development)
    cors_origins: str = "*"

    # ML defaults
    anomaly_contamination: float = Field(default=0.05, gt=0, lt=0.5)
    anomaly_random_state: int = 42

    @field_validator("storage_dir", "upload_dir", "processed_dir", mode="before")
    @classmethod
    def _expand_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def uploads_path(self) -> Path:
        """Directory where original uploads are stored."""
        return self.upload_dir or (self.storage_dir / "uploads")

    @property
    def processed_path(self) -> Path:
        """Directory where cleaned datasets are stored."""
        return self.processed_dir or (self.storage_dir / "processed")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    def ensure_directories(self) -> None:
        """Create storage directories if they do not exist."""
        for path in (self.storage_dir, self.uploads_path, self.processed_path):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


settings = get_settings()
