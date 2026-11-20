"""Retrieval metrics on hand-computed cases (values worked out on paper, see comments)."""

from __future__ import annotations

import math

import pytest

from evals.metrics.retrieval import (
    dedup,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    retrieval_scores,
    to_article_level,
)

# ranked: A  x  B  y  C        gold: {A, B, C, D}
RANKED = ["A", "x", "B", "y", "C"]
GOLD = {"A", "B", "C", "D"}


def test_recall() -> None:
    assert recall_at_k(RANKED, GOLD, 1) == 0.25  # A
    assert recall_at_k(RANKED, GOLD, 3) == 0.5  # A, B
    assert recall_at_k(RANKED, GOLD, 5) == 0.75  # A, B, C (D never retrieved)
    assert recall_at_k([], GOLD, 5) == 0.0


def test_mrr() -> None:
    assert mrr_at_k(RANKED, GOLD, 10) == 1.0
    assert mrr_at_k(["x", "y", "B"], GOLD, 10) == pytest.approx(1 / 3)
    assert mrr_at_k(["x", "y", "B"], GOLD, 2) == 0.0  # first hit is beyond the cutoff


def test_ndcg_binary() -> None:
    # DCG@5 = 1/log2(2) + 1/log2(4) + 1/log2(6) = 1 + 0.5 + 0.386853
    # IDCG@5 with 4 relevant = 1 + 1/log2(3) + 1/log2(4) + 1/log2(5) = 1 + 0.630930 + 0.5 + 0.430677
    dcg = 1 + 0.5 + 1 / math.log2(6)
    idcg = 1 + 1 / math.log2(3) + 0.5 + 1 / math.log2(5)
    assert ndcg_at_k(RANKED, GOLD, 5) == pytest.approx(dcg / idcg)
    # = 1.886853 / 2.561606 = 0.7366
    assert ndcg_at_k(RANKED, GOLD, 5) == pytest.approx(0.7366, abs=1e-4)


def test_ndcg_perfect_and_zero() -> None:
    assert ndcg_at_k(["A", "B"], {"A", "B"}, 10) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "y"], {"A"}, 10) == 0.0


def test_ndcg_graded() -> None:
    # gains 2^rel - 1; ranked [b (rel 1), a (rel 2)]
    # DCG = 1/1 + 3/log2(3); ideal DCG = 3/1 + 1/log2(3)
    qrels = {"a": 2, "b": 1}
    dcg = 1 + 3 / math.log2(3)
    idcg = 3 + 1 / math.log2(3)
    assert ndcg_at_k(["b", "a"], qrels, 10) == pytest.approx(dcg / idcg)


def test_dedup_and_article_projection() -> None:
    assert dedup(["A", "A", "B", "A", "C"]) == ["A", "B", "C"]
    chunks = ["AIA:art:6:par:2", "AIA:art:6:par:3", "AIA:annex:III", "GDPR:art:4:pt:11"]
    assert to_article_level(chunks) == ["AIA:art:6", "AIA:annex:III", "GDPR:art:4"]


def test_gold_at_paragraph_level_counts_as_its_article() -> None:
    # gold ids may be finer than article level; retrieval is evaluated at article level
    scores = retrieval_scores(["AIA:art:6:par:1", "AIA:art:7"], ["AIA:art:6:par:2"], ks=(1, 5))
    assert scores["recall@1"] == 1.0
    assert scores["mrr@10"] == 1.0


def test_retrieval_scores_keys() -> None:
    scores = retrieval_scores(["AIA:art:1", "AIA:art:2"], ["AIA:art:2"], ks=(5, 10))
    assert set(scores) == {"recall@5", "recall@10", "mrr@10", "ndcg@10"}


def test_empty_gold_is_rejected() -> None:
    with pytest.raises(ValueError, match="gold"):
        recall_at_k(["A"], set(), 5)
