from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from reglens.ingestion.chunk import Chunk
from reglens.ingestion.index import collection_name, index_chunks, model_slug, point_id
from reglens.retrieval.dense import DenseRetriever
from reglens.retrieval.qdrant import SearchFilters
from reglens.retrieval.sparse import SparseRetriever
from tests.fakes import FakeDense, FakeSparse


def make_chunk(unit_id: str, lang: str, text: str, regulation: str = "AIA") -> Chunk:
    article_id = ":".join(unit_id.split(":")[:3])
    return Chunk(
        id=f"{unit_id}#{lang}",
        unit_id=unit_id,
        article_id=article_id,
        regulation=regulation,  # type: ignore[arg-type]
        lang=lang,  # type: ignore[arg-type]
        type="article",
        article=unit_id.split(":")[2],
        paragraph=None,
        title="t",
        path="p",
        url_eurlex="https://example.invalid",
        text=text,
        n_tokens=len(text.split()),
    )


CHUNKS = [
    make_chunk("AIA:art:5:par:1", "en", "prohibited AI practices manipulative techniques"),
    make_chunk("AIA:art:5:par:1", "it", "pratiche di IA vietate tecniche manipolative"),
    make_chunk("AIA:art:6:par:2", "en", "high-risk AI systems referred to in Annex III"),
    make_chunk("GDPR:art:17:par:1", "en", "right to erasure right to be forgotten", "GDPR"),
    make_chunk("GDPR:art:35:par:1", "en", "data protection impact assessment", "GDPR"),
]


@pytest.fixture
def client() -> QdrantClient:
    client = QdrantClient(":memory:")
    index_chunks(client, "test", CHUNKS, FakeDense(), FakeSparse())
    return client


def test_point_ids_are_stable_uuids() -> None:
    assert point_id("AIA:art:5:par:1#en") == point_id("AIA:art:5:par:1#en")
    assert point_id("AIA:art:5:par:1#en") != point_id("AIA:art:5:par:1#it")


def test_collection_name_is_versioned() -> None:
    assert model_slug("intfloat/multilingual-e5-large") == "e5large"
    assert collection_name(
        "f4a0f1877c96", "intfloat/multilingual-e5-large", "paragraph", "none"
    ) == ("reglens_f4a0f187_e5large_paragraph")


def test_index_reports_and_refuses_to_overwrite(client: QdrantClient) -> None:
    assert client.count("test", exact=True).count == len(CHUNKS)
    with pytest.raises(FileExistsError):
        index_chunks(client, "test", CHUNKS, FakeDense(), FakeSparse())
    info = index_chunks(client, "test", CHUNKS[:2], FakeDense(), FakeSparse(), recreate=True)
    assert (info["points"], info["dense_dim"]) == (2, 64)


def test_sparse_search_ranks_exact_terms_first(client: QdrantClient) -> None:
    hits = SparseRetriever(client, "test", FakeSparse()).search("right to erasure", k=3)
    assert hits[0].unit_id == "GDPR:art:17:par:1"
    assert hits[0].payload["url_eurlex"] == "https://example.invalid"


def test_dense_search_and_filters(client: QdrantClient) -> None:
    retriever = DenseRetriever(client, "test", FakeDense())
    hits = retriever.search("impact assessment", k=2)
    assert hits[0].article_id == "GDPR:art:35"
    only_it = retriever.search("prohibited practices", k=5, filters=SearchFilters(lang="it"))
    assert {h.payload["lang"] for h in only_it} == {"it"}
    only_aia = retriever.search("right", k=5, filters=SearchFilters(regulation="AIA"))
    assert {h.payload["regulation"] for h in only_aia} == {"AIA"}


def test_empty_filters_are_none() -> None:
    assert SearchFilters().to_qdrant() is None


def test_make_client_local_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from reglens.config import Settings
    from reglens.retrieval.qdrant import make_client

    settings = Settings(_env_file=None, qdrant_url=f"path:{tmp_path / 'q'}")  # type: ignore[call-arg]
    client = make_client(settings)
    index_chunks(client, "local", CHUNKS, FakeDense(), FakeSparse())
    assert client.count("local", exact=True).count == len(CHUNKS)
    client.close()
