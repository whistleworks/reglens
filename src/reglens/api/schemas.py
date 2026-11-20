"""Pydantic models at the API boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = {
    "en": "Information only, not legal advice. Always check the official text on EUR-Lex.",
    "it": (
        "Solo informazione, non consulenza legale. Verifica sempre il testo ufficiale su EUR-Lex."
    ),
}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="Question about the AI Act or the GDPR")
    lang: Literal["en", "it"] | None = Field(default=None, description="Answer language hint")


class SourceOut(BaseModel):
    id: str
    title: str
    url: str
    snippet: str


class CitationOut(BaseModel):
    id: str
    quote: str | None = None
    title: str | None = None
    url: str | None = None


class AskResponse(BaseModel):
    request_id: str
    answer: str
    citations: list[CitationOut]
    sources: list[SourceOut]
    status: str
    refused: bool
    reason: str | None = None
    route: str | None = None
    mode: Literal["full", "sources_only"] = "full"
    degraded: list[str] = Field(default_factory=list)
    latency_ms: float
    cost_usd: float = 0.0
    disclaimer: str


class FeedbackRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    value: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class Problem(BaseModel):
    """RFC 7807 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
