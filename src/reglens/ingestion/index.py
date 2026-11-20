"""Upsert chunks into a versioned Qdrant collection with dense + BM25 sparse vectors."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient, models

from reglens.ingestion.chunk import Chunk
from reglens.ingestion.embed import DenseEncoder, SparseEncoder
from reglens.ingestion.enrich import EnrichStrategy, embedding_text
from reglens.ingestion.sources import LANGS, Lang
from reglens.observability.logging import get_logger

log = get_logger(__name__)

DENSE = "dense"
SPARSE = "bm25"
PAYLOAD_INDEXES = ("regulation", "lang", "type", "article_id", "unit_id")
_NAMESPACE = uuid.UUID("6f1c3f0e-8f5b-4c1e-9a43-2d1f0b6f5a10")


def point_id(chunk_id: str) -> str:
    """Stable UUID for a chunk id (Qdrant ids must be ints or UUIDs)."""
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


def model_slug(model_name: str) -> str:
    """``intfloat/multilingual-e5-large`` -> ``e5large``."""
    base = model_name.split("/")[-1].lower().replace("multilingual-", "")
    return re.sub(r"[^a-z0-9]", "", base)


def collection_name(chunks_sha: str, dense_model: str, strategy: str, enrich: str) -> str:
    """Versioned by the sha of the chunk file it is built from."""
    suffix = "" if enrich == "none" else f"_{enrich}"
    return f"reglens_{chunks_sha[:8]}_{model_slug(dense_model)}_{strategy}{suffix}"


def payload(chunk: Chunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "unit_id": chunk.unit_id,
        "article_id": chunk.article_id,
        "regulation": chunk.regulation,
        "article": chunk.article,
        "paragraph": chunk.paragraph,
        "type": chunk.type,
        "lang": chunk.lang,
        "title": chunk.title,
        "path": chunk.path,
        "url_eurlex": chunk.url_eurlex,
        "text": chunk.text,
    }


def create_collection(client: QdrantClient, name: str, dim: int, *, recreate: bool) -> None:
    if client.collection_exists(name):
        if not recreate:
            raise FileExistsError(f"collection {name} exists (use --recreate)")
        client.delete_collection(name)
    client.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for field in PAYLOAD_INDEXES:
        client.create_payload_index(name, field, field_schema=models.PayloadSchemaType.KEYWORD)


def index_chunks(
    client: QdrantClient,
    name: str,
    chunks: Sequence[Chunk],
    dense: DenseEncoder,
    sparse: SparseEncoder,
    *,
    enrich: EnrichStrategy = "none",
    batch_size: int = 64,
    recreate: bool = False,
) -> dict[str, Any]:
    create_collection(client, name, dense.dim, recreate=recreate)
    texts_by_lang: dict[Lang, list[str]] = {
        lang: [embedding_text(c, enrich) for c in chunks if c.lang == lang] for lang in LANGS
    }
    fit = getattr(sparse, "fit_avg_len", None)
    avg_len = fit(texts_by_lang) if fit is not None else None

    started = datetime.now(UTC)
    for start in range(0, len(chunks), batch_size):
        batch = list(chunks[start : start + batch_size])
        texts = [embedding_text(c, enrich) for c in batch]
        dense_vecs = dense.embed_documents(texts)
        points = []
        for chunk, text, vector in zip(batch, texts, dense_vecs, strict=True):
            sparse_vec = sparse.embed_documents([text], chunk.lang)[0]
            points.append(
                models.PointStruct(
                    id=point_id(chunk.id),
                    vector={
                        DENSE: vector,
                        SPARSE: models.SparseVector(
                            indices=sparse_vec.indices, values=sparse_vec.values
                        ),
                    },
                    payload=payload(chunk),
                )
            )
        client.upsert(name, points=points, wait=True)
        log.info("index.batch", collection=name, done=start + len(batch), total=len(chunks))

    count = client.count(name, exact=True).count
    if count != len(chunks):
        raise RuntimeError(f"indexed {count} points, expected {len(chunks)}")
    return {
        "collection": name,
        "points": count,
        "dense_model": dense.name,
        "dense_dim": dense.dim,
        "sparse_model": sparse.name,
        "bm25_avg_len": avg_len,
        "enrich": enrich,
        "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
    }
