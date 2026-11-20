from __future__ import annotations

from pathlib import Path

import pytest

from reglens.ingestion.parse import Article, Corpus, build_corpus, normalize_label

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eurlex"


@pytest.fixture(scope="module")
def corpora() -> dict[str, Corpus]:
    return {lang: build_corpus(FIXTURES, lang) for lang in ("en", "it")}


def article(corpus: Corpus, regulation: str, number: str) -> Article:
    doc = next(r for r in corpus.regulations if r.regulation == regulation)
    return next(a for a in doc.articles if a.number == number)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(a)", "a"),
        ("a)", "a"),
        ("(14a)", "14a"),
        ("14 bis)", "14a"),
        ("14\xa0ter)", "14b"),
        ("1 quater.", "1c"),
        ("1 quinquies.", "1d"),
        ("6\xa0bis.", "6a"),
        ("1.", "1"),
        ("(ba)", "ba"),
        ("(iv)", "iv"),
        ("‘5.", None),
        ("«5.", None),
        ("—", None),
        ("Article", None),
        ("", None),
    ],
)
def test_normalize_label(raw: str, expected: str | None) -> None:
    assert normalize_label(raw) == expected


def test_consolidated_article_structure(corpora: dict[str, Corpus]) -> None:
    art6 = article(corpora["en"], "AIA", "6")
    assert art6.id == "AIA:art:6"
    assert art6.heading == "Article 6"
    assert art6.title == "Classification rules for high-risk AI systems"
    assert (art6.chapter, art6.chapter_title) == ("III", "HIGH-RISK AI SYSTEMS")
    assert (art6.section, art6.section_title) == ("1", "Classification of AI systems as high-risk")
    numbers = [p.number for p in art6.paragraphs]
    # paragraphs 1a-1c were inserted by Reg. (EU) 2026/1744
    assert numbers == ["1", "1a", "1b", "1c", "2", "3", "4", "5", "6", "7", "8"]
    par1 = art6.paragraphs[0]
    assert par1.id == "AIA:art:6:par:1"
    assert [p.label for p in par1.points] == ["a", "b"]
    assert par1.points[0].text.startswith("(a) the AI system is intended to be used")
    # the second subparagraph of par. 3 (a sibling element in the HTML) stays in par. 3
    par3 = art6.paragraphs[5]
    assert "The first subparagraph shall apply" in par3.text
    assert [p.label for p in par3.points] == ["a", "b", "c", "d"]


def test_amendment_markers_and_footnotes_are_removed(corpora: dict[str, Corpus]) -> None:
    for corpus in corpora.values():
        for doc in corpus.regulations:
            for art in doc.articles:
                assert "▼" not in art.text
                assert "►" not in art.text
                assert "()" not in art.text


def test_inserted_article_has_letter_suffix_in_both_languages(
    corpora: dict[str, Corpus],
) -> None:
    assert article(corpora["en"], "AIA", "4a").heading == "Article 4a"
    assert article(corpora["it"], "AIA", "4a").heading == "Articolo 4 bis"


def test_exponents_are_rendered(corpora: dict[str, Corpus]) -> None:
    assert "10^25" in article(corpora["en"], "AIA", "51").text


def test_quoted_paragraphs_of_amended_acts_are_content(corpora: dict[str, Corpus]) -> None:
    for lang in ("en", "it"):
        art105 = article(corpora[lang], "AIA", "105")
        assert [p.number for p in art105.paragraphs] == [None]
        assert "5. " in art105.paragraphs[0].text


def test_oj_paragraphs_points_and_typo_in_source(corpora: dict[str, Corpus]) -> None:
    for lang in ("en", "it"):
        art6 = article(corpora[lang], "GDPR", "6")
        assert art6.paragraphs[0].id == "GDPR:art:6:par:1"
        assert [p.label for p in art6.paragraphs[0].points] == ["a", "b", "c", "d", "e", "f"]
        assert not art6.paragraphs[0].text.startswith("1.")
        # IT art. 38(4) is printed "4   " without the dot: the div id still gives the number
        art38 = article(corpora[lang], "GDPR", "38")
        assert [p.number for p in art38.paragraphs] == ["1", "2", "3", "4", "5", "6"]
        assert not art38.paragraphs[3].text.startswith("4")


def test_definitions_in_both_oj_layouts(corpora: dict[str, Corpus]) -> None:
    # EN prints definitions as two-column tables, IT as inline "1)   «...»" paragraphs
    for lang, fragment in (("en", "‘consent’"), ("it", "«consenso dell'interessato»")):
        art4 = article(corpora[lang], "GDPR", "4")
        points = art4.paragraphs[0].points
        assert len(points) == 26
        assert [p.label for p in points[:3]] == ["1", "2", "3"]
        assert fragment in points[10].text


def test_recitals_and_annexes(corpora: dict[str, Corpus]) -> None:
    aia = corpora["en"].regulations[0]
    assert [r.id for r in aia.recitals] == ["AIA:rec:1", "AIA:rec:53"]
    assert not aia.recitals[0].text.startswith("(1)")
    annex = aia.annexes[0]
    assert (annex.id, annex.title) == (
        "AIA:annex:III",
        "High-risk AI systems referred to in Article 6(2)",
    )
    assert [p.label for p in annex.points] == [str(i) for i in range(1, 9)]
    assert "remote biometric identification" in annex.points[0].text


def test_same_ids_in_both_languages(corpora: dict[str, Corpus]) -> None:
    def ids(corpus: Corpus) -> list[str]:
        out = []
        for doc in corpus.regulations:
            for art in doc.articles:
                out += [p.id for p in art.paragraphs]
                out += [f"{p.id}:{pt.label}" for p in art.paragraphs for pt in p.points]
            out += [r.id for r in doc.recitals] + [a.id for a in doc.annexes]
        return out

    assert ids(corpora["en"]) == ids(corpora["it"])
