"""Text actually sent to the embedding models for each chunk.

* ``none``: the chunk text as is (M1 baseline);
* ``hierarchy``: the hierarchical path first ("GDPR > Capo III > Articolo 17 Diritto alla
  cancellazione > par. 1"), so that a bare paragraph carries the context of its parent.
  The prefix is applied to both the dense and the BM25 representation.
"""

from __future__ import annotations

from typing import Literal

from reglens.ingestion.chunk import Chunk

EnrichStrategy = Literal["none", "hierarchy"]


def embedding_text(chunk: Chunk, strategy: EnrichStrategy = "none") -> str:
    if strategy == "none":
        return chunk.text
    if strategy == "hierarchy":
        return f"{chunk.path}\n{chunk.text}"
    raise ValueError(f"unknown enrichment strategy {strategy!r}")  # pragma: no cover
