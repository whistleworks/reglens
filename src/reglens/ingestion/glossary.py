"""Glossary of legal definitions: AI Act Article 3 and GDPR Article 4, in EN and IT."""

from __future__ import annotations

import re

from pydantic import BaseModel

from reglens.ids import Regulation, article_id
from reglens.ingestion.parse import Corpus, Point

DEFINITION_ARTICLES: dict[Regulation, str] = {"AIA": "3", "GDPR": "4"}

# EN: (1) ‘AI system’ means ...   IT: 1) «sistema di IA»: ...
# The label may carry a latin suffix: "14 bis) «PMI»: ..."
# Straight apostrophes occur inside Italian terms ("dell'informazione"), so each opening
# quote only closes on its own counterpart.
_TERM_RE = re.compile(
    r"^\S+(?:\s(?:bis|ter|quater|quinquies|sexies))?\)?\s+"
    r"(?:‘(?P<t1>[^’]+)’|«(?P<t2>[^»]+)»|“(?P<t3>[^”]+)”|\"(?P<t4>[^\"]+)\")"
)


class GlossaryEntry(BaseModel):
    id: str
    regulation: Regulation
    number: str
    term_en: str
    term_it: str
    definition_en: str
    definition_it: str


def term_of(point: Point) -> str:
    match = _TERM_RE.match(point.text)
    if match is None:
        raise ValueError(f"no quoted term at the start of definition {point.label!r}")
    term = next(g for g in match.groups() if g is not None)
    return term.strip()


def _definition_points(corpus: Corpus, regulation: Regulation, article_number: str) -> list[Point]:
    doc = next(d for d in corpus.regulations if d.regulation == regulation)
    article = next(a for a in doc.articles if a.number == article_number)
    return [point for paragraph in article.paragraphs for point in paragraph.points]


def build_glossary(
    en: Corpus,
    it: Corpus,
    definition_articles: dict[Regulation, str] = DEFINITION_ARTICLES,
) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for regulation, number in definition_articles.items():
        en_points = _definition_points(en, regulation, number)
        it_points = {p.label: p for p in _definition_points(it, regulation, number)}
        for point in en_points:
            it_point = it_points[point.label]
            entries.append(
                GlossaryEntry(
                    id=str(article_id(regulation, number, definition=point.label)),
                    regulation=regulation,
                    number=point.label,
                    term_en=term_of(point),
                    term_it=term_of(it_point),
                    definition_en=point.text,
                    definition_it=it_point.text,
                )
            )
    return entries
