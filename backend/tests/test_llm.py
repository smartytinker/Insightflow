"""Tests for deterministic question answering and LLM grounding boundaries."""

from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest
from app.core.config import Settings
from app.core.exceptions import LLMNotConfiguredError, LLMUnavailableError
from app.services.llm_service import LLMService
from app.services.question_engine import QuestionEngine

FRAME = pd.DataFrame(
    {
        "category": ["A", "A", "B", "B", "C"],
        "revenue": [100.0, 300.0, 50.0, 150.0, 25.0],
        "quantity": [1, 3, 1, 3, 1],
        "customer_id": ["C1", "C2", "C1", "C3", "C2"],
        "order_date": pd.to_datetime(
            ["2024-01-05", "2024-02-05", "2024-03-05", "2024-04-05", "2024-05-05"]
        ),
    }
)


def test_group_highest_and_lowest():
    engine = QuestionEngine(FRAME)
    highest = engine.answer("Which category has the highest revenue?")
    assert highest.question_type == "group_aggregate"
    assert "A" in highest.answer
    assert "400" in highest.answer
    assert highest.table[0]["category"] == "A"
    assert highest.table[0]["total revenue"] == 400.0

    lowest = engine.answer("Which category contributes the least revenue?")
    assert "C" in lowest.answer
    assert lowest.table[0]["category"] == "C"


def test_average_with_alias_uses_actual_column():
    engine = QuestionEngine(FRAME)
    result = engine.answer("What is the average sales value?")
    assert result.question_type == "aggregate"
    assert result.context["metric"] == "revenue"
    assert result.context["value"] == pytest.approx(125.0)
    assert "125" in result.answer
    fact = next(f for f in result.facts if "Mean" in f["label"])
    assert fact["value"] == pytest.approx(125.0)


def test_count_and_unique_count():
    engine = QuestionEngine(FRAME)
    rows = engine.answer("How many rows are in the dataset?")
    assert rows.question_type == "count"
    assert rows.context["count"] == 5

    customers = engine.answer("How many unique customers are there?")
    assert customers.question_type == "count"
    assert customers.context["column"] == "customer_id"
    assert customers.context["count"] == 3


def test_correlation_uses_pandas():
    engine = QuestionEngine(FRAME)
    result = engine.answer("What is the correlation between revenue and quantity?")
    assert result.question_type == "correlation"
    top = result.context["pairs"][0]
    assert {top["column_a"], top["column_b"]} == {"revenue", "quantity"}
    assert 0.8 <= top["correlation"] <= 0.9


def test_trend_uses_dates_and_sums():
    engine = QuestionEngine(FRAME)
    result = engine.answer("What are the revenue trends over time?")
    assert result.question_type == "trend"
    assert result.context["date_column"] == "order_date"
    assert result.context["metric"] == "revenue"
    assert result.context["frequency"] == "month"
    assert result.context["peak_value"] == 300.0


def test_summary_uses_profile_facts():
    profile = {
        "overview": {
            "row_count": 5,
            "column_count": 5,
            "missing_percentage": 0.0,
            "duplicate_rows": 0,
        },
        "quality": {"columns_with_missing_values": []},
        "summary": "The dataset contains 5 rows and 5 columns.",
        "top_correlations": [],
        "numeric_columns": [
            {"name": "revenue", "mean": 125.0, "median": 100.0},
        ],
        "categorical_columns": [],
    }
    result = QuestionEngine(FRAME, profile).answer("Summarize this dataset for management.")
    assert result.question_type == "summary"
    assert "5 rows" in result.answer
    assert any(fact["label"] == "Rows" and fact["value"] == 5 for fact in result.facts)


def test_outlier_scan_does_not_claim_fraud():
    frame = pd.DataFrame({"value": [10, 11, 12, 13, 14, 1000]})
    result = QuestionEngine(frame).answer("Are there unusual patterns?")
    assert result.question_type == "outlier_scan"
    assert "not necessarily" in result.answer.lower()
    assert result.context["findings"][0]["outlier_count"] >= 1


def test_unanswerable_question_is_explicit():
    result = QuestionEngine(FRAME).answer("What is the weather in Paris tomorrow?")
    assert result.question_type == "unanswerable"
    assert "could not match" in result.answer
    assert any("Available numeric columns" in fact["label"] for fact in result.facts)


def _llm_settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_base_url="https://example.test/v1",
        llm_model="test-model",
        llm_timeout_seconds=5,
        _env_file=None,
    )


def test_llm_not_configured():
    service = LLMService(Settings(llm_api_key=None, _env_file=None))
    with pytest.raises(LLMNotConfiguredError):
        service.complete([{"role": "user", "content": "hi"}])


def test_llm_success_and_request_contains_only_facts():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "The total is 400 based on the facts."}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = LLMService(_llm_settings(), client=client)
    text = service.interpret(
        question="Which category has the highest revenue?",
        dataset_context={"dataset": {"rows": 5, "columns": 5}},
        calculated_facts=[{"label": "Top category", "value": "A (400)", "method": "groupby"}],
        history=[],
        table=[{"category": "A", "total revenue": 400.0}],
    )
    assert "400" in text
    assert captured["model"] == "test-model"
    serialized = json.dumps(captured)
    assert "Top category" in serialized
    assert "total revenue" in serialized
    # No raw rows or credentials should be present.
    assert "test-key" not in serialized
    assert "row_number" not in serialized


def test_llm_timeout_is_graceful():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = LLMService(_llm_settings(), client=client)
    with pytest.raises(LLMUnavailableError, match="timed out"):
        service.complete([{"role": "user", "content": "hi"}])


def test_llm_rate_limit_is_graceful():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = LLMService(_llm_settings(), client=client)
    with pytest.raises(LLMUnavailableError, match="rate limit"):
        service.complete([{"role": "user", "content": "hi"}])


def test_llm_auth_failure_does_not_leak_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = LLMService(_llm_settings(), client=client)
    with pytest.raises(LLMUnavailableError) as error:
        service.complete([{"role": "user", "content": "hi"}])
    assert "test-key" not in error.value.message
