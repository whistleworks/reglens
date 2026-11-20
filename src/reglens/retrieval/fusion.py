"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009).

score(d) = sum over rankings r of 1 / (k + rank_r(d)), with 1-based ranks and k = 60.
RRF uses ranks only, so BM25 scores (unbounded) and cosine similarities need no
normalisation before fusion.
"""

from __future__ import annotations

from collections.abc import Sequence

from reglens.retrieval.qdrant import Hit

RRF_K = 60


def rrf(
    rankings: Sequence[Sequence[Hit]],
    k: int = RRF_K,
    limit: int | None = None,
    weights: Sequence[float] | None = None,
) -> list[Hit]:
    """Weighted RRF: score(d) = sum_r w_r / (k + rank_r(d)); equal weights by default."""
    weights = list(weights) if weights is not None else [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("one weight per ranking is required")
    scores: dict[str, float] = {}
    first_seen: dict[str, Hit] = {}
    for weight, ranking in zip(weights, rankings, strict=True):
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    # ties broken by chunk id for determinism
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    fused = [first_seen[cid].model_copy(update={"score": scores[cid]}) for cid in ordered]
    return fused[:limit] if limit is not None else fused
