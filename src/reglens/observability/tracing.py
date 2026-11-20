"""OpenTelemetry tracing, exported over OTLP to Langfuse (or any OTLP backend).

Langfuse ingests OTLP at ``{LANGFUSE_HOST}/api/public/otel/v1/traces`` with Basic auth
(public key : secret key). Without credentials the global no-op tracer is used, so the
code paths are identical in tests, CI and production.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from reglens import __version__
from reglens.config import Settings
from reglens.observability.logging import get_logger, mask_pii

log = get_logger(__name__)
TRACER_NAME = "reglens"
_configured = False


def _langfuse_exporter(settings: Settings) -> SpanExporter | None:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    public = settings.langfuse_public_key
    secret = settings.langfuse_secret_key
    if not public or not secret:
        return None
    token = base64.b64encode(f"{public}:{secret.get_secret_value()}".encode()).decode()
    return OTLPSpanExporter(
        endpoint=settings.langfuse_host.rstrip("/") + "/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {token}"},
    )


def setup_tracing(settings: Settings, exporter: SpanExporter | None = None) -> bool:
    """Install a real tracer provider if an exporter is available. Returns True if enabled."""
    global _configured
    if _configured:
        return True
    exporter = exporter or _langfuse_exporter(settings)
    if exporter is None:
        return False
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "reglens",
                "service.version": __version__,
                "deployment.environment": settings.app_env,
                "git.sha": settings.git_sha,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    log.info("tracing.enabled", exporter=type(exporter).__name__)
    return True


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME, __version__)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value)[:4000]
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list | tuple):
        return [str(v)[:200] for v in value][:50]
    return str(value)[:4000]


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Span with PII-masked attributes; ``None`` attributes are skipped."""
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, _clean(value))
        yield current


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
