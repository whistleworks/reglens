from __future__ import annotations

import json
from pathlib import Path

import pytest

from reglens.ingestion.chunk import (
    ChunkingConfig,
    ParagraphChunker,
    eurlex_url,
    split_to_budget,
)
from reglens.ingestion.parse import build_corpus
from reglens.ingestion.pipeline import run_ingest

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eurlex"


def words(text: str) -> int:
    """Deterministic stand-in for the model tokenizer: one token per word."""
    return len(text.split())


@pytest.mark.parametrize("budget", [5, 8, 50])
def test_split_respects_budget_and_keeps_all_words(budget: int) -> None:
    text = "one two three four.\nfive six seven eight nine ten; eleven twelve\nthirteen"
    parts = split_to_budget(text, budget, words)
    assert all(words(p) <= budget for p in parts)
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())


def test_split_does_not_touch_short_text() -> None:
    assert split_to_budget("a b c", 10, words) == ["a b c"]


def test_split_hard_splits_a_single_overlong_sentence() -> None:
    parts = split_to_budget(" ".join(["w"] * 25), 10, words)
    assert [words(p) for p in parts] == [10, 10, 5]


def test_eurlex_url_points_to_the_right_version() -> None:
    assert eurlex_url("AIA", "article", "it", "art_6") == (
        "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:02024R1689-20260727#art_6"
    )
    assert eurlex_url("AIA", "recital", "en", "rct_53").endswith("CELEX:32024R1689#rct_53")
    assert eurlex_url("GDPR", "article", "en", "art_4").endswith("CELEX:32016R0679#art_4")


@pytest.fixture(scope="module")
def chunks_en() -> list:  # type: ignore[type-arg]
    corpus = build_corpus(FIXTURES, "en")
    return ParagraphChunker(ChunkingConfig(max_tokens=120), words).chunk(corpus)


def test_paragraph_chunks_metadata(chunks_en: list) -> None:  # type: ignore[type-arg]
    by_id = {c.id: c for c in chunks_en}
    chunk = by_id["AIA:art:6:par:1a#en"]
    assert chunk.unit_id == "AIA:art:6:par:1a"
    assert chunk.article_id == "AIA:art:6"
    assert (chunk.regulation, chunk.lang, chunk.type) == ("AIA", "en", "article")
    assert (chunk.article, chunk.paragraph) == ("6", "1a")
    assert chunk.path == (
        "AI Act > Chapter III HIGH-RISK AI SYSTEMS > Section 1 Classification of AI systems "
        "as high-risk > Article 6 Classification rules for high-risk AI systems > par. 1a"
    )
    assert chunk.url_eurlex.endswith("#art_6")
    recital = by_id["GDPR:rec:1#en"]
    assert (recital.type, recital.article_id) == ("recital", "GDPR:rec:1")


def test_chunks_are_unique_non_empty_and_within_budget(chunks_en: list) -> None:  # type: ignore[type-arg]
    ids = [c.id for c in chunks_en]
    assert len(ids) == len(set(ids))
    assert all(c.text.strip() for c in chunks_en)
    assert all(c.n_tokens <= 120 for c in chunks_en)


def test_overlong_units_are_split_with_part_suffix(chunks_en: list) -> None:  # type: ignore[type-arg]
    # AIA art. 3 (70 definitions in one unnumbered paragraph) cannot fit in 120 words
    parts = [c for c in chunks_en if c.unit_id == "AIA:art:3"]
    assert len(parts) > 1
    assert [c.id for c in parts[:2]] == ["AIA:art:3#en~0", "AIA:art:3#en~1"]


def test_no_text_is_lost(chunks_en: list) -> None:  # type: ignore[type-arg]
    corpus = build_corpus(FIXTURES, "en")
    source = " ".join(
        p.text for doc in corpus.regulations for a in doc.articles for p in a.paragraphs
    )
    chunked = " ".join(c.text for c in chunks_en if c.type == "article")
    assert chunked.split() == source.split()


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    config = ChunkingConfig(max_tokens=200)
    lock = {"aia_oj_en": {"sha256": "x"}}
    first = run_ingest(FIXTURES, tmp_path / "a", config, words, sources_lock=lock, sha="s1")
    second = run_ingest(FIXTURES, tmp_path / "b", config, words, sources_lock=lock, sha="s2")
    assert first["content_hash"] == second["content_hash"]
    for name in first["files"]:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text())
    assert manifest["chunks"]["n"] == first["chunks"]["n"] > 0
    assert manifest["chunks"]["tokens"]["max"] <= 200
    assert manifest["glossary_entries"] == 26 + 70


def test_config_change_changes_hash(tmp_path: Path) -> None:
    a = run_ingest(
        FIXTURES, tmp_path / "a", ChunkingConfig(max_tokens=200), words, sources_lock={}, sha="s"
    )
    b = run_ingest(
        FIXTURES, tmp_path / "b", ChunkingConfig(max_tokens=100), words, sources_lock={}, sha="s"
    )
    assert a["content_hash"] != b["content_hash"]


def test_config_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "ingest.yaml"
    path.write_text("chunking:\n  strategy: paragraph\n  max_tokens: 300\n")
    assert ChunkingConfig.from_yaml(path).max_tokens == 300


def test_labels_follow_the_chunk_language() -> None:
    chunks_it = ParagraphChunker(ChunkingConfig(max_tokens=120), words).chunk(
        build_corpus(FIXTURES, "it")
    )
    by_id = {c.id: c for c in chunks_it}
    assert by_id["GDPR:rec:1#it"].title == "Considerando 1"
    assert by_id["AIA:annex:III#it~0"].title.startswith("Allegato III:")
    assert " > Capo III " in by_id["AIA:art:6:par:1a#it"].path
