"""FastAPI application factory.

uvicorn reglens.api.main:create_app --factory --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from reglens import __version__
from reglens.api.errors import install_error_handlers
from reglens.api.middleware import install_middleware
from reglens.api.ratelimit import RateLimiter
from reglens.api.routes import router
from reglens.api.services import Services
from reglens.config import Settings, get_settings
from reglens.observability.logging import configure_logging
from reglens.observability.metrics import METRICS
from reglens.observability.tracing import setup_tracing

STATIC = Path(__file__).parents[1] / "web" / "static"


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    setup_tracing(settings)
    METRICS.enable_otel(settings)
    app = FastAPI(
        title="RegLens",
        version=__version__,
        description=(
            "Agentic RAG over the EU AI Act and the GDPR with verifiable citations. "
            "Information only, not legal advice."
        ),
    )
    if services is None:  # pragma: no cover - production wiring
        from reglens.api.services import build_services

        services = build_services()
    app.state.services = services
    app.state.settings = settings
    app.state.key_limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.ip_limiter = RateLimiter(settings.rate_limit_per_min * 2)
    app.state.public_limiter = RateLimiter(max(3, settings.rate_limit_per_min // 3))
    install_error_handlers(app)
    install_middleware(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.include_router(router)
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(STATIC / "index.html")

    return app
