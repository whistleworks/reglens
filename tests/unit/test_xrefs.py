from __future__ import annotations

import pytest

from reglens.ids import Regulation
from reglens.ingestion.parse import Article, Corpus, Paragraph, RegulationDoc
from reglens.ingestion.xrefs import build_xrefs, extract_refs

# 30 real fragments from the corpus (source paragraph in the first column), checked by hand.
REAL_CASES: list[tuple[str, str, Regulation, str, list[str]]] = [
    # --- EN ---
    (
        "AIA:art:75c:par:5",
        "en",
        "AIA",
        "ordered by a decision pursuant to Article 75a(4);",
        ["AIA:art:75a:par:4"],
    ),
    (
        "AIA:art:42:par:3",
        "en",
        "AIA",
        "the conditions laid down in Article 12(1) of that Regulation are fulfilled",
        [],
    ),
    (
        "GDPR:art:83:par:2",
        "en",
        "GDPR",
        "where measures referred to in Article 58(2) have",
        ["GDPR:art:58:par:2"],
    ),
    (
        "AIA:art:11:par:2",
        "en",
        "AIA",
        "legislation listed in Section A of Annex I is placed",
        ["AIA:annex:I"],
    ),
    (
        "GDPR:art:43:par:3",
        "en",
        "GDPR",
        "competent pursuant to Article 55 or 56 or by the Board pursuant to Article 63.",
        ["GDPR:art:55", "GDPR:art:56", "GDPR:art:63"],
    ),
    (
        "GDPR:art:58:par:1",
        "en",
        "GDPR",
        "certifications issued pursuant to Article 42(7);",
        ["GDPR:art:42:par:7"],
    ),
    (
        "AIA:art:56:par:2",
        "en",
        "AIA",
        "the obligations provided for in Articles 53 and 55,",
        ["AIA:art:53", "AIA:art:55"],
    ),
    (
        "AIA:art:23:par:2",
        "en",
        "AIA",
        "presents a risk within the meaning of Article 79(1), the",
        ["AIA:art:79:par:1"],
    ),
    (
        "AIA:art:111:par:1",
        "en",
        "AIA",
        "Without prejudice to the application of Article 5 as referred to in Article 113(3), "
        "point (a), AI systems",
        ["AIA:art:5", "AIA:art:113:par:3:pt:a"],
    ),
    (
        "AIA:art:2:par:13",
        "en",
        "AIA",
        "referred to in Article 6(1), the application of specific requirements or obligations "
        "laid down in Articles 9 to 15 and 17 to 25 may be limited",
        [
            "AIA:art:6:par:1",
            *[f"AIA:art:{n}" for n in range(9, 16)],
            *[f"AIA:art:{n}" for n in range(17, 26)],
        ],
    ),
    (
        "AIA:art:42:par:3",
        "en",
        "AIA",
        "the cybersecurity requirements set out in Article 15 of this Regulation.",
        ["AIA:art:15"],
    ),
    (
        "AIA:rec:14",
        "en",
        "AIA",
        "as defined in Article 4, point (14) of Regulation (EU) 2016/679, Article 3, point (18) "
        "of Regulation (EU) 2018/1725",
        ["GDPR:art:4:pt:14"],
    ),
    (
        "AIA:art:6:par:2",
        "en",
        "AIA",
        "AI systems referred to in Annex III shall be considered",
        ["AIA:annex:III"],
    ),
    (
        "AIA:art:6:par:3",
        "en",
        "AIA",
        "profiling of natural persons within the meaning of Article 4, point (4), of Regulation "
        "(EU) 2016/679;",
        ["GDPR:art:4:pt:4"],
    ),
    (
        "AIA:art:3",
        "en",
        "AIA",
        "as referred to in Article 5(1), point (h)",
        ["AIA:art:5:par:1:pt:h"],
    ),
    (
        "AIA:art:40:par:2",
        "en",
        "AIA",
        "in accordance with Article 10 of Regulation (EU) No 1025/2012",
        [],
    ),
    ("AIA:art:111:par:2", "en", "AIA", "the obligations referred to in Article 16 TFEU", []),
    # --- IT ---
    (
        "AIA:art:14:par:5",
        "it",
        "AIA",
        "per i sistemi di IA ad alto rischio di cui all'allegato III, punto 1, lettera a), le",
        ["AIA:annex:III:pt:1"],
    ),
    (
        "GDPR:art:57:par:1",
        "it",
        "GDPR",
        "sui trattamenti di cui all'articolo 36, paragrafo 2;",
        ["GDPR:art:36:par:2"],
    ),
    (
        "AIA:art:30:par:3",
        "it",
        "AIA",
        "un certificato di accreditamento di cui all'articolo 29, paragrafo 2, l'autorità",
        ["AIA:art:29:par:2"],
    ),
    (
        "GDPR:art:58:par:2",
        "it",
        "GDPR",
        "la certificazione rilasciata a norma degli articoli 42 e 43,",
        ["GDPR:art:42", "GDPR:art:43"],
    ),
    (
        "GDPR:art:58:par:3",
        "it",
        "GDPR",
        "gli accordi amministrativi di cui all'articolo 46, paragrafo 3, lettera b);",
        ["GDPR:art:46:par:3:pt:b"],
    ),
    (
        "AIA:art:11:par:3",
        "it",
        "AIA",
        "conformemente all'articolo 97 al fine di modificare l'allegato IV ove necessario",
        ["AIA:art:97", "AIA:annex:IV"],
    ),
    (
        "AIA:art:2:par:13",
        "it",
        "AIA",
        "di cui agli articoli da 9 a 15 e da 17 a 25 può essere limitata",
        [*[f"AIA:art:{n}" for n in range(9, 16)], *[f"AIA:art:{n}" for n in range(17, 26)]],
    ),
    (
        "AIA:art:42:par:3",
        "it",
        "AIA",
        "le condizioni di cui all'articolo 12, paragrafo 1, di tale regolamento, tali sistemi",
        [],
    ),
    (
        "AIA:rec:14",
        "it",
        "AIA",
        "all'articolo 4, punto 14, del regolamento (UE) 2016/679, all'articolo 3, punto 18, del "
        "regolamento (UE) 2018/1725",
        ["GDPR:art:4:pt:14"],
    ),
    (
        "AIA:art:36:par:1",
        "it",
        "AIA",
        "lo strumento elettronico di notifica di cui all'articolo 30, paragrafo 2.",
        ["AIA:art:30:par:2"],
    ),
    (
        "AIA:art:2:par:13",
        "it",
        "AIA",
        "la normativa di armonizzazione dell'Unione elencata "
        "nell'allegato I, sezione A, stabilisce",
        ["AIA:annex:I"],
    ),
    ("AIA:art:6:par:1", "it", "AIA", "articolo 4 bis", ["AIA:art:4a"]),
    ("AIA:art:47", "it", "AIA", "di cui all'articolo 10 della direttiva (UE) 2016/680", []),
]


@pytest.mark.parametrize(("unit", "lang", "regulation", "text", "expected"), REAL_CASES)
def test_real_references(
    unit: str, lang: str, regulation: Regulation, text: str, expected: list[str]
) -> None:
    assert [str(ref) for ref in extract_refs(text, lang, regulation)] == expected, unit


def test_thirty_real_cases() -> None:
    assert len(REAL_CASES) == 30


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("Articles 102 to 104", "en", ["AIA:art:102", "AIA:art:103", "AIA:art:104"]),
        ("Article 5(1)(h)", "en", ["AIA:art:5:par:1:pt:h"]),
        ("point 4 of Annex III", "en", ["AIA:annex:III:pt:4"]),
        ("Annex III, point 4", "en", ["AIA:annex:III:pt:4"]),
        ("punto 4 dell'allegato III", "it", ["AIA:annex:III:pt:4"]),
        ("Article 8 of the Charter", "en", []),
        ("paragraph 2 of this Article", "en", []),
        ("Article 6 and Article 6(1)", "en", ["AIA:art:6", "AIA:art:6:par:1"]),
        ("Article 6 and again Article 6", "en", ["AIA:art:6"]),
    ],
)
def test_edge_cases(text: str, lang: str, expected: list[str]) -> None:
    assert [str(ref) for ref in extract_refs(text, lang, "AIA")] == expected


def _corpus(articles: list[Article]) -> Corpus:
    return Corpus(
        lang="en",
        regulations=[RegulationDoc(regulation="AIA", lang="en", celex=[], articles=articles)],
    )


def _article(number: str, title: str, text: str) -> Article:
    return Article(
        id=f"AIA:art:{number}",
        number=number,
        heading=f"Article {number}",
        title=title,
        paragraphs=[Paragraph(id=f"AIA:art:{number}:par:1", number="1", text=text)],
    )


def test_build_xrefs_projects_filters_and_skips_amending_articles() -> None:
    corpus = _corpus(
        [
            _article(
                "6", "Classification", "Annex III and Article 7(2) and Article 6(1) and Article 999"
            ),
            _article("7", "Amendments to Annex III", "Article 6"),
            _article("108", "Amendment to Regulation (EU) 2018/1139", "in Article 43, ..."),
        ]
    )
    known = {"AIA:art:6", "AIA:art:7", "AIA:art:43", "AIA:annex:III"}
    assert build_xrefs(corpus, known) == {
        # self-reference (6 -> 6(1)) and unknown article 999 dropped; targets at article level
        "AIA:art:6:par:1": ["AIA:art:7", "AIA:annex:III"],
        "AIA:art:7:par:1": ["AIA:art:6"],
    }
