"""Offline ingestion pipeline: raw XHTML -> corpus, glossary, xrefs, chunks, manifest.

The manifest ``content_hash`` covers the output files and the chunking config, never
timestamps or the git sha, so two runs on the same sources give the same hash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from reglens.ingestion.chunk import Chunk, ChunkingConfig, TokenCounter, make_chunker
from reglens.ingestion.glossary import build_glossary
from reglens.ingestion.parse import Corpus, build_corpus
from reglens.ingestion.sources import LANGS, Lang
from reglens.ingestion.xrefs import build_xrefs
from reglens.observability.logging import get_logger

log = get_logger(__name__)

MANIFEST_SCHEMA_VERSION = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, text: str) -> str:
    data = text.encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def known_unit_ids(corpus: Corpus) -> set[str]:
    return {
        unit_id
        for doc in corpus.regulations
        for unit_id in (
            *(a.id for a in doc.articles),
            *(r.id for r in doc.recitals),
            *(a.id for a in doc.annexes),
        )
    }


def length_stats(values: list[int]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {
        "min": float(arr.min()),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "mean": round(float(arr.mean()), 2),
    }


def _histogram(
    values: list[int], edges: tuple[int, ...] = (64, 128, 256, 384, 512)
) -> dict[str, int]:
    out: dict[str, int] = {}
    low = 0
    for high in edges:
        out[f"{low}-{high - 1}"] = sum(low <= v < high for v in values)
        low = high
    out[f">={low}"] = sum(v >= low for v in values)
    return out


def _xref_agreement(xrefs: dict[Lang, dict[str, list[str]]]) -> float:
    pairs = {lang: {(s, t) for s, ts in x.items() for t in ts} for lang, x in xrefs.items()}
    union = pairs["en"] | pairs["it"]
    return round(len(pairs["en"] & pairs["it"]) / len(union), 4) if union else 1.0


def git_sha(default: str = "unknown") -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return default
    return out.stdout.strip() or default


def run_ingest(
    raw_dir: Path,
    processed_dir: Path,
    config: ChunkingConfig,
    count_tokens: TokenCounter,
    *,
    sources_lock: dict[str, Any],
    sha: str,
) -> dict[str, Any]:
    processed_dir.mkdir(parents=True, exist_ok=True)
    corpora: dict[Lang, Corpus] = {lang: build_corpus(raw_dir, lang) for lang in LANGS}
    files: dict[str, str] = {}
    for lang, corpus in corpora.items():
        files[f"corpus_{lang}.json"] = _write(
            processed_dir / f"corpus_{lang}.json", corpus.model_dump_json(indent=1) + "\n"
        )

    glossary = build_glossary(corpora["en"], corpora["it"])
    files["glossary.json"] = _write(
        processed_dir / "glossary.json", _json([e.model_dump() for e in glossary])
    )

    # Ids are identical across languages (tested), so the EN xrefs are the reference;
    # the IT extraction is computed only to report the agreement.
    known = known_unit_ids(corpora["en"])
    xrefs = {lang: build_xrefs(corpus, known) for lang, corpus in corpora.items()}
    files["xrefs.json"] = _write(processed_dir / "xrefs.json", _json(xrefs["en"]))

    chunker = make_chunker(config, count_tokens)
    chunks: list[Chunk] = [c for lang in LANGS for c in chunker.chunk(corpora[lang])]
    chunks_name = f"chunks_{config.strategy}.jsonl"
    files[chunks_name] = _write(
        processed_dir / chunks_name, "".join(c.model_dump_json() + "\n" for c in chunks)
    )

    lengths = [c.n_tokens for c in chunks]
    counts = {
        lang: {
            doc.regulation: {
                "articles": len(doc.articles),
                "recitals": len(doc.recitals),
                "annexes": len(doc.annexes),
            }
            for doc in corpus.regulations
        }
        for lang, corpus in corpora.items()
    }
    content_hash = sha256_bytes(
        json.dumps({"files": files, "chunking": config.model_dump()}, sort_keys=True).encode()
    )
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "content_hash": content_hash,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": sha,
        "sources": sources_lock,
        "chunking": config.model_dump(),
        "files": files,
        "counts": counts,
        "glossary_entries": len(glossary),
        "xrefs": {
            "citing_units": len(xrefs["en"]),
            "pairs": sum(len(t) for t in xrefs["en"].values()),
            "en_it_jaccard": _xref_agreement(xrefs),
        },
        "chunks": {
            "n": len(chunks),
            "by_lang": {lang: sum(c.lang == lang for c in chunks) for lang in LANGS},
            "by_type": {
                t: sum(c.type == t for c in chunks) for t in ("article", "recital", "annex")
            },
            "split_units": len({c.unit_id + c.lang for c in chunks if "~" in c.id}),
            "tokens": length_stats(lengths),
            "tokens_histogram": _histogram(lengths),
        },
        "index": None,  # filled by `make index`
    }
    (processed_dir / "manifest.json").write_text(_json(manifest), encoding="utf-8")
    log.info(
        "ingest.done",
        content_hash=content_hash[:12],
        chunks=len(chunks),
        max_tokens=manifest["chunks"]["tokens"]["max"],
    )
    return manifest
