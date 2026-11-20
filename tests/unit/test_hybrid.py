from __future__ import annotations

from collections.abc import Sequence

import pytest

from reglens.retrieval.fusion import rrf
from reglens.retrieval.lang import detect_lang
from reglens.retrieval.pipeline import RetrievalPipeline
from reglens.retrieval.qdrant import Hit, SearchFilters
from reglens.retrieval.rerank import rerank


def hit(chunk: str, score: float = 1.0, text: str = "") -> Hit:
    unit = chunk.split("#")[0]
    return Hit(
        chunk_id=chunk,
        unit_id=unit,
        article_id=":".join(unit.split(":")[:3]),
        score=score,
        payload={"text": text or chunk},
    )


def test_rrf_hand_computed() -> None:
    # dense: A B C ; sparse: B D A   (k = 60)
    # A = 1/61 + 1/63 ; B = 1/62 + 1/61 ; C = 1/63 ; D = 1/62
    dense = [hit("A"), hit("B"), hit("C")]
    sparse = [hit("B"), hit("D"), hit("A")]
    fused = rrf([dense, sparse])
    assert [h.chunk_id for h in fused] == ["B", "A", "D", "C"]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[3].score == pytest.approx(1 / 63)


def test_rrf_limit_and_ties_are_deterministic() -> None:
    fused = rrf([[hit("Y")], [hit("X")]], limit=1)
    assert [h.chunk_id for h in fused] == ["X"]  # equal scores: ordered by id


class FakeReranker:
    name = "fake"

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        return [float(doc.count(query)) for doc in documents]


def test_rerank_reorders_head_and_keeps_tail() -> None:
    hits = [hit("A", text="x"), hit("B", text="q q"), hit("C", text="q"), hit("D", text="q q q")]
    out = rerank("q", hits, FakeReranker(), top_n=3)
    assert [h.chunk_id for h in out] == ["B", "C", "A", "D"]  # D is beyond top_n
    assert out[0].score == 2.0


class FakeRetriever:
    def __init__(self, ranking: list[Hit]) -> None:
        self.ranking = ranking
        self.calls: list[tuple[str, int, SearchFilters | None, str | None]] = []

    def search(
        self, query: str, k: int, filters: SearchFilters | None = None, *, query_lang: str = "en"
    ) -> list[Hit]:
        self.calls.append((query, k, filters, query_lang))
        return self.ranking[:k]


def test_hybrid_pipeline_fuses_reranks_and_times_stages() -> None:
    dense = FakeRetriever([hit("A"), hit("B")])
    sparse = FakeRetriever([hit("B"), hit("C")])
    pipeline = RetrievalPipeline(
        "hybrid", dense=dense, sparse=sparse, reranker=FakeReranker(), candidates=10
    )
    result = pipeline.search("Quali pratiche sono vietate?")
    assert result.query_lang == "it"
    assert sparse.calls[0][3] == "it"  # the detected language picks the BM25 stemmer
    assert {h.chunk_id for h in result.hits} == {"A", "B", "C"}
    assert set(result.latency_ms) == {"dense", "sparse", "fusion", "rerank", "total"}


def test_single_mode_pipelines() -> None:
    dense = FakeRetriever([hit("A")])
    assert [h.chunk_id for h in RetrievalPipeline("dense", dense=dense).search("q").hits] == ["A"]
    with pytest.raises(ValueError, match="sparse"):
        RetrievalPipeline("bm25", dense=dense)
    with pytest.raises(ValueError, match="dense"):
        RetrievalPipeline("hybrid", sparse=dense)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Quali pratiche di IA sono vietate dall'AI Act?", "it"),
        ("Che rapporto c'è tra la FRIA e la DPIA?", "it"),
        ("Which AI practices are prohibited by the AI Act?", "en"),
        ("A chatbot used for hiring decisions: is it high-risk?", "en"),
        ("GDPR", "en"),  # no evidence: default English
    ],
)
def test_detect_lang(text: str, lang: str) -> None:
    assert detect_lang(text) == lang
