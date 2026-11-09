"""Text actually sent to the embedding models for each chunk.

M1 baseline: the chunk text as is (``none``). M2 adds the hierarchical prefix
("GDPR > Chapter III > Art. 17 ... > par. 1") as a second strategy for the ablation.
"""

from __future__ import annotations

from typing import Literal

from reglens.ingestion.chunk import Chunk

EnrichStrategy = Literal["none"]


def embedding_text(chunk: Chunk, strategy: EnrichStrategy = "none") -> str:
    if strategy == "none":
        return chunk.text
    raise ValueError(f"unknown enrichment strategy {strategy!r}")  # pragma: no cover
