"""BEIR SciFact sanity check for our BM25 (FastEmbed term weights + Qdrant IDF).

Published reference: BM25 nDCG@10 = 0.665 on SciFact (Thakur et al., 2021, "BEIR: A
Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models",
arXiv:2104.08663v4, Table 2, p. 7; verified 2026-11-09). Tolerance: +/- 0.02.

    python -m evals.beir_sanity            # Qdrant from QDRANT_URL (docker compose)
    python -m evals.beir_sanity --memory   # in-process Qdrant (no Docker)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from evals.metrics.retrieval import ndcg_at_k, recall_at_k
from evals.metrics.stats import bootstrap_ci
from reglens.config import REPO_ROOT, get_settings
from reglens.observability.logging import configure_logging, get_logger

log = get_logger(__name__)

PUBLISHED_NDCG10 = 0.665
TOLERANCE = 0.02
CORPUS_REPO = "BeIR/scifact"
QRELS_REPO = "BeIR/scifact-qrels"
COLLECTION = "beir_scifact_bm25"

Qrels = dict[str, dict[str, int]]


def parse_qrels(lines: Sequence[str]) -> Qrels:
    """BEIR qrels TSV: ``query-id<TAB>corpus-id<TAB>score`` with a header row."""
    qrels: Qrels = defaultdict(dict)
    for row in csv.reader(lines, delimiter="\t"):
        if not row or row[0] == "query-id":
            continue
        qrels[row[0]][row[1]] = int(row[2])
    return dict(qrels)


def evaluate(
    queries: Mapping[str, str], qrels: Qrels, search: Callable[[str], list[str]], k: int = 10
) -> dict[str, Any]:
    ndcgs, recalls, latencies = [], [], []
    for qid in sorted(qrels):
        if not any(v > 0 for v in qrels[qid].values()):
            continue
        started = time.perf_counter()
        ranked = search(queries[qid])
        latencies.append((time.perf_counter() - started) * 1000)
        ndcgs.append(ndcg_at_k(ranked, qrels[qid], k))
        recalls.append(recall_at_k(ranked, qrels[qid], 100))
    return {
        "ndcg@10": {
            "value": round(sum(ndcgs) / len(ndcgs), 4),
            "ci95": bootstrap_ci(ndcgs),
            "n": len(ndcgs),
        },
        "recall@100": {
            "value": round(sum(recalls) / len(recalls), 4),
            "ci95": bootstrap_ci(recalls),
            "n": len(recalls),
        },
        "latency_ms_p50": round(sorted(latencies)[len(latencies) // 2], 2),
    }


def _download(
    with_title: bool = True,
) -> tuple[dict[str, str], dict[str, str], Qrels, dict[str, str]]:
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    revisions = {
        repo: api.dataset_info(repo).sha or "unknown" for repo in (CORPUS_REPO, QRELS_REPO)
    }
    corpus_path = hf_hub_download(
        CORPUS_REPO,
        "corpus/corpus-00000-of-00001.parquet",
        repo_type="dataset",
        revision=revisions[CORPUS_REPO],
    )
    queries_path = hf_hub_download(
        CORPUS_REPO,
        "queries/queries-00000-of-00001.parquet",
        repo_type="dataset",
        revision=revisions[CORPUS_REPO],
    )
    qrels_path = hf_hub_download(
        QRELS_REPO, "test.tsv", repo_type="dataset", revision=revisions[QRELS_REPO]
    )
    corpus = {
        str(row["_id"]): (f"{row['title']} {row['text']}" if with_title else row["text"]).strip()
        for row in pq.read_table(corpus_path).to_pylist()
    }
    queries = {str(row["_id"]): str(row["text"]) for row in pq.read_table(queries_path).to_pylist()}
    qrels = parse_qrels(Path(qrels_path).read_text().splitlines())
    return corpus, queries, qrels, revisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="beir_sanity")
    parser.add_argument("--memory", action="store_true", help="in-process Qdrant instead of server")
    # Diagnostic variants: they explain the gap to the published value; the official
    # sanity check is the default configuration and is never tuned on these runs.
    parser.add_argument("--no-title", action="store_true", help="diagnostic: index text only")
    parser.add_argument("--no-stem", action="store_true", help="diagnostic: disable stemming")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    from reglens.ingestion.embed import FastEmbedBM25
    from reglens.ingestion.pipeline import git_sha
    from reglens.retrieval.qdrant import make_client

    corpus, queries, qrels, revisions = _download(with_title=not args.no_title)
    variant = "-".join(v for v, on in (("notitle", args.no_title), ("nostem", args.no_stem)) if on)
    log.info("beir.loaded", docs=len(corpus), queries=len(qrels))

    client = QdrantClient(":memory:") if args.memory else make_client(settings)
    bm25 = FastEmbedBM25(settings.sparse_model, disable_stemmer=args.no_stem)
    doc_ids = list(corpus)
    avg_len = bm25.fit_avg_len({"en": [corpus[d] for d in doc_ids]})["en"]
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config={},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    started = time.perf_counter()
    for start in range(0, len(doc_ids), 256):
        batch = doc_ids[start : start + 256]
        vectors = bm25.embed_documents([corpus[d] for d in batch], "en")
        client.upsert(
            COLLECTION,
            points=[
                models.PointStruct(
                    id=start + i,
                    vector={"bm25": models.SparseVector(indices=v.indices, values=v.values)},
                    payload={"doc_id": doc_id},
                )
                for i, (doc_id, v) in enumerate(zip(batch, vectors, strict=True))
            ],
        )
    index_seconds = round(time.perf_counter() - started, 1)

    def search(query: str) -> list[str]:
        vec = bm25.embed_query(query, "en")
        response = client.query_points(
            COLLECTION,
            query=models.SparseVector(indices=vec.indices, values=vec.values),
            using="bm25",
            limit=100,
            with_payload=True,
        )
        return [str((p.payload or {})["doc_id"]) for p in response.points]

    metrics = evaluate(queries, qrels, search)
    ndcg = metrics["ndcg@10"]["value"]
    within = abs(ndcg - PUBLISHED_NDCG10) <= TOLERANCE
    now = datetime.now(UTC)
    sha = git_sha()
    result = {
        "run_id": f"{now:%Y%m%d-%H%M}_{sha}_beir-scifact" + (f"-{variant}" if variant else ""),
        "variant": variant or "official",
        "timestamp": now.isoformat(timespec="seconds"),
        "git_sha": sha,
        "benchmark": "BEIR SciFact (test qrels)",
        "dataset_revisions": revisions,
        "backend": "qdrant-memory" if args.memory else f"qdrant-server {settings.qdrant_url}",
        "method": {
            "sparse_model": bm25.name,
            "stemmer": "none" if args.no_stem else "snowball english",
            "k1": 1.2,
            "b": 0.75,
            "avg_len": avg_len,
            "idf": "Qdrant Modifier.IDF",
            "doc_text": "text" if args.no_title else "title + ' ' + text",
        },
        "docs": len(corpus),
        "index_seconds": index_seconds,
        "metrics": metrics,
        "reference": {
            "ndcg@10": PUBLISHED_NDCG10,
            "source": "Thakur et al. 2021, arXiv:2104.08663v4, Table 2 (BM25, SciFact)",
            "tolerance": TOLERANCE,
        },
        "delta": round(ndcg - PUBLISHED_NDCG10, 4),
        "within_tolerance": within,
    }
    out = REPO_ROOT / "evals" / "results" / f"{result['run_id']}.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    log.info("beir.done", ndcg10=ndcg, delta=result["delta"], within=within, path=str(out))
    if variant:
        return 0  # diagnostics never fail: only the official configuration is gated
    return 0 if within else 1


if __name__ == "__main__":
    sys.exit(main())
