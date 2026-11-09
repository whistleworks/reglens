"""Deterministic retrieval metrics.

RegLens evaluates retrieval at ARTICLE level: retrieved chunk ids are projected to their
article (or recital/annex), deduplicated keeping the first occurrence, and compared with
the gold ids projected the same way. This keeps chunking ablations comparable.

``gold`` is either a set of ids (binary relevance) or a ``{id: grade}`` mapping (graded
relevance, used by the BEIR sanity check).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from reglens.ids import parse_id

Gold = set[str] | Mapping[str, int]


def dedup(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def to_article_level(ids: Iterable[str]) -> list[str]:
    return dedup(str(parse_id(i).article_level()) for i in ids)


def _relevant(gold: Gold) -> Mapping[str, int]:
    rel = gold if isinstance(gold, Mapping) else dict.fromkeys(gold, 1)
    rel = {k: v for k, v in rel.items() if v > 0}
    if not rel:
        raise ValueError("gold must contain at least one relevant id")
    return rel


def recall_at_k(ranked: Sequence[str], gold: Gold, k: int) -> float:
    rel = _relevant(gold)
    return len(set(ranked[:k]) & rel.keys()) / len(rel)


def mrr_at_k(ranked: Sequence[str], gold: Gold, k: int) -> float:
    rel = _relevant(gold)
    for rank, doc in enumerate(ranked[:k], start=1):
        if doc in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gold: Gold, k: int) -> float:
    """nDCG with exponential gain ``2^rel - 1`` (equals plain binary nDCG for rel in {0,1})."""
    rel = _relevant(gold)
    dcg = sum(
        (2 ** rel.get(doc, 0) - 1) / math.log2(rank + 1)
        for rank, doc in enumerate(ranked[:k], start=1)
    )
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
    return dcg / idcg


def retrieval_scores(
    retrieved_ids: Sequence[str], gold_ids: Sequence[str], ks: Sequence[int] = (5, 10)
) -> dict[str, float]:
    """Article-level recall@k for each k, plus MRR@10 and nDCG@10."""
    ranked = to_article_level(retrieved_ids)
    gold = set(to_article_level(gold_ids))
    scores = {f"recall@{k}": recall_at_k(ranked, gold, k) for k in ks}
    scores["mrr@10"] = mrr_at_k(ranked, gold, 10)
    scores["ndcg@10"] = ndcg_at_k(ranked, gold, 10)
    return scores
