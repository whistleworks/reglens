"""RFC 7807 ``application/problem+json`` error responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from reglens.api.schemas import Problem
from reglens.observability.logging import get_logger

log = get_logger(__name__)
PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status, self.title, self.detail, self.type = status, title, detail, type_
        self.headers = headers or {}


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    *,
    type_: str = "about:blank",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = Problem(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        request_id=request_id,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            request, exc.status, exc.title, exc.detail, type_=exc.type, headers=exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []))
        return problem_response(
            request, 422, "Invalid request", f"{where}: {first.get('msg', 'invalid')}"
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("api.unhandled_error", error_type=type(exc).__name__)
        return problem_response(
            request, 500, "Internal error", "An unexpected error occurred; it has been logged."
        )
