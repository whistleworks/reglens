"""Checks on glossary.json and xrefs.json produced by `make ingest`."""

from __future__ import annotations

import json
from typing import Any

import pytest

from reglens.config import get_settings
from reglens.ids import parse_id

pytestmark = pytest.mark.data


def _load(name: str) -> Any:
    path = get_settings().processed_dir / name
    if not path.exists():
        pytest.skip("run `make ingest` first")
    return json.loads(path.read_text())


def test_glossary_counts_and_terms() -> None:
    entries = _load("glossary.json")
    by_reg = {reg: [e for e in entries if e["regulation"] == reg] for reg in ("AIA", "GDPR")}
    # AIA art. 3: 68 original definitions + (14a), (14b) inserted by Reg. (EU) 2026/1744
    assert len(by_reg["AIA"]) == 70
    assert len(by_reg["GDPR"]) == 26
    for entry in entries:
        parse_id(entry["id"])
        assert entry["term_en"], entry["id"]
        assert entry["term_it"], entry["id"]
    terms = {e["id"]: (e["term_en"], e["term_it"]) for e in entries}
    assert terms["AIA:art:3:def:1"] == ("AI system", "sistema di IA")
    assert terms["GDPR:art:4:def:1"] == ("personal data", "dato personale")


def test_xrefs_are_valid_internal_ids() -> None:
    xrefs = _load("xrefs.json")
    corpus = json.loads((get_settings().processed_dir / "corpus_en.json").read_text())
    known = {
        unit["id"]
        for doc in corpus["regulations"]
        for kind in ("articles", "recitals", "annexes")
        for unit in doc[kind]
    }
    assert len(xrefs) > 300
    for source, targets in xrefs.items():
        parse_id(source)
        assert targets, source
        assert all(t in known for t in targets), source
    # spot checks
    assert "AIA:annex:III" in xrefs["AIA:art:6:par:2"]
    assert xrefs["GDPR:art:9:par:2"] == ["GDPR:art:89"]  # point (j): "Article 89(1)"
