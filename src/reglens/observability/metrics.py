"""Application metrics: in-process registry exposed as Prometheus text at /metrics, and
mirrored to OpenTelemetry (OTLP -> Grafana Cloud) when OTEL_EXPORTER_OTLP_ENDPOINT is set.

Metric names follow the brief (section 7): requests_total, errors_total, latency_seconds,
tokens_total, cost_usd_total, agent_steps, refusals_total, citation_failures_total,
cache_hits_total, llm_fallbacks_total, provider_429_total, retrieval_top_score,
feedback_total, degraded_total, budget_remaining_usd.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from reglens.config import Settings
from reglens.observability.logging import get_logger

log = get_logger(__name__)

LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30)
SCORE_BUCKETS = (0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0.3, 0.5, 0.7, 0.9)
STEP_BUCKETS = (1, 2, 3, 4, 5, 6)
_HISTOGRAM_BUCKETS = {
    "latency_seconds": LATENCY_BUCKETS,
    "retrieval_top_score": SCORE_BUCKETS,
    "agent_steps": STEP_BUCKETS,
}

Labels = tuple[tuple[str, str], ...]


def _labels(labels: dict[str, Any] | None) -> Labels:
    return tuple(sorted((k, str(v)) for k, v in (labels or {}).items()))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, dict[Labels, float]] = defaultdict(lambda: defaultdict(float))
        self.gauges: dict[str, dict[Labels, float]] = defaultdict(dict)
        self.hist: dict[str, dict[Labels, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._otel: dict[str, Any] = {}
        self._meter: Any = None

    def enable_otel(self, settings: Settings) -> bool:
        if not settings.otel_exporter_otlp_endpoint:
            return False
        from opentelemetry import metrics as otel_metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        headers = dict(
            pair.split("=", 1)
            for pair in (settings.otel_exporter_otlp_headers or "").split(",")
            if "=" in pair
        )
        exporter = OTLPMetricExporter(
            endpoint=settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/metrics",
            headers=headers,
        )
        provider = MeterProvider(metric_readers=[PeriodicExportingMetricReader(exporter, 30_000)])
        otel_metrics.set_meter_provider(provider)
        self._meter = otel_metrics.get_meter("reglens")
        log.info("metrics.otel_enabled")
        return True

    def _instrument(self, kind: str, name: str) -> Any:
        if self._meter is None:
            return None
        if name not in self._otel:
            factory = {
                "counter": self._meter.create_counter,
                "hist": self._meter.create_histogram,
                "gauge": self._meter.create_gauge,
            }[kind]
            self._otel[name] = factory(name)
        return self._otel[name]

    def inc(self, name: str, value: float = 1.0, **labels: Any) -> None:
        with self._lock:
            self.counters[name][_labels(labels)] += value
        if (inst := self._instrument("counter", name)) is not None:
            inst.add(value, {k: str(v) for k, v in labels.items()})

    def observe(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self.hist[name][_labels(labels)].append(value)
        if (inst := self._instrument("hist", name)) is not None:
            inst.record(value, {k: str(v) for k, v in labels.items()})

    def set(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self.gauges[name][_labels(labels)] = value
        if (inst := self._instrument("gauge", name)) is not None:
            inst.set(value, {k: str(v) for k, v in labels.items()})

    def prometheus(self) -> str:
        def fmt(labels: Labels, extra: tuple[tuple[str, str], ...] = ()) -> str:
            items = list(labels) + list(extra)
            if not items:
                return ""
            return "{" + ",".join(f'{k}="{v}"' for k, v in items) + "}"

        lines: list[str] = []
        with self._lock:
            for name, counter in sorted(self.counters.items()):
                lines.append(f"# TYPE reglens_{name} counter")
                lines += [f"reglens_{name}{fmt(lb)} {v}" for lb, v in counter.items()]
            for name, gauge in sorted(self.gauges.items()):
                lines.append(f"# TYPE reglens_{name} gauge")
                lines += [f"reglens_{name}{fmt(lb)} {v}" for lb, v in gauge.items()]
            for name, series in sorted(self.hist.items()):
                buckets = _HISTOGRAM_BUCKETS.get(name, LATENCY_BUCKETS)
                lines.append(f"# TYPE reglens_{name} histogram")
                for lb, values in series.items():
                    for edge in buckets:
                        count = sum(v <= edge for v in values)
                        lines.append(
                            f"reglens_{name}_bucket{fmt(lb, (('le', str(edge)),))} {count}"
                        )
                    lines.append(f"reglens_{name}_bucket{fmt(lb, (('le', '+Inf'),))} {len(values)}")
                    lines.append(f"reglens_{name}_sum{fmt(lb)} {sum(values)}")
                    lines.append(f"reglens_{name}_count{fmt(lb)} {len(values)}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()
