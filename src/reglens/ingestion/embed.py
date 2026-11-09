"""Dense and sparse encoders behind small protocols, so tests can inject fakes.

* Dense: ``intfloat/multilingual-e5-*`` via FastEmbed (ONNX, CPU). e5 expects the
  ``query: `` / ``passage: `` prefixes, added here explicitly.
* Sparse: BM25 term weights via FastEmbed ``Qdrant/bm25`` with a per-language Snowball
  stemmer and stopword list. IDF is applied by Qdrant (``Modifier.IDF``) at query time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from reglens.ingestion.sources import Lang

_SNOWBALL: dict[Lang, str] = {"en": "english", "it": "italian"}


@dataclass(frozen=True, slots=True)
class SparseVec:
    indices: list[int]
    values: list[float]


class DenseEncoder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SparseEncoder(Protocol):
    name: str

    def embed_documents(self, texts: Sequence[str], lang: Lang) -> list[SparseVec]: ...

    def embed_query(self, text: str, lang: Lang) -> SparseVec: ...


class FastEmbedDense:
    def __init__(
        self, model_name: str, *, batch_size: int = 32, threads: int | None = None
    ) -> None:
        from fastembed import TextEmbedding

        self.name = model_name
        self.batch_size = batch_size
        self._model = TextEmbedding(model_name, threads=threads)
        self.dim = len(next(iter(self._model.embed(["dim probe"]))))
        self._prefixed = "e5" in model_name.lower()

    def _prefix(self, kind: str, texts: Iterable[str]) -> list[str]:
        return [f"{kind}: {t}" for t in texts] if self._prefixed else list(texts)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.embed(self._prefix("passage", texts), batch_size=self.batch_size)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = next(iter(self._model.embed(self._prefix("query", [text]))))
        return [float(x) for x in vector]


class FastEmbedBM25:
    """One BM25 model per language. ``avg_len`` should be the corpus mean length in tokens."""

    def __init__(
        self, model_name: str = "Qdrant/bm25", avg_len: dict[Lang, float] | None = None
    ) -> None:
        from fastembed import SparseTextEmbedding

        self.name = model_name
        self._factory = SparseTextEmbedding
        self.avg_len: dict[Lang, float] = {}
        self._models: dict[Lang, Any] = {}
        self._build(avg_len or {})

    def _build(self, avg_len: dict[Lang, float]) -> None:
        self.avg_len = {lang: avg_len.get(lang, 256.0) for lang in _SNOWBALL}
        self._models = {
            lang: self._factory(self.name, language=snowball, avg_len=self.avg_len[lang])
            for lang, snowball in _SNOWBALL.items()
        }

    def fit_avg_len(self, texts: dict[Lang, Sequence[str]]) -> dict[Lang, float]:
        """Set BM25 ``avg_len`` per language from the documents to index (call before embedding)."""
        means = {
            lang: round(sum(lengths) / len(lengths), 2)
            for lang, docs in texts.items()
            if (lengths := self.doc_lengths(docs, lang))
        }
        self._build(means)
        return self.avg_len

    def doc_lengths(self, texts: Sequence[str], lang: Lang) -> list[int]:
        """BM25 |d| exactly as FastEmbed computes it (tokens after stopwords and stemming).

        FastEmbed's public ``token_count`` counts tokens *before* stopword removal, so
        it would bias ``avg_len``; this mirrors ``Bm25.raw_embed`` instead.
        """
        from fastembed.common.utils import remove_non_alphanumeric

        model = self._models[lang].model
        return [
            len(model._stem(model.tokenizer.tokenize(remove_non_alphanumeric(t)))) for t in texts
        ]

    def embed_documents(self, texts: Sequence[str], lang: Lang) -> list[SparseVec]:
        return [
            SparseVec(e.indices.tolist(), e.values.tolist())
            for e in self._models[lang].embed(list(texts))
        ]

    def embed_query(self, text: str, lang: Lang) -> SparseVec:
        e = next(iter(self._models[lang].query_embed(text)))
        return SparseVec(e.indices.tolist(), e.values.tolist())
