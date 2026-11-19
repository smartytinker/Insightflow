"""Chat orchestration tests: grounding, persistence and provider fallback."""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.core.exceptions import LLMUnavailableError, NotFoundError
from app.services.chat_service import ChatService
from app.services.ingestion_service import IngestionService
from tests.helpers import SAMPLE_CSV


class FakeLLM:
    def __init__(self, response: str = "This suggests Electronics is the key driver.") -> None:
        self.response = response
        self.calls: list[dict] = []

    def interpret(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FailingLLM:
    def interpret(self, **kwargs):
        raise LLMUnavailableError("The AI provider timed out.")


def _dataset(db):
    dataset, _, _ = IngestionService(db, settings).upload("sales.csv", SAMPLE_CSV.encode())
    return dataset


def test_llm_narrative_is_added_after_deterministic_answer(db):
    dataset = _dataset(db)
    fake = FakeLLM()
    service = ChatService(db, settings, llm=fake)
    result = service.ask(dataset, "Which category has the highest revenue?")

    assert result["mode"] == "llm+calculations"
    assert "AI interpretation:" in result["answer"]
    assert fake.response in result["answer"]
    assert "1,060.5" in result["answer"]
    assert result["calculated_facts"]
    call = fake.calls[0]
    assert call["question"] == "Which category has the highest revenue?"
    assert call["calculated_facts"]
    # Context contains summaries, not raw records.
    serialized = str(call["dataset_context"])
    assert "TXN-" not in serialized
    assert "CUST-" not in serialized
    assert call["dataset_context"]["dataset"]["rows"] == 11


def test_provider_failure_falls_back_to_calculations(db):
    dataset = _dataset(db)
    service = ChatService(db, settings, llm=FailingLLM())
    result = service.ask(dataset, "What is the average revenue?")

    assert result["mode"] == "calculations_only"
    assert result["note"]
    assert "timed out" in result["note"]
    assert "148.6" in result["answer"]  # deterministic mean
    assert result["llm_error"]


def test_conversation_history_continuity(db):
    dataset = _dataset(db)
    service = ChatService(db, settings, llm=FakeLLM())
    first = service.ask(dataset, "What is the average revenue?")
    second = service.ask(dataset, "How many rows are there?", session_id=first["session_id"])
    assert first["session_id"] == second["session_id"]

    history = service.history(dataset, session_id=first["session_id"])
    assert len(history["messages"]) == 4
    assert history["messages"][0].role == "user"
    assert history["messages"][-1].role == "assistant"


def test_session_scoped_to_dataset(db):
    dataset = _dataset(db)
    other, _, _ = IngestionService(db, settings).upload("other.csv", b"value\n1\n2\n3\n")
    service = ChatService(db, settings, llm=FakeLLM())
    result = service.ask(dataset, "How many rows are there?")
    with pytest.raises(NotFoundError):
        service.ask(other, "How many rows?", session_id=result["session_id"])


def test_empty_question_rejected(db):
    from app.core.exceptions import ValidationAppError

    dataset = _dataset(db)
    with pytest.raises(ValidationAppError):
        ChatService(db, settings, llm=FakeLLM()).ask(dataset, "   ")
