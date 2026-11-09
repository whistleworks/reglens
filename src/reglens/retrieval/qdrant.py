"""Qdrant client factory, retrieval result type and metadata filters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
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

    def to_qdrant(self) -> models.Filter | None:
        conditions: list[models.Condition] = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in self.model_dump().items()
            if value is not None
        ]
        return models.Filter(must=conditions) if conditions else None


def make_client(settings: Settings) -> QdrantClient:
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
