"""Evaluation runner. M1 implements the retrieval stage.

    python -m evals.run_eval --split dev --stage retrieval --config configs/bm25.yaml

Writes ``evals/results/{YYYYMMDD-HHMM}_{git_sha}_{config_hash}_{split}.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from evals.dataset import EvalRecord, Split, dataset_version, load_dataset
from evals.metrics.retrieval import retrieval_scores, to_article_level
from evals.metrics.stats import bootstrap_ci, percentiles
from reglens.config import REPO_ROOT, get_settings
from reglens.ingestion.sources import Lang
from reglens.observability.logging import configure_logging, get_logger
from reglens.retrieval.qdrant import Hit

log = get_logger(__name__)

RESULTS_DIR = REPO_ROOT / "evals" / "results"
DEFAULT_DATASET = REPO_ROOT / "evals" / "datasets" / "reglens_v0.jsonl"
RESULTS_SCHEMA_VERSION = 1

# (query, k, query_lang) -> ranked hits
SearchFn = Callable[[str, int, Lang], list[Hit]]


class RetrievalConfig(BaseModel):
    name: str
    retriever: Literal["bm25", "dense"]
    candidates: int = Field(
        default=50, description="Chunks retrieved before projecting to article level"
    )
    ks: list[int] = Field(default_factory=lambda: [5, 10])
    collection: str | None = Field(default=None, description="None = from data manifest")

    @classmethod
    def from_yaml(cls, path: Path) -> RetrievalConfig:
        return cls.model_validate(yaml.safe_load(path.read_text()))

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()[:8]


class MetricValue(BaseModel):
    value: float
    ci95: tuple[float, float]
    n: int


class PerQuery(BaseModel):
    id: str
    lang: str
    category: str
    retrieved_ids: list[str]
    retrieved_chunks: list[str]
    gold_ids: list[str]
    scores: dict[str, float]
    latency_ms: float
    cost_usd: float = 0.0
    error: str | None = None


class RunResult(BaseModel):
    schema_version: int
    run_id: str
    git_sha: str
    timestamp: str
    stage: Literal["retrieval"]
    dataset_version: str
    split: Split
    config: dict[str, Any]
    config_hash: str
    model_ids: dict[str, str]
    prompt_versions: dict[str, str]
    index_version: str
    metrics: dict[str, MetricValue]
    by_category: dict[str, dict[str, MetricValue]]
    by_lang: dict[str, dict[str, MetricValue]]
    latency_ms: dict[str, dict[str, float]]
    cost_usd: dict[str, float]
    n_queries: int
    n_skipped: int
    per_query: list[PerQuery]


def _aggregate(rows: Sequence[PerQuery]) -> dict[str, MetricValue]:
    ok = [r for r in rows if r.error is None]
    if not ok:
        return {}
    return {
        name: MetricValue(
            value=round(sum(values) / len(values), 4),
            ci95=bootstrap_ci(values),
            n=len(values),
        )
        for name in ok[0].scores
        if (values := [r.scores[name] for r in ok])
    }


def _grouped(rows: Sequence[PerQuery], key: str) -> dict[str, dict[str, MetricValue]]:
    groups: dict[str, list[PerQuery]] = defaultdict(list)
    for row in rows:
        groups[getattr(row, key)].append(row)
    return {name: _aggregate(group) for name, group in sorted(groups.items())}


def run_retrieval(
    records: Sequence[EvalRecord], search: SearchFn, config: RetrievalConfig
) -> list[PerQuery]:
    rows: list[PerQuery] = []
    for record in records:
        started = time.perf_counter()
        error: str | None = None
        hits: list[Hit] = []
        try:
            hits = search(record.question, config.candidates, record.lang)
        except Exception as exc:  # an eval run must survive single-query failures
            error = f"{type(exc).__name__}: {exc}"
            log.warning("eval.query_failed", id=record.id, error=error)
        latency = (time.perf_counter() - started) * 1000
        chunk_units = [h.unit_id for h in hits]
        rows.append(
            PerQuery(
                id=record.id,
                lang=record.lang,
                category=record.category,
                retrieved_ids=to_article_level(chunk_units)[: max(config.ks)],
                retrieved_chunks=[h.chunk_id for h in hits[:20]],
                gold_ids=list(record.gold_ids),
                scores={} if error else retrieval_scores(chunk_units, record.gold_ids, config.ks),
                latency_ms=round(latency, 2),
                error=error,
            )
        )
    return rows


def build_result(
    rows: list[PerQuery],
    *,
    config: RetrievalConfig,
    split: Split,
    dataset_path: Path,
    n_skipped: int,
    git_sha: str,
    model_ids: dict[str, str],
    index_version: str,
    now: datetime | None = None,
) -> RunResult:
    now = now or datetime.now(UTC)
    config_hash = config.config_hash()
    return RunResult(
        schema_version=RESULTS_SCHEMA_VERSION,
        run_id=f"{now:%Y%m%d-%H%M}_{git_sha}_{config_hash}_{split}",
        git_sha=git_sha,
        timestamp=now.isoformat(timespec="seconds"),
        stage="retrieval",
        dataset_version=dataset_version(dataset_path),
        split=split,
        config=config.model_dump(),
        config_hash=config_hash,
        model_ids=model_ids,
        prompt_versions={},
        index_version=index_version,
        metrics=_aggregate(rows),
        by_category=_grouped(rows, "category"),
        by_lang=_grouped(rows, "lang"),
        latency_ms={"retrieval": percentiles([r.latency_ms for r in rows])} if rows else {},
        cost_usd={"total": 0.0, "per_query": 0.0},
        n_queries=len(rows),
        n_skipped=n_skipped,
        per_query=rows,
    )


def write_result(result: RunResult, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return path


def _real_search(config: RetrievalConfig) -> tuple[SearchFn, dict[str, str], str]:
    from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
    from reglens.retrieval.dense import DenseRetriever
    from reglens.retrieval.qdrant import make_client
    from reglens.retrieval.sparse import SparseRetriever

    settings = get_settings()
    manifest = json.loads((settings.processed_dir / "manifest.json").read_text())
    index = manifest.get("index") or {}
    collection = config.collection or settings.qdrant_collection or index.get("collection")
    if not collection:
        raise SystemExit("no Qdrant collection: run `make index` first")
    client = make_client(settings)
    if config.retriever == "bm25":
        sparse = SparseRetriever(
            client, collection, FastEmbedBM25(index.get("sparse_model", settings.sparse_model))
        )
        return (
            lambda q, k, lang: sparse.search(q, k, query_lang=lang),
            {"sparse": sparse.encoder.name},
            collection,
        )
    dense = DenseRetriever(
        client, collection, FastEmbedDense(index.get("dense_model", settings.embedding_model))
    )
    # e5 is multilingual: the query language is not needed for dense search
    return (lambda q, k, _lang: dense.search(q, k), {"dense": dense.encoder.name}, collection)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--stage", choices=["retrieval"], default="retrieval")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--final", action="store_true", help="required for --split test (M6)")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)

    if args.split == "test" and not args.final:
        log.error("eval.test_split_refused", reason="the test split needs --final (M6 only)")
        return 2

    from reglens.ingestion.pipeline import git_sha

    config = RetrievalConfig.from_yaml(args.config)
    records = [r for r in load_dataset(args.dataset) if r.split == args.split]
    targets = [r for r in records if r.has_retrieval_target]
    unreviewed = [r.id for r in targets if not r.reviewed]
    if unreviewed:
        log.warning("eval.unreviewed_records", n=len(unreviewed), ids=unreviewed[:10])
    search, model_ids, index_version = _real_search(config)
    rows = run_retrieval(targets, search, config)
    result = build_result(
        rows,
        config=config,
        split=args.split,
        dataset_path=args.dataset,
        n_skipped=len(records) - len(targets),
        git_sha=git_sha(),
        model_ids=model_ids,
        index_version=index_version,
    )
    path = write_result(result)
    log.info(
        "eval.done",
        path=str(path.relative_to(REPO_ROOT)),
        **{name: m.value for name, m in result.metrics.items()},
        errors=sum(r.error is not None for r in rows),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
