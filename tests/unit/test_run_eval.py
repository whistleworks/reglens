from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evals.dataset import load_dataset
from evals.run_eval import (
    RetrievalConfig,
    RunResult,
    build_result,
    main,
    run_retrieval,
    write_result,
)
from reglens.retrieval.pipeline import RetrievalResult
from reglens.retrieval.qdrant import Hit

DATASET = Path(__file__).parents[1] / "fixtures" / "evals" / "mini.jsonl"
CONFIG = RetrievalConfig(name="fake", retriever="bm25", candidates=10, ks=[5, 10])


def hit(unit_id: str) -> Hit:
    article = ":".join(unit_id.split(":")[:3])
    return Hit(chunk_id=f"{unit_id}#en", unit_id=unit_id, article_id=article, score=1.0, payload={})


def fake_search(query: str, lang: str | None) -> RetrievalResult:
    timing = {"dense": 1.0, "total": 2.0}
    if "prohibited" in query:
        hits = [hit("AIA:art:5:par:1"), hit("AIA:art:5:par:2"), hit("AIA:art:6:par:1")]
        return RetrievalResult(hits=hits, latency_ms=timing, query_lang="en")
    if "FRIA" in query:  # GDPR art. 35 missed
        hits = [hit("AIA:art:26:par:1"), hit("AIA:art:27:par:1")]
        return RetrievalResult(hits=hits, latency_ms=timing, query_lang="it")
    raise TimeoutError("qdrant timeout")


def records(split: str = "dev") -> list:  # type: ignore[type-arg]
    return [r for r in load_dataset(DATASET) if r.split == split and r.has_retrieval_target]


def test_per_query_scores_and_article_projection() -> None:
    rows = run_retrieval(records(), fake_search, CONFIG)
    assert [r.id for r in rows] == ["q001", "q002"]
    q1, q2 = rows
    assert q1.retrieved_ids == ["AIA:art:5", "AIA:art:6"]
    assert q1.scores["recall@5"] == 1.0
    assert q2.scores["recall@5"] == 0.5
    assert q2.scores["mrr@10"] == 0.5


def test_failures_are_recorded_not_raised() -> None:
    test_records = records("test")
    rows = run_retrieval(test_records, fake_search, CONFIG)
    assert rows[0].error == "TimeoutError: qdrant timeout"
    assert rows[0].scores == {}


def test_result_document(tmp_path: Path) -> None:
    rows = run_retrieval(records(), fake_search, CONFIG)
    result = build_result(
        rows,
        config=CONFIG,
        split="dev",
        dataset_path=DATASET,
        n_skipped=1,
        git_sha="abc1234",
        model_ids={"sparse": "fake"},
        index_version="reglens_test",
        now=datetime(2026, 11, 9, 15, 30, tzinfo=UTC),
    )
    assert result.run_id == f"20261109-1530_abc1234_{CONFIG.config_hash()}_dev"
    assert result.metrics["recall@5"].value == 0.75
    assert result.metrics["recall@5"].n == 2
    low, high = result.metrics["recall@5"].ci95
    assert 0.5 <= low <= 0.75 <= high <= 1.0
    assert set(result.by_category) == {"single_hop", "multi_hop"}
    assert set(result.by_lang) == {"en", "it"}
    assert result.dataset_version.startswith("mini@")
    assert set(result.latency_ms) == {"dense", "total", "retrieval"}
    assert result.per_query[1].query_lang == "it"
    path = write_result(result, tmp_path)
    assert path.name == f"{result.run_id}.json"
    RunResult.model_validate(json.loads(path.read_text()))  # valid results JSON


def test_config_hash_changes_with_config() -> None:
    other = CONFIG.model_copy(update={"candidates": 20})
    assert CONFIG.config_hash() != other.config_hash()


def test_test_split_requires_final(tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("name: x\nretriever: bm25\n")
    assert main(["--split", "test", "--config", str(config), "--dataset", str(DATASET)]) == 2


def test_dataset_rejects_duplicates_and_bad_ids(tmp_path: Path) -> None:
    line = DATASET.read_text().splitlines()[0]
    dup = tmp_path / "dup.jsonl"
    dup.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(dup)
    bad = tmp_path / "bad.jsonl"
    bad.write_text(line.replace("AIA:art:5", "AIA:article:5") + "\n")
    with pytest.raises(ValueError, match="canonical"):
        load_dataset(bad)


def test_test_access_is_logged(tmp_path: Path) -> None:
    from evals.run_eval import log_test_access

    log_path = tmp_path / "test_access.log"
    log_test_access(Path("configs/x.yaml"), DATASET, log_path)
    log_test_access(Path("configs/y.yaml"), DATASET, log_path)
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [e["config"] for e in entries] == ["configs/x.yaml", "configs/y.yaml"]


def test_resolve_index_by_strategy_and_enrich() -> None:
    from evals.run_eval import resolve_index

    manifest = {
        "indexes": {
            "a": {
                "collection": "a",
                "strategy": "paragraph",
                "enrich": "none",
                "dense_model": "m",
                "created_at": "2026-11-01",
            },
            "b": {
                "collection": "b",
                "strategy": "paragraph",
                "enrich": "none",
                "dense_model": "m",
                "created_at": "2026-11-02",
            },
            "c": {
                "collection": "c",
                "strategy": "article",
                "enrich": "hierarchy",
                "dense_model": "m",
                "created_at": "2026-11-01",
            },
        }
    }
    cfg = RetrievalConfig(name="x", retriever="hybrid")
    assert resolve_index(cfg, manifest, "m")["collection"] == "b"  # newest wins
    cfg2 = cfg.model_copy(update={"strategy": "article", "enrich": "hierarchy"})
    assert resolve_index(cfg2, manifest, "m")["collection"] == "c"
    with pytest.raises(SystemExit, match="make index"):
        resolve_index(cfg.model_copy(update={"strategy": "fixed"}), manifest, "m")


def test_smoke_gate_logic() -> None:
    from evals.smoke import gate

    current = {"queries": ["q1"], "metrics": {"recall@5": {"value": 0.70}}}
    base = {"queries": ["q1"], "metrics": {"recall@5": {"value": 0.72}}}
    assert gate(current, base) == []  # within tolerance (0.03)
    worse = {"queries": ["q1"], "metrics": {"recall@5": {"value": 0.68}}}
    assert "recall@5" in gate(worse, base)[0]
    assert gate(current, None) == []
    changed = {"queries": ["q2"], "metrics": {"recall@5": {"value": 0.9}}}
    assert "query set changed" in gate(changed, base)[0]
