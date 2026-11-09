"""Dense (embedding) retrieval."""

from __future__ import annotations

from qdrant_client import QdrantClient

from reglens.ingestion.embed import DenseEncoder
from reglens.ingestion.index import DENSE
from reglens.retrieval.qdrant import Hit, SearchFilters, to_hits


class DenseRetriever:
    name = "dense"

    def __init__(self, client: QdrantClient, collection: str, encoder: DenseEncoder) -> None:
        self.client = client
        self.collection = collection
        self.encoder = encoder

    def search(self, query: str, k: int, filters: SearchFilters | None = None) -> list[Hit]:
        response = self.client.query_points(
            self.collection,
            query=self.encoder.embed_query(query),
            using=DENSE,
            limit=k,
            query_filter=filters.to_qdrant() if filters else None,
            with_payload=True,
        )
        return to_hits(response.points)
