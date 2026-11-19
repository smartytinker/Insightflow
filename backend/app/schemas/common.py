"""Shared schema utilities and enums."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Base schema with ORM support and strict extra-field handling."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MessageResponse(BaseModel):
    """Simple acknowledgement payload."""

    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class TimestampedModel(BaseModel):
    created_at: datetime


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class PaginatedResponse(BaseModel):
    total: int
    limit: int
    offset: int
