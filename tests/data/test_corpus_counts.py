"""Structural checks on the real corpus. Run with `make test-data` after `make ingest`.

Expected counts (verified by hand on 2026-11-09, see data/README.md):
- AI Act, consolidated 27.07.2026: 113 original articles + 6 inserted by Reg. (EU) 2026/1744
  (4a, 60a, 75a, 75b, 75c, 75d) = 119; 14 annexes (Annex XIV added by 2026/1744);
  180 recitals from the original OJ text.
- GDPR (OJ 2016): 99 articles, 173 recitals, no annexes.
"""

from __future__ import annotations

import pytest

from reglens.config import get_settings
from reglens.ingestion.parse import Corpus

pytestmark = pytest.mark.data

INSERTED_AIA_ARTICLES = {"4a", "60a", "75a", "75b", "75c", "75d"}


@pytest.fixture(scope="module")
def corpora() -> dict[str, Corpus]:
    processed = get_settings().processed_dir
    paths = {lang: processed / f"corpus_{lang}.json" for lang in ("en", "it")}
    if not all(p.exists() for p in paths.values()):
        pytest.skip("run `make ingest` first")
    return {lang: Corpus.model_validate_json(p.read_text()) for lang, p in paths.items()}


@pytest.mark.parametrize("lang", ["en", "it"])
def test_aia_counts(corpora: dict[str, Corpus], lang: str) -> None:
    aia = corpora[lang].regulations[0]
    assert aia.regulation == "AIA"
    numbers = [a.number for a in aia.articles]
    assert len(numbers) == 119
    assert {n for n in numbers if not n.isdigit()} == INSERTED_AIA_ARTICLES
    assert sorted(int(n) for n in numbers if n.isdigit()) == list(range(1, 114))
    assert [r.number for r in aia.recitals] == list(range(1, 181))
    assert len(aia.annexes) == 14
    assert aia.annexes[-1].id == "AIA:annex:XIV"


@pytest.mark.parametrize("lang", ["en", "it"])
def test_gdpr_counts(corpora: dict[str, Corpus], lang: str) -> None:
    gdpr = corpora[lang].regulations[1]
    assert gdpr.regulation == "GDPR"
    assert [a.number for a in gdpr.articles] == [str(i) for i in range(1, 100)]
    assert [r.number for r in gdpr.recitals] == list(range(1, 174))
    assert gdpr.annexes == []


def test_ids_aligned_between_languages(corpora: dict[str, Corpus]) -> None:
    def ids(corpus: Corpus) -> list[str]:
        out: list[str] = []
        for doc in corpus.regulations:
            for art in doc.articles:
                for par in art.paragraphs:
                    out.append(par.id)
                    out += [f"{par.id}:pt:{pt.label}" for pt in par.points]
            out += [r.id for r in doc.recitals]
            for annex in doc.annexes:
                out.append(annex.id)
                out += [f"{annex.id}:pt:{pt.label}" for pt in annex.points]
        return out

    en, it = ids(corpora["en"]), ids(corpora["it"])
    assert en == it
    assert len(en) == len(set(en))


@pytest.mark.parametrize("lang", ["en", "it"])
def test_no_empty_units(corpora: dict[str, Corpus], lang: str) -> None:
    for doc in corpora[lang].regulations:
        for art in doc.articles:
            assert art.title, art.id
            assert art.paragraphs, art.id
            assert all(p.text.strip() for p in art.paragraphs), art.id
        assert all(r.text.strip() for r in doc.recitals)
        assert all(a.text.strip() and a.title for a in doc.annexes)
