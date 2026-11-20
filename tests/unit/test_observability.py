from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from reglens.config import Settings
from reglens.observability.metrics import Metrics
from reglens.observability.tracing import setup_tracing, span
from tests.unit.test_api import KEY, make

EXPORTER = InMemorySpanExporter()


def _spans() -> list[str]:
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    provider.force_flush()  # type: ignore[attr-defined]
    return [s.name for s in EXPORTER.get_finished_spans()]


def test_request_produces_a_trace_with_stage_spans(tmp_path: Path) -> None:
    setup_tracing(Settings(_env_file=None), exporter=EXPORTER)  # type: ignore[call-arg]
    EXPORTER.clear()
    client: TestClient = make(tmp_path)
    assert client.post("/v1/ask", json={"question": "high-risk?"}, headers=KEY).status_code == 200
    names = _spans()
    assert {"request", "retrieval", "answer"} <= set(names)
    request_span = next(s for s in EXPORTER.get_finished_spans() if s.name == "request")
    attrs = dict(request_span.attributes or {})
    assert attrs["status"] == "answered"
    assert attrs["version.git_sha"] == "abc"


def test_span_attributes_are_masked() -> None:
    setup_tracing(Settings(_env_file=None), exporter=EXPORTER)  # type: ignore[call-arg]
    EXPORTER.clear()
    with span("probe", question="write to mario@example.com", empty=None, ids=["a", "b"]):
        pass
    _spans()
    probe = next(s for s in EXPORTER.get_finished_spans() if s.name == "probe")
    attrs = dict(probe.attributes or {})
    assert attrs["question"] == "write to [EMAIL]"
    assert "empty" not in attrs
    assert list(attrs["ids"]) == ["a", "b"]  # type: ignore[arg-type]


def test_prometheus_exposition() -> None:
    metrics = Metrics()
    metrics.inc("requests_total", route="/v1/ask", status=200)
    metrics.inc("requests_total", route="/v1/ask", status=200)
    metrics.observe("latency_seconds", 0.3, stage="http")
    metrics.set("budget_remaining_usd", 0.75)
    text = metrics.prometheus()
    assert 'reglens_requests_total{route="/v1/ask",status="200"} 2.0' in text
    assert 'reglens_latency_seconds_bucket{stage="http",le="0.5"} 1' in text
    assert 'reglens_latency_seconds_bucket{stage="http",le="0.25"} 0' in text
    assert "reglens_budget_remaining_usd 0.75" in text


def test_metrics_endpoint_counts_requests(tmp_path: Path) -> None:
    client = make(tmp_path)
    client.get("/health")
    body = client.get("/metrics").text
    assert 'reglens_requests_total{route="/health",status="200"}' in body


def test_otel_disabled_without_endpoint() -> None:
    assert Metrics().enable_otel(Settings(_env_file=None)) is False  # type: ignore[call-arg]
