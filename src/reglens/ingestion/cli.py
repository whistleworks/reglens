"""Ingestion CLI: ``python -m reglens.ingestion.cli {fetch,ingest,index}``."""

from __future__ import annotations

import argparse
import sys

from reglens.config import get_settings
from reglens.ingestion.fetch import Fetcher, FetchError, default_client
from reglens.ingestion.parse import build_corpus
from reglens.ingestion.sources import LANGS
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
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        corpus = build_corpus(settings.raw_dir, lang)
        path = settings.processed_dir / f"corpus_{lang}.json"
        path.write_text(corpus.model_dump_json(indent=1) + "\n", encoding="utf-8")
        log.info(
            "parse.done",
            lang=lang,
            path=str(path),
            **{
                f"{doc.regulation.lower()}_{kind}": len(getattr(doc, kind))
                for doc in corpus.regulations
                for kind in ("articles", "recitals", "annexes")
            },
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reglens-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "ingest"):
        p = sub.add_parser(name)
        p.add_argument("--update-lock", action="store_true", help="accept changed source hashes")
    args = parser.parse_args(argv)

    configure_logging(get_settings().log_level)
    if args.command == "fetch":
        return cmd_fetch(args.update_lock)
    if args.command == "ingest":
        return cmd_fetch(args.update_lock) or cmd_parse()
    return 1  # pragma: no cover - argparse enforces the choices


if __name__ == "__main__":
    sys.exit(main())
