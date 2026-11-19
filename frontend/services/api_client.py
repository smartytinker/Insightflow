"""Typed HTTP client for the InsightFlow REST API.

The Streamlit frontend talks to the backend exclusively through this module;
it never imports backend models or services.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


class ApiError(Exception):
    """A user-presentable API failure with a stable error code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "api_error",
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


class InsightFlowClient:
    """Thin wrapper around the InsightFlow API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 180.0,
        public_base_url: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://localhost:8000")).rstrip("/")
        # Browser-facing URL for direct download links (may differ inside Docker).
        self.public_base_url = (
            public_base_url or os.getenv("PUBLIC_API_BASE_URL") or self.base_url
        ).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------- transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                files=files,
                data=data,
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise ApiError(
                "The request timed out. The dataset may be large; please try again.",
                code="timeout",
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ApiError(
                f"Cannot reach the InsightFlow API. Is the backend running at {self.base_url}?",
                code="connection_error",
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ApiError(
                f"The request failed: {type(exc).__name__}", code="request_error"
            ) from exc

        if response.status_code >= 400:
            message = f"Request failed with HTTP {response.status_code}."
            code = "http_error"
            details: dict[str, Any] = {}
            try:
                payload = response.json()
                error = payload.get("error", {})
                message = error.get("message") or message
                code = error.get("code") or code
                details = error.get("details") or {}
            except ValueError:
                pass
            raise ApiError(message, code=code, status_code=response.status_code, details=details)

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                "The API returned an invalid response.", code="invalid_response"
            ) from exc

    def _download(self, path: str) -> tuple[bytes, str]:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise ApiError("The download could not be completed.", code="download_error") from exc
        if response.status_code >= 400:
            raise ApiError(
                f"Download failed with HTTP {response.status_code}.", code="download_error"
            )
        disposition = response.headers.get("content-disposition", "")
        filename = "insightflow_export.csv"
        if "filename=" in disposition:
            filename = disposition.split("filename=")[-1].strip().strip('"')
        return response.content, filename

    # --------------------------------------------------------------- helpers

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=10)

    def overview(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/overview")

    def list_datasets(self, limit: int = 200) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/datasets", params={"limit": limit, "offset": 0})
        return payload["items"]

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}")

    def upload_dataset(self, filename: str, content: bytes) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/datasets/upload",
            files={"file": (filename, content, "text/csv")},
        )

    def delete_dataset(self, dataset_id: str) -> None:
        self._request("DELETE", f"/api/v1/datasets/{dataset_id}")

    def preview(self, dataset_id: str, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/preview",
            params={"limit": limit, "offset": offset},
        )

    def clean(self, dataset_id: str, configuration: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/datasets/{dataset_id}/clean", json=configuration)

    def cleaning_history(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/cleaning-history")

    def profile(self, dataset_id: str, refresh: bool = False) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/profile",
            params={"refresh": str(refresh).lower()},
        )

    def statistics(self, dataset_id: str, refresh: bool = False) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/statistics",
            params={"refresh": str(refresh).lower()},
        )

    def run_anomalies(self, dataset_id: str, configuration: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/datasets/{dataset_id}/anomalies", json=configuration)

    def latest_anomalies(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/anomalies")

    def anomaly_history(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/anomalies/history")

    def chat(self, dataset_id: str, question: str, session_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if session_id:
            payload["session_id"] = session_id
        return self._request("POST", f"/api/v1/datasets/{dataset_id}/chat", json=payload)

    def chat_history(self, dataset_id: str, session_id: str | None = None) -> dict[str, Any]:
        params = {"session_id": session_id} if session_id else None
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/chat/history", params=params)

    def chat_sessions(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/chat/sessions")

    def start_chat_session(self, dataset_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/datasets/{dataset_id}/chat/sessions")

    def report(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/report")

    def download_dataset_csv(self, dataset_id: str) -> tuple[bytes, str]:
        return self._download(f"/api/v1/datasets/{dataset_id}/report/dataset.csv")

    def download_anomalies_csv(self, dataset_id: str) -> tuple[bytes, str]:
        return self._download(f"/api/v1/datasets/{dataset_id}/report/anomalies.csv")

    def download_quality_csv(self, dataset_id: str) -> tuple[bytes, str]:
        return self._download(f"/api/v1/datasets/{dataset_id}/report/quality.csv")

    def load_sample(self, name: str) -> bytes:
        """Read a bundled sample file (frontend-local convenience)."""
        path = Path(__file__).resolve().parents[2] / "sample_data" / name
        return path.read_bytes()
