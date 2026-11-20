from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.compare import compare, to_markdown
from evals.report import describe, table


def run(name: str, scores: list[float], dataset: str = "v0@abc") -> dict[str, Any]:
    return {
        "config": {"name": name, "retriever": "hybrid", "strategy": "paragraph", "rerank": True},
        "dataset_version": dataset,
        "metrics": {
            "recall@5": {"value": sum(scores) / len(scores), "ci95": [0.1, 0.9], "n": len(scores)}
        },
        "latency_ms": {"retrieval": {"p50": 120.0, "p95": 300.0, "p99": 400.0}},
        "per_query": [
            {"id": f"q{i:03d}", "scores": {"recall@5": s}, "error": None}
            for i, s in enumerate(scores)
        ],
    }


def test_compare_paired_delta() -> None:
    a = run("a", [0.0] * 10 + [1.0] * 10)
    b = run("b", [1.0] * 20)
    result = compare(a, b)["recall@5"]
    assert (result["a"], result["b"], result["n"]) == (0.5, 1.0, 20)
    assert result["delta"] == 0.5
    assert result["ci95"][0] > 0
    md = to_markdown("a", "b", compare(a, b))
    assert "▲ +0.5000" in md


def test_compare_refuses_different_datasets() -> None:
    with pytest.raises(ValueError, match="different datasets"):
        compare(run("a", [1.0]), run("b", [1.0], dataset="v1@def"))


def test_report_table(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps(run("hybrid_rerank", [1.0, 0.0])))
    text = table([path])
    assert "`hybrid_rerank` | hybrid · paragraph · +rerank | 0.500 [0.10–0.90]" in text
    assert "| 2 | 120 / 300 |" in text
    assert describe({"retriever": "dense", "strategy": "article", "enrich": "hierarchy"}) == (
        "dense · article · +hierarchy"
    )
