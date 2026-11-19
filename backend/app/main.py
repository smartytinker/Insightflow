"""InsightFlow FastAPI application factory.

Routes stay thin; business logic lives in service classes. The app exposes
OpenAPI documentation at /docs and consistent error envelopes.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import analytics, anomalies, chat, cleaning, datasets, overview, reports
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import engine

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
InsightFlow is a data intelligence API for CSV analytics.

**Capabilities**
- Upload and validate CSV datasets with safe storage
- Profile data, compute statistics and chart-ready aggregates
- Clean datasets without modifying the original upload
- Detect statistical anomalies with Isolation Forest
- Ask grounded natural-language questions with deterministic calculations
- Export JSON reports and CSV downloads

All errors use a consistent envelope with a request identifier.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Service and database health"},
    {"name": "overview", "description": "Dashboard metrics and recent activity"},
    {"name": "datasets", "description": "Upload, list, inspect and delete datasets"},
    {"name": "cleaning", "description": "Configurable cleaning with recorded history"},
    {"name": "analytics", "description": "Profiling, statistics and chart data"},
    {"name": "anomalies", "description": "Isolation Forest anomaly detection"},
    {"name": "assistant", "description": "Natural-language dataset questions"},
    {"name": "reports", "description": "JSON reports and CSV exports"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare storage and, for local SQLite, create the schema automatically."""
    configure_logging(settings)
    settings.ensure_directories()
    if settings.database_url.startswith("sqlite"):
        # Postgres deployments use Alembic migrations (see docker entrypoint).
        import app.models  # noqa: F401  (register models)
        from app.db.base import Base

        Base.metadata.create_all(bind=engine)
        logger.info("SQLite schema ensured at %s", settings.database_url)
    logger.info("InsightFlow %s starting (env=%s)", settings.app_version, settings.environment)
    yield
    logger.info("InsightFlow shutting down")


def create_app() -> FastAPI:
    configure_logging(settings)
    app = FastAPI(
        title=settings.app_name,
        description=API_DESCRIPTION,
        version=settings.app_version,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The centralized handler builds the response; this log preserves timing.
            logger.exception(
                "Request failed: %s %s (request_id=%s)",
                request.method,
                request.url.path,
                request_id,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %s (%.1f ms, request_id=%s)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    register_exception_handlers(app)

    prefix = settings.api_v1_prefix
    app.include_router(overview.router, prefix=prefix)
    app.include_router(datasets.router, prefix=prefix)
    app.include_router(cleaning.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(anomalies.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)

    @app.get("/", tags=["health"], summary="Service information")
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
            "api": prefix,
        }

    @app.get("/health", tags=["health"], summary="Health check")
    @app.get(
        f"{prefix}/health", tags=["health"], summary="API health check", include_in_schema=False
    )
    def health() -> JSONResponse:
        database_status = "ok"
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Database health check failed")
            database_status = "unavailable"
        status_code = 200 if database_status == "ok" else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if status_code == 200 else "degraded",
                "database": database_status,
                "version": settings.app_version,
                "llm_configured": settings.llm_configured,
            },
        )

    return app


app = create_app()
