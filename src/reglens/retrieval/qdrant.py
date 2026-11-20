"""Qdrant client factory, retrieval result type and metadata filters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from qdrant_client import QdrantClient, models

from reglens.config import Settings
from reglens.ids import Regulation
from reglens.ingestion.chunk import UnitType
from reglens.ingestion.sources import Lang


class Hit(BaseModel):
    chunk_id: str
    unit_id: str
    article_id: str
    score: float
    payload: dict[str, Any]


class SearchFilters(BaseModel):
    regulation: Regulation | None = None
    lang: Lang | None = None
    type: UnitType | None = None
    exclude_types: list[UnitType] = Field(default_factory=list)

    def to_qdrant(self) -> models.Filter | None:
        conditions: list[models.Condition] = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in self.model_dump(exclude={"exclude_types"}).items()
            if value is not None
        ]
        excluded: list[models.Condition] = (
            [models.FieldCondition(key="type", match=models.MatchAny(any=self.exclude_types))]
            if self.exclude_types
            else []
        )
        if not conditions and not excluded:
            return None
        return models.Filter(must=conditions or None, must_not=excluded or None)

    def merged(self, other: SearchFilters | None) -> SearchFilters:
        """``other`` (e.g. a tool call) wins on explicit fields; exclusions are unioned."""
        if other is None:
            return self
        data = self.model_dump()
        for key, value in other.model_dump(exclude={"exclude_types"}).items():
            if value is not None:
                data[key] = value
        data["exclude_types"] = sorted(set(self.exclude_types) | set(other.exclude_types))
        return SearchFilters.model_validate(data)


LOCAL_PREFIX = "path:"


def make_client(settings: Settings) -> QdrantClient:
    """``QDRANT_URL=http://...`` for a server; ``QDRANT_URL=path:<dir>`` for embedded local mode
    (no Docker; also the base of the ``local_snapshot`` fallback planned for M5)."""
    if settings.index_mode == "local_snapshot":
        return QdrantClient(path=str(settings.index_snapshot_path))
    if settings.qdrant_url.startswith(LOCAL_PREFIX):
        return QdrantClient(path=settings.qdrant_url.removeprefix(LOCAL_PREFIX))
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return QdrantClient(url=settings.qdrant_url, api_key=api_key, timeout=30)


def to_hits(points: list[models.ScoredPoint]) -> list[Hit]:
    hits = []
    for point in points:
        payload = point.payload or {}
        hits.append(
            Hit(
                chunk_id=str(payload["id"]),
                unit_id=str(payload["unit_id"]),
                article_id=str(payload["article_id"]),
                score=float(point.score),
                payload=payload,
            )
        )
    return hits
