"""Checks on the real chunks and manifest. Run with `make test-data` after `make ingest`."""

from __future__ import annotations

import json
from typing import Any

import pytest

from reglens.config import REPO_ROOT, get_settings
from reglens.ids import parse_id
from reglens.ingestion.chunk import Chunk, ChunkingConfig, hf_token_counter

pytestmark = pytest.mark.data

E5_MAX_TOKENS = 512


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    path = get_settings().processed_dir / "manifest.json"
    if not path.exists():
        pytest.skip("run `make ingest` first")
    data: dict[str, Any] = json.loads(path.read_text())
    return data


STRATEGIES = ["paragraph", "paragraph_defs", "article", "fixed"]


@pytest.fixture(scope="module", params=STRATEGIES)
def chunks(request: pytest.FixtureRequest, manifest: dict[str, Any]) -> list[Chunk]:
    path = get_settings().processed_dir / f"chunks_{request.param}.jsonl"
    return [Chunk.model_validate_json(line) for line in path.read_text().splitlines()]


def test_chunks_unique_and_non_empty(chunks: list[Chunk]) -> None:
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.text.strip() for c in chunks)
    for chunk in chunks:
        parse_id(chunk.unit_id)
        assert parse_id(chunk.article_id) == parse_id(chunk.unit_id).article_level()


def test_chunks_fit_the_embedding_model(chunks: list[Chunk]) -> None:
    config = ChunkingConfig.from_yaml(REPO_ROOT / "configs" / "ingest.yaml")
    count = hf_token_counter(config.tokenizer)
    # re-count with the real tokenizer, including the e5 "passage: " prefix
    worst = max(count(f"passage: {c.text}") for c in chunks)
    assert worst <= E5_MAX_TOKENS


def test_every_unit_is_covered_in_both_languages(manifest: dict[str, Any]) -> None:
    path = get_settings().processed_dir / "chunks_paragraph.jsonl"
    chunks = [Chunk.model_validate_json(line) for line in path.read_text().splitlines()]
    corpus = json.loads((get_settings().processed_dir / "corpus_en.json").read_text())
    units = {
        p["id"] for doc in corpus["regulations"] for a in doc["articles"] for p in a["paragraphs"]
    } | {u["id"] for doc in corpus["regulations"] for u in doc["recitals"] + doc["annexes"]}
    for lang in ("en", "it"):
        assert {c.unit_id for c in chunks if c.lang == lang} == units, lang


def test_manifest_matches_files(manifest: dict[str, Any]) -> None:
    import hashlib

    processed = get_settings().processed_dir
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((processed / name).read_bytes()).hexdigest() == digest, name
    for strategy, stats in manifest["chunks"].items():
        lines = (processed / f"chunks_{strategy}.jsonl").read_text().splitlines()
        assert stats["n"] == len(lines)
        assert stats["tokens"]["max"] <= manifest["chunking"][strategy]["max_tokens"]
