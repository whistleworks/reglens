from __future__ import annotations

import pytest

from evals.beir_sanity import evaluate, parse_qrels


def test_parse_qrels_skips_header() -> None:
    lines = ["query-id\tcorpus-id\tscore", "1\td1\t1", "1\td2\t1", "3\td9\t1"]
    assert parse_qrels(lines) == {"1": {"d1": 1, "d2": 1}, "3": {"d9": 1}}


def test_evaluate_with_fake_search() -> None:
    qrels = {"1": {"d1": 1}, "2": {"d5": 1}, "3": {"d7": 0}}  # q3 has no relevant doc: skipped
    queries = {"1": "a", "2": "b", "3": "c"}
    ranked = {"a": ["d1", "x"], "b": ["x", "d5"], "c": ["d7"]}
    result = evaluate(queries, qrels, lambda q: ranked[q])
    assert result["ndcg@10"]["n"] == 2
    # q1: 1.0; q2: hit at rank 2 -> 1/log2(3) = 0.6309
    assert result["ndcg@10"]["value"] == pytest.approx((1 + 0.6309) / 2, abs=1e-4)
    assert result["recall@100"]["value"] == 1.0
