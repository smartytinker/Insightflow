"""Centralized logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.config import Settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging(settings: Settings) -> None:
    """Configure root logging once, avoiding duplicate handlers.

    Log messages never include dataframe contents; callers should log only
    metadata such as dataset IDs, row counts and operation names.
    """
    root = logging.getLogger()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)

    # Quiet noisy third-party loggers while keeping warnings visible.
    for name in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    """Return a logger adapter that prefixes structured context."""
    logger = logging.getLogger(name)
    if not context:
        return logging.LoggerAdapter(logger, {})
    return logging.LoggerAdapter(logger, context)
