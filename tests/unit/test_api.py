"""API tests with fake services, including fault injection (brief M4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reglens.agent.guardrails import GuardrailResult
from reglens.agent.state import AgentResult, Status
from reglens.agent.tools import Citation
from reglens.api.main import create_app
from reglens.api.ratelimit import RateLimiter
from reglens.api.services import Services
from reglens.config import Settings
from reglens.llm.budget import DailyBudget
from reglens.llm.client import LLMError
from reglens.retrieval.qdrant import Hit

KEY = {"X-API-Key": "test-key"}


def hit(unit: str) -> Hit:
    return Hit(
        chunk_id=f"{unit}#en",
        unit_id=unit,
        article_id=":".join(unit.split(":")[:3]),
        score=1.0,
        payload={
            "text": "Some legal text.",
            "title": "Article 6",
            "url_eurlex": "https://eur-lex.europa.eu/x#art_6",
        },
    )


def answered(guarded: GuardrailResult) -> AgentResult:
    return AgentResult(
        answer="Annex III systems are high-risk.",
        citations=[Citation(id="AIA:art:6:par:2", quote="Annex III")],
        status=Status.ANSWERED,
        reason=None,
        retrieved_ids=["AIA:art:6:par:2"],
        tool_calls=[],
        steps=1,
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.002,
        latency_ms=5.0,
        route="rag",
    )


def make(tmp_path: Path, **overrides: Any) -> TestClient:
    values: dict[str, Any] = dict(
        retrieve=lambda q: [hit("AIA:art:6:par:2"), hit("AIA:art:6:par:2"), hit("AIA:annex:III")],
        answer=answered,
        store=None,
        budget=DailyBudget(1.0),
        feedback_path=tmp_path / "feedback.jsonl",
        versions={"git_sha": "abc"},
        ready_checks={"qdrant": lambda: True, "llm": lambda: True},
    )
    values.update(overrides)
    settings = Settings(_env_file=None, api_keys="test-key", rate_limit_per_min=60)  # type: ignore[call-arg]
    return TestClient(create_app(Services(**values), settings))


def test_health_version_ready(tmp_path: Path) -> None:
    client = make(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/version").json()["git_sha"] == "abc"
    assert client.get("/ready").status_code == 200
    down = make(tmp_path, ready_checks={"qdrant": lambda: False})
    assert down.get("/ready").status_code == 503


def test_ask_json_with_citations_and_headers(tmp_path: Path) -> None:
    response = make(tmp_path).post(
        "/v1/ask",
        json={"question": "Which AI is high-risk?"},
        headers={**KEY, "X-Request-ID": "req-12345678"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req-12345678"
    assert response.headers["X-Request-ID"] == "req-12345678"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert body["mode"] == "full"
    assert body["citations"][0]["id"] == "AIA:art:6:par:2"
    assert body["citations"][0]["url"].endswith("#art_6")
    assert [s["id"] for s in body["sources"]] == ["AIA:art:6:par:2", "AIA:annex:III"]  # deduped
    assert body["disclaimer"].startswith("Information only")


def test_auth_required(tmp_path: Path) -> None:
    client = make(tmp_path)
    response = client.post("/v1/ask", json={"question": "q?"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Unauthorized"
    bad = client.post("/v1/ask", json={"question": "q?"}, headers={"X-API-Key": "wrong"})
    assert bad.status_code == 401
    bearer = client.post(
        "/v1/ask", json={"question": "q?"}, headers={"Authorization": "Bearer test-key"}
    )
    assert bearer.status_code == 200


def test_validation_errors_are_problem_json(tmp_path: Path) -> None:
    client = make(tmp_path)
    assert client.post("/v1/ask", json={}, headers=KEY).status_code == 422
    too_long = client.post("/v1/ask", json={"question": "x" * 5000}, headers=KEY)
    assert too_long.status_code == 422
    assert "longer" in too_long.json()["detail"]


def test_fault_llm_down_gives_sources_only(tmp_path: Path) -> None:
    def down(guarded: GuardrailResult) -> AgentResult:
        raise LLMError("429 from every provider", retryable=True, status=429)

    body = make(tmp_path, answer=down).post("/v1/ask", json={"question": "q?"}, headers=KEY).json()
    assert body["mode"] == "sources_only"
    assert body["degraded"] == ["llm_unavailable"]
    assert body["sources"]


def test_fault_budget_exhausted_gives_sources_only(tmp_path: Path) -> None:
    budget = DailyBudget(0.001)
    budget.record(0.01)
    body = (
        make(tmp_path, budget=budget).post("/v1/ask", json={"question": "q?"}, headers=KEY).json()
    )
    assert body["mode"] == "sources_only"
    assert body["degraded"] == ["budget_exhausted"]


def test_budget_is_charged(tmp_path: Path) -> None:
    budget = DailyBudget(1.0)
    make(tmp_path, budget=budget).post("/v1/ask", json={"question": "q?"}, headers=KEY)
    assert budget.spent_usd == pytest.approx(0.002)


def test_fault_qdrant_down_gives_503_retry_after(tmp_path: Path) -> None:
    def broken(question: str) -> list[Hit]:
        raise ConnectionError("qdrant unreachable")

    response = make(tmp_path, retrieve=broken).post("/v1/ask", json={"question": "q?"}, headers=KEY)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.json()["title"] == "Search index unavailable"


def test_llm_not_configured_still_serves_sources(tmp_path: Path) -> None:
    body = make(tmp_path, answer=None).post("/v1/ask", json={"question": "q?"}, headers=KEY).json()
    assert body["degraded"] == ["llm_not_configured"]


def test_sse_stream(tmp_path: Path) -> None:
    client = make(tmp_path)
    with client.stream("POST", "/v1/ask?stream=true", json={"question": "q?"}, headers=KEY) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = [
        line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")
    ]
    assert events == ["status", "sources", "answer", "done"]


def test_sse_reports_errors_as_events(tmp_path: Path) -> None:
    def broken(question: str) -> list[Hit]:
        raise ConnectionError("down")

    with make(tmp_path, retrieve=broken).stream("POST", "/ui/ask", json={"question": "q?"}) as r:
        text = "".join(r.iter_text())
    assert "event: error" in text
    assert '"status": 503' in text


def test_rate_limit_per_key(tmp_path: Path) -> None:
    client = make(tmp_path)
    clock = [0.0]
    client.app.state.key_limiter = RateLimiter(2, clock=lambda: clock[0])  # type: ignore[attr-defined]
    codes = [
        client.post("/v1/ask", json={"question": "q?"}, headers=KEY).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    clock[0] = 31.0  # one token refilled after 30 s at 2/min
    assert client.post("/v1/ask", json={"question": "q?"}, headers=KEY).status_code == 200


def test_rate_limit_response_has_retry_after(tmp_path: Path) -> None:
    client = make(tmp_path)
    client.app.state.public_limiter = RateLimiter(1, clock=lambda: 0.0)  # type: ignore[attr-defined]
    client.post("/ui/ask", json={"question": "q?"})
    limited = client.post("/ui/ask", json={"question": "q?"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_feedback_is_recorded_and_masked(tmp_path: Path) -> None:
    client = make(tmp_path)
    response = client.post(
        "/v1/feedback",
        json={"request_id": "req-12345678", "value": "down", "comment": "wrong, mail me at a@b.io"},
    )
    assert response.status_code == 202
    entry = json.loads((tmp_path / "feedback.jsonl").read_text().splitlines()[0])
    assert entry["value"] == "down"
    assert entry["comment"] == "wrong, mail me at [EMAIL]"


def test_unhandled_error_is_problem_json(tmp_path: Path) -> None:
    def explode(guarded: GuardrailResult) -> AgentResult:
        raise ZeroDivisionError("bug")

    client = TestClient(make(tmp_path, answer=explode).app, raise_server_exceptions=False)
    response = client.post("/v1/ask", json={"question": "q?"}, headers=KEY)
    assert response.status_code == 500
    assert "bug" not in response.text  # no internals leaked


def test_ui_page_is_served(tmp_path: Path) -> None:
    client = make(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "RegLens" in page.text
    assert "non consulenza legale" in page.text
    assert client.get("/static/app.js").status_code == 200
