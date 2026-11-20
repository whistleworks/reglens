"""Sparse BM25 retrieval (term weights from FastEmbed, IDF applied by Qdrant)."""

from __future__ import annotations

from qdrant_client import QdrantClient, models

from reglens.ingestion.embed import SparseEncoder
from reglens.ingestion.index import SPARSE
from reglens.ingestion.sources import Lang
from reglens.retrieval.qdrant import Hit, SearchFilters, to_hits


class SparseRetriever:
    name = "bm25"

    def __init__(self, client: QdrantClient, collection: str, encoder: SparseEncoder) -> None:
        self.client = client
        self.collection = collection
        self.encoder = encoder

    def search(
        self,
        query: str,
        k: int,
        filters: SearchFilters | None = None,
        *,
        query_lang: Lang = "en",
    ) -> list[Hit]:
        """``query_lang`` selects the stemmer/stopwords for the query (not a filter)."""
        vector = self.encoder.embed_query(query, query_lang)
        response = self.client.query_points(
            self.collection,
            query=models.SparseVector(indices=vector.indices, values=vector.values),
            using=SPARSE,
            limit=k,
            query_filter=filters.to_qdrant() if filters else None,
            with_payload=True,
        )
        return to_hits(response.points)
