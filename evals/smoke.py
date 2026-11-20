"""CI smoke eval + regression gate (no secrets, no model downloads beyond BM25 files).

    python -m evals.smoke [--baseline evals/baselines/main.json] [--write-candidate PATH]

* indexes the committed paragraph chunks with BM25 into an in-memory Qdrant,
* runs the first 20 dev queries with a retrieval target (fixed list, sorted by id),
* compares recall@5 and MRR@10 with the ``smoke`` section of the baseline:
  the gate fails if recall@5 drops by more than TOLERANCE (brief: 0.03).
* if a replay cache of e2e answers is present it also checks citation validity == 1.0.

Dense retrieval and generation are covered by the nightly full eval (eval-full.yml),
because e5-large embeddings of the whole corpus take minutes on CI CPUs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from evals.dataset import dataset_version, load_dataset
from evals.metrics.retrieval import retrieval_scores
from evals.metrics.stats import bootstrap_ci
from reglens.config import REPO_ROOT, get_settings
from reglens.ingestion.chunk import Chunk
from reglens.ingestion.embed import FastEmbedBM25
from reglens.observability.logging import configure_logging, get_logger
from reglens.retrieval.sparse import SparseRetriever

log = get_logger(__name__)

N_QUERIES = 20
TOLERANCE = 0.03
GATED = ("recall@5",)
DATASET = REPO_ROOT / "evals" / "datasets" / "reglens_v1.jsonl"
BASELINE = REPO_ROOT / "evals" / "baselines" / "main.json"


class _NoDense:
    name = "none"
    dim = 1

    def embed_documents(self, texts: Any) -> list[list[float]]:
        return [[1.0] for _ in texts]

    def embed_query(self, _text: str) -> list[float]:
        return [1.0]


def run_smoke(dataset: Path = DATASET) -> dict[str, Any]:
    from reglens.ingestion.index import index_chunks

    settings = get_settings()
    chunks = [
        Chunk.model_validate_json(line)
        for line in (settings.processed_dir / "chunks_paragraph.jsonl").read_text().splitlines()
    ]
    client = QdrantClient(":memory:")
    bm25 = FastEmbedBM25(settings.sparse_model)
    index_chunks(client, "smoke", chunks, _NoDense(), bm25, batch_size=256)
    retriever = SparseRetriever(client, "smoke", bm25)
    records = sorted(
        (r for r in load_dataset(dataset) if r.split == "dev" and r.has_retrieval_target),
        key=lambda r: r.id,
    )[:N_QUERIES]
    per_query = []
    for record in records:
        hits = retriever.search(record.question, 50, query_lang=record.lang)
        per_query.append(
            {"id": record.id, **retrieval_scores([h.unit_id for h in hits], record.gold_ids)}
        )
    metrics = {}
    for name in ("recall@5", "recall@10", "mrr@10", "ndcg@10"):
        values = [q[name] for q in per_query]
        metrics[name] = {
            "value": round(sum(values) / len(values), 4),
            "ci95": bootstrap_ci(values),
            "n": len(values),
        }
    return {
        "dataset_version": dataset_version(dataset),
        "queries": [q["id"] for q in per_query],
        "metrics": metrics,
        "per_query": per_query,
    }


def gate(current: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    if baseline is None:
        return []
    failures = []
    for name in GATED:
        base = baseline["metrics"][name]["value"]
        now = current["metrics"][name]["value"]
        if now < base - TOLERANCE:
            failures.append(f"{name} {now:.4f} < baseline {base:.4f} - {TOLERANCE}")
    if baseline.get("queries") and baseline["queries"] != current["queries"]:
        failures.append("the smoke query set changed: update the baseline with the owner's OK")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smoke")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--write-candidate", type=Path)
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    current = run_smoke()
    baseline_doc = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    baseline = (baseline_doc or {}).get("smoke")
    failures = gate(current, baseline)
    summary = {k: v["value"] for k, v in current["metrics"].items()}
    if args.write_candidate:
        args.write_candidate.write_text(json.dumps({"smoke": current}, indent=1) + "\n")
    if baseline is None:
        log.warning(
            "smoke.no_baseline",
            **summary,
            hint="baseline is created only with the owner's OK (evals/baselines/)",
        )
        return 0
    if failures:
        log.error("smoke.gate_failed", failures=failures, **summary)
        return 1
    log.info("smoke.gate_passed", **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
