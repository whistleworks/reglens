"""Retrieval pipeline: bm25 | dense | hybrid (RRF), with optional cross-encoder rerank.

Every stage is timed so evaluation (and later tracing) can report per-stage latency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

from reglens.ingestion.sources import Lang
from reglens.observability.logging import get_logger
from reglens.observability.tracing import span
from reglens.retrieval.fusion import RRF_K, rrf
from reglens.retrieval.lang import detect_lang
from reglens.retrieval.qdrant import Hit, SearchFilters
from reglens.retrieval.rerank import Reranker, rerank

log = get_logger(__name__)

Mode = Literal["bm25", "dense", "hybrid"]


class _Dense(Protocol):
    def search(self, query: str, k: int, filters: SearchFilters | None = None) -> list[Hit]: ...


class _Sparse(Protocol):
    def search(
        self, query: str, k: int, filters: SearchFilters | None = None, *, query_lang: Lang = "en"
    ) -> list[Hit]: ...


@dataclass
class RetrievalResult:
    hits: list[Hit]
    latency_ms: dict[str, float] = field(default_factory=dict)
    query_lang: Lang = "en"
    degraded: list[str] = field(default_factory=list)


class RetrievalPipeline:
    def __init__(
        self,
        mode: Mode,
        *,
        dense: _Dense | None = None,
        sparse: _Sparse | None = None,
        reranker: Reranker | None = None,
        candidates: int = 50,
        rerank_top_n: int = 20,
        rrf_k: int = RRF_K,
    ) -> None:
        if mode in ("dense", "hybrid") and dense is None:
            raise ValueError(f"mode {mode!r} needs a dense retriever")
        if mode in ("bm25", "hybrid") and sparse is None:
            raise ValueError(f"mode {mode!r} needs a sparse retriever")
        self.mode = mode
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.candidates = candidates
        self.rerank_top_n = rerank_top_n
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        query_lang: Lang | None = None,
    ) -> RetrievalResult:
        latency: dict[str, float] = {}
        started_total = time.perf_counter()
        lang = query_lang or detect_lang(query)

        rankings: list[list[Hit]] = []
        if self.mode in ("dense", "hybrid"):
            assert self.dense is not None
            t = time.perf_counter()
            with span("retrieval.dense", k=self.candidates):
                rankings.append(self.dense.search(query, self.candidates, filters))
            latency["dense"] = _ms(t)
        if self.mode in ("bm25", "hybrid"):
            assert self.sparse is not None
            t = time.perf_counter()
            with span("retrieval.sparse", k=self.candidates, query_lang=lang):
                rankings.append(
                    self.sparse.search(query, self.candidates, filters, query_lang=lang)
                )
            latency["sparse"] = _ms(t)

        if len(rankings) > 1:
            t = time.perf_counter()
            hits = rrf(rankings, k=self.rrf_k, limit=self.candidates)
            latency["fusion"] = _ms(t)
        else:
            hits = rankings[0]

        degraded: list[str] = []
        if self.reranker is not None:
            t = time.perf_counter()
            try:
                with span("rerank", top_n=self.rerank_top_n):
                    hits = rerank(query, hits, self.reranker, self.rerank_top_n)
            except Exception as exc:  # degrade to fused order rather than failing the request
                log.warning("retrieval.rerank_failed", error_type=type(exc).__name__)
                degraded.append("rerank_unavailable")
            latency["rerank"] = _ms(t)

        latency["total"] = _ms(started_total)
        return RetrievalResult(hits=hits, latency_ms=latency, query_lang=lang, degraded=degraded)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
