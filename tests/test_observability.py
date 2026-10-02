from __future__ import annotations

import logging
import uuid

import httpx
from fastapi.testclient import TestClient

from app.answering import Answerer
from app.config import Settings
from app.main import create_app


HITS = [
    {
        "document_id": "doc-1",
        "filename": "guide.pdf",
        "page": 1,
        "page_end": None,
        "score": 1.0,
        "content": "Le délai de déclaration est de 15 jours ouvrables.",
    }
]


def _answerer() -> Answerer:
    return Answerer(
        Settings(
            llm_mode="openai_compatible",
            llm_base_url="https://provider.test/v1",
            llm_model="test-model",
            llm_timeout_seconds=2,
        )
    )


def _response(url: str, status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", url),
    )


def test_observability_llm_success(monkeypatch):
    def fake_post(self, url, **kwargs):
        return _response(
            url,
            200,
            {"choices": [{"message": {"content": "Le délai est de 15 jours [1]."}}]},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-success",
    )

    assert result["response_mode"] == "llm"
    assert result["fallback_reason"] is None
    assert result["generation"]["attempted"] is True
    assert result["generation"]["status"] == "success"
    assert result["generation"]["http_status"] == 200
    assert result["generation"]["rejected_answer"] is None


def test_observability_missing_citations_keeps_rejected_answer(monkeypatch, caplog):
    rejected = "Le délai est de 15 jours ouvrables."

    def fake_post(self, url, **kwargs):
        return _response(
            url,
            200,
            {"choices": [{"message": {"content": rejected}}]},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    with caplog.at_level(logging.WARNING, logger="app.answering"):
        result = _answerer().answer(
            "Quel est le délai ?",
            HITS,
            request_id="req-missing-citation",
        )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "missing_citations"
    assert result["generation"]["status"] == "rejected"
    assert result["generation"]["http_status"] == 200
    assert result["generation"]["rejected_answer"] == rejected

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=llm_rejected" in logs
    assert "request_id=req-missing-citation" in logs
    assert "reason=missing_citations" in logs
    assert "answer_preview='Le délai est de 15 jours ouvrables.'" in logs


def test_observability_invalid_citation_reference(monkeypatch):
    rejected = "Le délai est de 15 jours [9]."

    def fake_post(self, url, **kwargs):
        return _response(
            url,
            200,
            {"choices": [{"message": {"content": rejected}}]},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-invalid-ref",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "invalid_citation_reference"
    assert result["generation"]["status"] == "rejected"
    assert result["generation"]["rejected_answer"] == rejected


def test_observability_timeout(monkeypatch):
    def fake_post(self, url, **kwargs):
        raise httpx.ReadTimeout(
            "provider timeout",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-timeout",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "llm_timeout"
    assert result["generation"]["attempted"] is True
    assert result["generation"]["status"] == "unavailable"
    assert result["generation"]["error_type"] == "ReadTimeout"
    assert result["generation"]["rejected_answer"] is None


def test_observability_provider_http_error(monkeypatch):
    def fake_post(self, url, **kwargs):
        return _response(url, 429, {"error": "rate limited"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-provider-error",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "llm_provider_error"
    assert result["generation"]["status"] == "unavailable"
    assert result["generation"]["http_status"] == 429
    assert result["generation"]["error_type"] == "HTTPStatusError"


def test_observability_connection_error(monkeypatch):
    def fake_post(self, url, **kwargs):
        raise httpx.ConnectError(
            "cannot connect",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-connect",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "llm_connection_error"
    assert result["generation"]["status"] == "unavailable"
    assert result["generation"]["error_type"] == "ConnectError"


def test_observability_invalid_provider_payload(monkeypatch):
    def fake_post(self, url, **kwargs):
        return _response(url, 200, {"choices": []})

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-invalid-payload",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "llm_invalid_payload"
    assert result["generation"]["status"] == "error"
    assert result["generation"]["http_status"] == 200
    assert result["generation"]["error_type"] == "IndexError"


def test_observability_empty_llm_answer(monkeypatch):
    def fake_post(self, url, **kwargs):
        return _response(
            url,
            200,
            {"choices": [{"message": {"content": "   "}}]},
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = _answerer().answer(
        "Quel est le délai ?",
        HITS,
        request_id="req-empty",
    )

    assert result["response_mode"] == "extractive"
    assert result["fallback_reason"] == "llm_empty_answer"
    assert result["generation"]["status"] == "rejected"
    assert result["generation"]["http_status"] == 200


def test_api_request_id_is_returned_and_traceable_in_logs(tmp_path, caplog):
    settings = Settings(
        storage_dir=tmp_path / "obs-api",
        retrieval_mode="lexical",
        llm_mode="extractive",
    )

    with caplog.at_level(logging.INFO, logger="app.main"):
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/api/v1/questions",
                json={
                    "question": "Quel est le délai ?",
                    "document_ids": [],
                    "top_k": 4,
                },
            )

    assert response.status_code == 200
    body = response.json()
    request_id = body["request_id"]
    uuid.UUID(request_id)

    assert body["response_mode"] == "no_evidence"
    assert body["fallback_reason"] == "insufficient_evidence"

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert f"request_id={request_id}" in logs
    assert "event=question_started" in logs
    assert "event=retrieval_started" in logs
    assert "event=retrieval_completed" in logs
    assert "event=response_completed" in logs
