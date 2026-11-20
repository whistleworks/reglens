"""Cross-encoder reranking (optional stage, enabled only if the ablation justifies it)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from reglens.retrieval.qdrant import Hit


class Reranker(Protocol):
    name: str

    def scores(self, query: str, documents: Sequence[str]) -> list[float]: ...


class FastEmbedReranker:
    """``BAAI/bge-reranker-v2-m3`` (Apache-2.0, multilingual) via FastEmbed ONNX on CPU."""

    def __init__(self, model_name: str, *, batch_size: int = 16) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = model_name
        self.batch_size = batch_size
        self._model = TextCrossEncoder(model_name)

    def scores(self, query: str, documents: Sequence[str]) -> list[float]:
        return [
            float(s) for s in self._model.rerank(query, list(documents), batch_size=self.batch_size)
        ]


def rerank(query: str, hits: Sequence[Hit], reranker: Reranker, top_n: int) -> list[Hit]:
    """Rescore the first ``top_n`` hits with the cross-encoder; the tail keeps its order."""
    head, tail = list(hits[:top_n]), list(hits[top_n:])
    if not head:
        return []
    scores = reranker.scores(query, [str(h.payload.get("text", "")) for h in head])
    order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
    reranked = [head[i].model_copy(update={"score": scores[i]}) for i in order]
    return reranked + tail
