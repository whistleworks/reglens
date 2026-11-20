"""Deterministic fake encoders for tests (no model downloads, no network)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

from reglens.ingestion.embed import SparseVec
from reglens.ingestion.sources import Lang

_WORD = re.compile(r"\w+")


def _bucket(token: str, size: int) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % size


class FakeDense:
    """Bag-of-words hashed into ``dim`` buckets, L2-normalised: similar texts -> close vectors."""

    name = "fake-dense"

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _WORD.findall(text.lower()):
            vec[_bucket(token, self.dim)] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FakeSparse:
    """Raw term frequencies keyed by a stable hash; Qdrant applies IDF."""

    name = "fake-bm25"

    def __init__(self) -> None:
        self.avg_len: dict[Lang, float] = {}

    def _vec(self, text: str) -> SparseVec:
        counts = Counter(_bucket(t, 2**31) for t in _WORD.findall(text.lower()))
        indices = sorted(counts)
        return SparseVec(indices, [float(counts[i]) for i in indices])

    def embed_documents(self, texts: Sequence[str], lang: Lang) -> list[SparseVec]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str, lang: Lang) -> SparseVec:
        vec = self._vec(text)
        return SparseVec(vec.indices, [1.0] * len(vec.indices))
