"""HTTP routes: /v1/ask (JSON or SSE), /v1/feedback, /ui/ask, /health, /ready, /version."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from reglens import __version__
from reglens.agent.guardrails import InputRejectedError, check_input
from reglens.api.auth import extract_key, key_matches
from reglens.api.errors import ProblemError
from reglens.api.middleware import client_ip
from reglens.api.ratelimit import RateLimiter, hash_ip
from reglens.api.schemas import DISCLAIMER, AskRequest, AskResponse, FeedbackRequest
from reglens.api.services import RetrievalUnavailableError, Services
from reglens.config import Settings
from reglens.observability.metrics import METRICS
from reglens.retrieval.lang import detect_lang

router = APIRouter()


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


def settings(request: Request) -> Settings:
    cfg: Settings = request.app.state.settings
    return cfg


ServicesDep = Annotated[Services, Depends(services)]
SettingsDep = Annotated[Settings, Depends(settings)]


def _limit(limiter: RateLimiter, identity: str) -> None:
    allowed, retry_after = limiter.allow(identity)
    if not allowed:
        raise ProblemError(
            429,
            "Too many requests",
            "Rate limit exceeded, retry later.",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )


def require_api_key(request: Request, cfg: SettingsDep) -> str:
    key = extract_key(request)
    valid = [k.get_secret_value() for k in cfg.api_keys]
    if not key_matches(key, valid):
        raise ProblemError(
            401,
            "Unauthorized",
            "A valid API key is required (X-API-Key).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    assert key is not None
    _limit(request.app.state.key_limiter, f"key:{hash_ip(key)}")
    _limit(request.app.state.ip_limiter, f"ip:{hash_ip(client_ip(request))}")
    return key


def public_limit(request: Request) -> None:
    _limit(request.app.state.public_limiter, f"pub:{hash_ip(client_ip(request))}")


def _ask(req: AskRequest, request: Request, svc: Services, cfg: Settings) -> AskResponse:
    started = time.perf_counter()
    try:
        guarded = check_input(req.question, cfg.max_input_chars)
    except InputRejectedError as exc:
        raise ProblemError(422, "Invalid question", str(exc)) from exc
    try:
        outcome = svc.ask(guarded)
    except RetrievalUnavailableError as exc:
        raise ProblemError(
            503,
            "Search index unavailable",
            "The legal index is temporarily unreachable.",
            headers={"Retry-After": "30"},
        ) from exc
    lang = req.lang or detect_lang(req.question)
    return AskResponse(
        request_id=request.state.request_id,
        answer=outcome.answer,
        citations=outcome.citations,
        sources=outcome.sources,
        status=outcome.status,
        refused=outcome.status not in ("answered", "clarify"),
        reason=outcome.reason,
        route=outcome.route,
        mode=outcome.mode,
        degraded=outcome.degraded,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        cost_usd=outcome.cost_usd,
        disclaimer=DISCLAIMER[lang],
    )


async def _sse(
    req: AskRequest, request: Request, svc: Services, cfg: Settings
) -> AsyncIterator[str]:
    def event(name: str, data: object) -> str:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    yield event("status", {"stage": "retrieval", "request_id": request.state.request_id})
    try:
        response = await run_in_threadpool(_ask, req, request, svc, cfg)
    except ProblemError as exc:
        yield event("error", {"status": exc.status, "title": exc.title, "detail": exc.detail})
        return
    yield event("sources", [s.model_dump() for s in response.sources])
    yield event("answer", response.model_dump())
    yield event("done", {"latency_ms": response.latency_ms})


@router.post("/v1/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
async def ask(
    req: AskRequest,
    request: Request,
    svc: ServicesDep,
    cfg: SettingsDep,
    stream: bool = False,
) -> AskResponse | StreamingResponse:
    if stream:
        return StreamingResponse(
            _sse(req, request, svc, cfg),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
    return await run_in_threadpool(_ask, req, request, svc, cfg)


@router.post("/ui/ask", response_model=AskResponse, dependencies=[Depends(public_limit)])
async def ui_ask(
    req: AskRequest,
    request: Request,
    svc: ServicesDep,
    cfg: SettingsDep,
) -> StreamingResponse:
    """Public route used by the web UI: no key, stricter per-IP rate limit, always SSE."""
    return StreamingResponse(
        _sse(req, request, svc, cfg),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/v1/feedback", status_code=202)
@router.post(
    "/ui/feedback", status_code=202, include_in_schema=False, dependencies=[Depends(public_limit)]
)
async def feedback(req: FeedbackRequest, svc: ServicesDep) -> dict[str, str]:
    await run_in_threadpool(svc.record_feedback, req.request_id, req.value, req.comment)
    METRICS.inc("feedback_total", vote=req.value)
    return {"status": "recorded"}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(METRICS.prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(svc: ServicesDep) -> JSONResponse:
    """Ready when the index answers. Optional dependencies (LLM) are reported, not required:
    without them the API still serves "sources only" answers."""

    async def run(checks: dict[str, Any]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for name, check in checks.items():
            try:
                out[name] = bool(await run_in_threadpool(check))
            except Exception:
                out[name] = False
        return out

    required = await run(svc.ready_checks)
    optional = await run(svc.info_checks)
    ok = all(required.values())
    status = "ready" if ok and all(optional.values()) else ("degraded" if ok else "not_ready")
    return JSONResponse(
        {"status": status, "checks": {**required, **optional}}, status_code=200 if ok else 503
    )


@router.get("/version")
async def version(svc: ServicesDep) -> dict[str, str]:
    return {"version": __version__, **svc.versions}
