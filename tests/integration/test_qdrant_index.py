"""Real models + Qdrant in Docker. Run with `make qdrant && make test-integration`."""

from __future__ import annotations

import uuid

import pytest
from qdrant_client import QdrantClient

from reglens.config import get_settings
from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
from reglens.ingestion.index import index_chunks
from reglens.retrieval.dense import DenseRetriever
from reglens.retrieval.qdrant import SearchFilters, make_client
from reglens.retrieval.sparse import SparseRetriever
from tests.unit.test_index_retrieval import CHUNKS

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> QdrantClient:
    client = make_client(get_settings())
    try:
        client.get_collections()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Qdrant not reachable: {exc}")
    return client


def test_real_models_index_and_search(client: QdrantClient) -> None:
    name = f"test_{uuid.uuid4().hex[:8]}"
    dense = FastEmbedDense(get_settings().embedding_model)
    sparse = FastEmbedBM25(get_settings().sparse_model)
    try:
        info = index_chunks(client, name, CHUNKS, dense, sparse)
        assert info["points"] == len(CHUNKS)
        assert set(info["bm25_avg_len"]) == {"en", "it"}

        bm25 = SparseRetriever(client, name, sparse)
        assert bm25.search("right to erasure", k=1)[0].unit_id == "GDPR:art:17:par:1"
        # Italian stemming: "vietate" in the doc, "vietata" in the query
        it_hits = bm25.search("pratica vietata", k=1, query_lang="it")
        assert it_hits[0].chunk_id == "AIA:art:5:par:1#it"

        e5 = DenseRetriever(client, name, dense)
        # cross-lingual: an Italian question finds the English GDPR article
        hit = e5.search("diritto all'oblio", k=1, filters=SearchFilters(lang="en"))[0]
        assert hit.unit_id == "GDPR:art:17:par:1"
    finally:
        client.delete_collection(name)
