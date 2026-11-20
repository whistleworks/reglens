from __future__ import annotations

from pathlib import Path

import pytest

from reglens.ingestion.glossary import build_glossary, term_of
from reglens.ingestion.parse import Point, build_corpus

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eurlex"


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("(1) ‘AI system’ means a machine-based system", "AI system"),
        ("1) «sistema di IA»: un sistema automatizzato", "sistema di IA"),
        (
            "14 bis) «microimprese, piccole e medie imprese» o «PMI»: ...",
            "microimprese, piccole e medie imprese",
        ),
        (
            "25) «servizio della società dell'informazione»: il servizio",
            "servizio della società dell'informazione",
        ),
    ],
)
def test_term_extraction(text: str, term: str) -> None:
    assert term_of(Point(label="1", raw_label="(1)", text=text)) == term


def test_term_missing_raises() -> None:
    with pytest.raises(ValueError, match="no quoted term"):
        term_of(Point(label="1", raw_label="(1)", text="(1) something without quotes"))


def test_glossary_from_gdpr_fixture() -> None:
    en, it = build_corpus(FIXTURES, "en"), build_corpus(FIXTURES, "it")
    # the AIA fixture has no Article 3: build only the GDPR definitions
    entries = build_glossary(en, it, {"GDPR": "4"})
    assert len(entries) == 26
    consent = next(e for e in entries if e.number == "11")
    assert consent.id == "GDPR:art:4:def:11"
    assert (consent.term_en, consent.term_it) == ("consent", "consenso dell'interessato")
    assert consent.definition_en.startswith("(11) ‘consent’ of the data subject means")
