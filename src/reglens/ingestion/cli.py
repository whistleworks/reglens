"""Ingestion CLI: ``python -m reglens.ingestion.cli {fetch,ingest,index}``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reglens.config import get_settings
from reglens.ingestion.fetch import Fetcher, FetchError, default_client
from reglens.ingestion.glossary import build_glossary
from reglens.ingestion.parse import Corpus, build_corpus
from reglens.ingestion.sources import LANGS
from reglens.ingestion.xrefs import build_xrefs
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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def cmd_parse() -> int:
    settings = get_settings()
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    corpora: dict[str, Corpus] = {}
    for lang in LANGS:
        corpus = build_corpus(settings.raw_dir, lang)
        corpora[lang] = corpus
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

    glossary = build_glossary(corpora["en"], corpora["it"])
    _write_json(settings.processed_dir / "glossary.json", [e.model_dump() for e in glossary])

    # Ids are identical across languages (tested), so xrefs are extracted from the EN text.
    en = corpora["en"]
    known = {
        unit_id
        for d in en.regulations
        for unit_id in (
            *(a.id for a in d.articles),
            *(r.id for r in d.recitals),
            *(a.id for a in d.annexes),
        )
    }
    xrefs = build_xrefs(en, known)
    _write_json(settings.processed_dir / "xrefs.json", xrefs)
    log.info("parse.glossary_xrefs", definitions=len(glossary), citing_units=len(xrefs))
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
