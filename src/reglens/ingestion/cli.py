"""Ingestion CLI: ``python -m reglens.ingestion.cli {fetch,ingest,index}``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from reglens.config import REPO_ROOT, get_settings
from reglens.ingestion.chunk import ChunkingConfig, hf_token_counter
from reglens.ingestion.fetch import Fetcher, FetchError, default_client
from reglens.ingestion.pipeline import git_sha, run_ingest
from reglens.observability.logging import configure_logging, get_logger

log = get_logger(__name__)


def cmd_fetch(update_lock: bool) -> int:
    settings = get_settings()
    with default_client(settings.http_user_agent, settings.http_timeout_s) as client:
        fetcher = Fetcher(
            settings.raw_dir,
            settings.data_dir / "sources.lock.json",
            client,
            update_lock=update_lock,
        )
        try:
            files = fetcher.fetch_all()
        except FetchError as exc:
            log.error("fetch.failed", error=str(exc))
            return 2
    log.info("fetch.done", files=len(files), downloaded=sum(not f.from_cache for f in files))
    return 0


def cmd_parse() -> int:
    settings = get_settings()
    configs = ChunkingConfig.all_from_yaml(REPO_ROOT / "configs" / "ingest.yaml")
    lock = json.loads((settings.data_dir / "sources.lock.json").read_text())
    sha = settings.git_sha if settings.git_sha != "unknown" else git_sha()
    run_ingest(
        settings.raw_dir,
        settings.processed_dir,
        configs,
        hf_token_counter(configs[0].tokenizer),
        sources_lock=lock,
        sha=sha,
    )
    return 0


def cmd_index(strategy: str, enrich: str, recreate: bool) -> int:
    from reglens.ingestion.chunk import Chunk
    from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
    from reglens.ingestion.index import collection_name, index_chunks
    from reglens.ingestion.pipeline import chunks_filename
    from reglens.retrieval.qdrant import make_client

    settings = get_settings()
    manifest_path = settings.processed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    chunks_file = chunks_filename(strategy)
    if chunks_file not in manifest["files"]:
        log.error("index.unknown_strategy", strategy=strategy, available=list(manifest["chunks"]))
        return 2
    chunks = [
        Chunk.model_validate_json(line)
        for line in (settings.processed_dir / chunks_file).read_text().splitlines()
    ]
    chunks_sha = manifest["files"][chunks_file]
    name = settings.qdrant_collection or collection_name(
        chunks_sha, settings.embedding_model, strategy, enrich
    )
    info = index_chunks(
        make_client(settings),
        name,
        chunks,
        FastEmbedDense(settings.embedding_model),
        FastEmbedBM25(settings.sparse_model),
        enrich=enrich,  # type: ignore[arg-type]
        recreate=recreate,
    )
    info.update(
        strategy=strategy,
        chunks_sha256=chunks_sha,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    manifest.setdefault("indexes", {})[name] = info
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    log.info("index.done", **{k: v for k, v in info.items() if k != "bm25_avg_len"})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reglens-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "ingest"):
        p = sub.add_parser(name)
        p.add_argument("--update-lock", action="store_true", help="accept changed source hashes")
    index = sub.add_parser("index")
    index.add_argument("--strategy", default="paragraph", choices=["paragraph", "article", "fixed"])
    index.add_argument("--enrich", default="none", choices=["none", "hierarchy"])
    index.add_argument("--recreate", action="store_true", help="drop the collection if it exists")
    args = parser.parse_args(argv)

    configure_logging(get_settings().log_level)
    if args.command == "fetch":
        return cmd_fetch(args.update_lock)
    if args.command == "ingest":
        return cmd_fetch(args.update_lock) or cmd_parse()
    if args.command == "index":
        return cmd_index(args.strategy, args.enrich, args.recreate)
    return 1  # pragma: no cover - argparse enforces the choices


if __name__ == "__main__":
    sys.exit(main())
