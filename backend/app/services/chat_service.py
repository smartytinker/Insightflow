"""AI assistant orchestration: deterministic facts plus grounded LLM narrative."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import LLMNotConfiguredError, LLMUnavailableError, ValidationAppError
from app.models.dataset import Dataset
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.chat_repository import ChatRepository
from app.services.analytics_service import AnalyticsService
from app.services.llm_service import LLMService
from app.services.question_engine import QuestionEngine
from app.utils.data_validation import load_dataframe
from app.utils.serialization import json_safe

logger = logging.getLogger(__name__)


class ChatService:
    """Answers dataset questions with calculated facts and optional AI narrative."""

    def __init__(self, db: Session, settings: Settings, llm: LLMService | None = None) -> None:
        self.db = db
        self.settings = settings
        self.repo = ChatRepository(db)
        self.analysis_repo = AnalysisRepository(db)
        self.analytics = AnalyticsService(db, settings)
        self.llm = llm or LLMService(settings)

    def ask(
        self,
        dataset: Dataset,
        question: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Answer a question, persist the conversation and return the response."""
        question = question.strip()
        if not question:
            raise ValidationAppError("The question must not be empty.")

        df = load_dataframe(dataset.active_path, self.settings)
        profile = self._safe_profile(dataset)
        session = self.repo.get_or_create_session(dataset.id, session_id)
        history = self.repo.history(session.id)
        if not history:
            session.title = question[:120]

        self.repo.add_message(session, "user", question)
        engine = QuestionEngine(df, profile)
        result = engine.answer(question)
        latest_anomaly = self.analysis_repo.latest_anomaly(dataset.id)
        if latest_anomaly is not None and result.question_type == "outlier_scan":
            result.fact(
                "Latest Isolation Forest run",
                f"{latest_anomaly.anomalies_detected:,} anomalies in "
                f"{latest_anomaly.total_records:,} records "
                f"({latest_anomaly.anomaly_percentage:.2f}%)",
                "stored anomaly results",
            )
            result.answer += (
                f" A stored Isolation Forest run analyzed "
                f"{latest_anomaly.total_records:,} records and flagged "
                f"{latest_anomaly.anomalies_detected:,} multivariate anomalies "
                f"({latest_anomaly.anomaly_percentage:.2f}%). These are statistical "
                "outliers, not confirmed errors or fraud."
            )

        dataset_context = self._dataset_context(dataset, df, profile)
        history_payload = [
            {"role": message.role, "content": message.content} for message in history
        ]

        mode = "calculations_only"
        llm_error: str | None = None
        note: str | None = None
        answer = result.answer
        try:
            llm_text = self.llm.interpret(
                question=question,
                dataset_context=dataset_context,
                calculated_facts=result.facts,
                history=history_payload,
                table=result.table,
            )
            mode = "llm+calculations"
            answer = f"{result.answer}\n\n**AI interpretation:** {llm_text}"
        except LLMNotConfiguredError:
            llm_error = "LLM provider is not configured."
            note = (
                "AI interpretation is unavailable because no LLM provider is configured. "
                "The answer above was calculated directly from your dataset."
            )
        except LLMUnavailableError as exc:
            llm_error = exc.message
            note = f"{exc.message} The answer above was calculated directly from your dataset."
        except Exception:  # pragma: no cover - defensive boundary for external service
            logger.exception("Unexpected LLM failure for dataset %s", dataset.id)
            llm_error = "Unexpected AI provider failure."
            note = (
                "AI interpretation is temporarily unavailable. "
                "The answer above was calculated directly from your dataset."
            )

        metadata = {
            "question_type": result.question_type,
            "mode": mode,
            "facts": result.facts,
            "table": result.table[:10],
            "columns_used": result.columns_used,
            "llm_error": llm_error,
            "note": note,
            "calculated_at": datetime.now(UTC).isoformat(),
        }
        assistant_message = self.repo.add_message(session, "assistant", answer, metadata)
        try:
            self.db.commit()
            self.db.refresh(assistant_message)
        except Exception:
            self.db.rollback()
            raise

        return {
            "session_id": session.id,
            "message_id": assistant_message.id,
            "answer": answer,
            "mode": mode,
            "calculated_facts": result.facts,
            "question_type": result.question_type,
            "llm_error": llm_error,
            "note": note,
            "created_at": assistant_message.created_at,
        }

    def history(
        self, dataset: Dataset, session_id: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Return persisted conversation history for a dataset."""
        session = (
            self.repo.get_session(dataset.id, session_id)
            if session_id
            else self.repo.latest_session(dataset.id)
        )
        if session is None:
            return {"dataset_id": dataset.id, "session_id": None, "messages": []}
        return {
            "dataset_id": dataset.id,
            "session_id": session.id,
            "messages": self.repo.history(session.id, limit=limit),
        }

    def list_sessions(self, dataset: Dataset) -> list[dict[str, Any]]:
        return [
            {
                "id": session.id,
                "dataset_id": session.dataset_id,
                "title": session.title,
                "message_count": message_count,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
            for session, message_count in self.repo.list_sessions(dataset.id)
        ]

    def start_session(self, dataset: Dataset, title: str | None = None) -> dict[str, Any]:
        """Create a new empty conversation and persist it."""
        session = self.repo.create_session(dataset.id, title or "New conversation")
        try:
            self.db.commit()
            self.db.refresh(session)
        except Exception:
            self.db.rollback()
            raise
        return {
            "id": session.id,
            "dataset_id": session.dataset_id,
            "title": session.title,
            "message_count": 0,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    # ----------------------------------------------------------------- context

    def _safe_profile(self, dataset: Dataset) -> dict[str, Any] | None:
        try:
            return self.analytics.profile(dataset, use_cache=True)
        except ValidationAppError:
            return None

    def _dataset_context(
        self, dataset: Dataset, df: Any, profile: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build a compact, non-sensitive statistical context for the LLM."""
        columns = [
            {
                "name": str(column),
                "dtype": str(df[column].dtype),
                "missing_percentage": round(float(df[column].isna().mean() * 100), 2),
                "unique_count": int(df[column].nunique(dropna=True)),
            }
            for column in list(df.columns)[:40]
        ]
        context: dict[str, Any] = {
            "dataset": {
                "rows": int(df.shape[0]),
                "columns": int(df.shape[1]),
                "is_cleaned": dataset.is_cleaned,
            },
            "columns": columns,
            "data_quality_issues": (profile or {}).get("quality_issues", [])[:5],
            "profile_summary": (profile or {}).get("summary"),
            "top_correlations": (profile or {}).get("top_correlations", [])[:3],
            "numeric_highlights": [
                {
                    "name": item["name"],
                    "mean": item.get("mean"),
                    "median": item.get("median"),
                    "min": item.get("minimum"),
                    "max": item.get("maximum"),
                }
                for item in (profile or {}).get("numeric_columns", [])[:6]
            ],
            "top_categories": [
                {"name": item["name"], "top_values": item.get("top_values", [])[:3]}
                for item in (profile or {}).get("categorical_columns", [])[:4]
            ],
        }
        time_series = (profile or {}).get("time_series")
        if time_series:
            context["time_series"] = {
                "date_column": time_series["date_column"],
                "metric_column": time_series["metric_column"],
                "granularity": time_series["granularity"],
                "point_count": len(time_series["points"]),
            }
        latest = self.analysis_repo.latest_anomaly(dataset.id)
        if latest is not None:
            context["latest_anomaly_run"] = {
                "total_records": latest.total_records,
                "anomalies_detected": latest.anomalies_detected,
                "anomaly_percentage": latest.anomaly_percentage,
                "features": latest.features,
                "created_at": json_safe(latest.created_at),
            }
        return context
