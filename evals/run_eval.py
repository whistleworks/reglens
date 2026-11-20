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
from reglens.retrieval.pipeline import RetrievalResult

log = get_logger(__name__)

RESULTS_DIR = REPO_ROOT / "evals" / "results"
DEFAULT_DATASET = REPO_ROOT / "evals" / "datasets" / "reglens_v0.jsonl"
RESULTS_SCHEMA_VERSION = 1

TEST_ACCESS_LOG = RESULTS_DIR / "test_access.log"

# (query, query_lang or None to auto-detect) -> retrieval result with per-stage latency
SearchFn = Callable[[str, Lang | None], RetrievalResult]


class RetrievalConfig(BaseModel):
    name: str
    retriever: Literal["bm25", "dense", "hybrid"]
    strategy: Literal["paragraph", "article", "fixed"] = "paragraph"
    enrich: Literal["none", "hierarchy"] = "none"
    rerank: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3-int8"
    rerank_top_n: int = 20
    query_lang: Literal["detect", "dataset"] = Field(
        default="detect", description="BM25 stemmer from a detector (as in production) or gold"
    )
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
    query_lang: str | None = None
    category: str
    retrieved_ids: list[str]
    retrieved_chunks: list[str]
    gold_ids: list[str]
    scores: dict[str, float]
    latency_ms: float
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
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
        result = RetrievalResult(hits=[])
        try:
            lang = record.lang if config.query_lang == "dataset" else None
            result = search(record.question, lang)
        except Exception as exc:  # an eval run must survive single-query failures
            error = f"{type(exc).__name__}: {exc}"
            log.warning("eval.query_failed", id=record.id, error=error)
        latency = (time.perf_counter() - started) * 1000
        hits = result.hits
        chunk_units = [h.unit_id for h in hits]
        rows.append(
            PerQuery(
                id=record.id,
                lang=record.lang,
                query_lang=None if error else result.query_lang,
                category=record.category,
                retrieved_ids=to_article_level(chunk_units)[: max(config.ks)],
                retrieved_chunks=[h.chunk_id for h in hits[:20]],
                gold_ids=list(record.gold_ids),
                scores={} if error else retrieval_scores(chunk_units, record.gold_ids, config.ks),
                latency_ms=round(latency, 2),
                stage_latency_ms=result.latency_ms,
                error=error,
            )
        )
    return rows


def _stage_latencies(rows: Sequence[PerQuery]) -> dict[str, dict[str, float]]:
    stages: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for stage, value in row.stage_latency_ms.items():
            stages[stage].append(value)
    out = {stage: percentiles(values) for stage, values in sorted(stages.items())}
    if rows:
        out["retrieval"] = percentiles([r.latency_ms for r in rows])
    return out


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
        latency_ms=_stage_latencies(rows),
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


def resolve_index(
    config: RetrievalConfig, manifest: dict[str, Any], dense_model: str
) -> dict[str, Any]:
    """The manifest index built from ``config.strategy``/``config.enrich`` (or ``collection``)."""
    indexes: dict[str, dict[str, Any]] = manifest.get("indexes") or {}
    if config.collection:
        if config.collection not in indexes:
            raise SystemExit(f"collection {config.collection} not in the data manifest")
        return indexes[config.collection]
    matches = [
        info
        for info in indexes.values()
        if info.get("strategy") == config.strategy
        and info.get("enrich") == config.enrich
        and info.get("dense_model") == dense_model
    ]
    if not matches:
        raise SystemExit(
            f"no index for strategy={config.strategy} enrich={config.enrich}: run "
            f"`make index STRATEGY={config.strategy} ENRICH={config.enrich}`"
        )
    return max(matches, key=lambda info: str(info.get("created_at", "")))


def _real_search(config: RetrievalConfig) -> tuple[SearchFn, dict[str, str], str]:
    from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
    from reglens.retrieval.dense import DenseRetriever
    from reglens.retrieval.pipeline import RetrievalPipeline
    from reglens.retrieval.qdrant import make_client
    from reglens.retrieval.rerank import FastEmbedReranker
    from reglens.retrieval.sparse import SparseRetriever

    settings = get_settings()
    manifest = json.loads((settings.processed_dir / "manifest.json").read_text())
    index = resolve_index(config, manifest, settings.embedding_model)
    collection = str(index["collection"])
    client = make_client(settings)
    model_ids: dict[str, str] = {}
    dense = sparse = None
    if config.retriever in ("dense", "hybrid"):
        dense = DenseRetriever(client, collection, FastEmbedDense(index["dense_model"]))
        model_ids["dense"] = index["dense_model"]
    if config.retriever in ("bm25", "hybrid"):
        sparse = SparseRetriever(client, collection, FastEmbedBM25(index["sparse_model"]))
        model_ids["sparse"] = index["sparse_model"]
    reranker = FastEmbedReranker(config.rerank_model) if config.rerank else None
    if reranker is not None:
        model_ids["reranker"] = config.rerank_model
    pipeline = RetrievalPipeline(
        config.retriever,
        dense=dense,
        sparse=sparse,
        reranker=reranker,
        candidates=config.candidates,
        rerank_top_n=config.rerank_top_n,
    )
    return (lambda q, lang: pipeline.search(q, query_lang=lang), model_ids, collection)


def log_test_access(config: Path, dataset: Path, log_path: Path = TEST_ACCESS_LOG) -> None:
    """Append-only record of every use of the test split (checked by the eval-auditor)."""
    from reglens.ingestion.pipeline import git_sha

    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "config": str(config),
            "dataset": str(dataset),
        }
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    log.warning("eval.test_split_accessed", log=str(log_path))


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
    if args.split == "test":
        log_test_access(args.config, args.dataset)

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
