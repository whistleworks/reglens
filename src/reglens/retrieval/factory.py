"""Build a RetrievalPipeline from a config and the data manifest (shared by API and evals)."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from reglens.config import Settings, get_settings
from reglens.retrieval.pipeline import RetrievalPipeline


class IndexNotFoundError(LookupError):
    pass


class PipelineConfig(BaseModel):
    retriever: Literal["bm25", "dense", "hybrid"] = "hybrid"
    strategy: Literal["paragraph", "article", "fixed"] = "paragraph"
    enrich: Literal["none", "hierarchy"] = "none"
    rerank: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3-int8"
    rerank_top_n: int = 20
    candidates: int = Field(
        default=50, description="Chunks retrieved before projecting to article level"
    )
    collection: str | None = Field(default=None, description="None = from data manifest")


def resolve_index(
    config: PipelineConfig, manifest: dict[str, Any], dense_model: str
) -> dict[str, Any]:
    """The manifest index built from ``config.strategy``/``config.enrich`` (or ``collection``)."""
    indexes: dict[str, dict[str, Any]] = manifest.get("indexes") or {}
    if config.collection:
        if config.collection not in indexes:
            raise IndexNotFoundError(f"collection {config.collection} not in the data manifest")
        return indexes[config.collection]
    matches = [
        info
        for info in indexes.values()
        if info.get("strategy") == config.strategy
        and info.get("enrich") == config.enrich
        and info.get("dense_model") == dense_model
    ]
    if not matches:
        raise IndexNotFoundError(
            f"no index for strategy={config.strategy} enrich={config.enrich}: run "
            f"`make index STRATEGY={config.strategy} ENRICH={config.enrich}`"
        )
    return max(matches, key=lambda info: str(info.get("created_at", "")))


def build_pipeline(
    config: PipelineConfig, settings: Settings | None = None
) -> tuple[RetrievalPipeline, dict[str, str], str]:  # pragma: no cover - loads real models
    from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
    from reglens.retrieval.dense import DenseRetriever
    from reglens.retrieval.qdrant import make_client
    from reglens.retrieval.rerank import FastEmbedReranker
    from reglens.retrieval.sparse import SparseRetriever

    settings = settings or get_settings()
    manifest = json.loads((settings.processed_dir / "manifest.json").read_text())
    index = resolve_index(config, manifest, settings.embedding_model)
    collection = str(index["collection"])
    client = make_client(settings)
    model_ids: dict[str, str] = {}
    dense = sparse = None
    if config.retriever in ("dense", "hybrid"):
        dense = DenseRetriever(client, collection, FastEmbedDense(index["dense_model"]))
        model_ids["dense"] = index["dense_model"]
    if config.retriever in ("bm25", "hybrid"):
        sparse = SparseRetriever(client, collection, FastEmbedBM25(index["sparse_model"]))
        model_ids["sparse"] = index["sparse_model"]
    reranker = FastEmbedReranker(config.rerank_model) if config.rerank else None
    if reranker is not None:
        model_ids["reranker"] = config.rerank_model
    pipeline = RetrievalPipeline(
        config.retriever,
        dense=dense,
        sparse=sparse,
        reranker=reranker,
        candidates=config.candidates,
        rerank_top_n=config.rerank_top_n,
    )
    return pipeline, model_ids, collection
