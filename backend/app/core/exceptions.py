"""Domain exceptions and FastAPI exception handlers.

Errors are returned with a stable envelope::

    {"error": {"code": "...", "message": "...", "details": {...},
               "request_id": "..."}}

Internal stack traces are logged server-side but never exposed to clients.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected, user-facing application errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "application_error"
    message: str = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ValidationAppError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_error"
    message = "The supplied data is invalid."


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_file_type"
    message = "Only CSV files are supported."


class FileTooLargeError(AppError):
    status_code = 413  # Payload Too Large / Content Too Large
    code = "file_too_large"
    message = "The uploaded file exceeds the configured size limit."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The operation conflicts with the current resource state."


class LLMUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_unavailable"
    message = "The AI assistant is currently unavailable. Deterministic analysis remains available."


class LLMNotConfiguredError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "llm_not_configured"
    message = "No LLM provider is configured. Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL."


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach centralized exception handlers to the application."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.warning("Application error: %s (%s)", exc.message, exc.code)
        return _error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(part) for part in error.get("loc", [])),
                    "message": error.get("msg", "Invalid value"),
                    "type": error.get("type", "value_error"),
                }
            )
        return _error_response(
            request,
            422,  # Unprocessable Content
            "request_validation_error",
            "The request payload or parameters are invalid.",
            {"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        code = "http_error"
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
        elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            code = "method_not_allowed"
        return _error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled error (request_id=%s)", request_id, exc_info=exc)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred. Please try again or check the server logs.",
        )
