"""Article Store: the structured corpus in memory, for exact access by canonical id.

Backs the agent tools ``get_article``, ``get_definition`` and ``follow_references`` and
the citation validator (does the id exist? is the quoted text really in the source?).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from reglens.ids import CanonicalId, InvalidIdError, parse_id
from reglens.ingestion.glossary import GlossaryEntry
from reglens.ingestion.parse import Corpus
from reglens.ingestion.sources import LANGS, Lang

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, NFKC, unify quotes/apostrophes and collapse whitespace (for quote checks)."""
    text = unicodedata.normalize("NFKC", text).lower()
    for src, dst in (("’", "'"), ("‘", "'"), ("«", '"'), ("»", '"'), ("“", '"'), ("”", '"')):
        text = text.replace(src, dst)
    return _WS.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class Unit:
    id: str
    lang: Lang
    title: str
    text: str


class ArticleStore:
    def __init__(
        self,
        corpora: dict[Lang, Corpus],
        glossary: list[GlossaryEntry],
        xrefs: dict[str, list[str]],
    ) -> None:
        self._units: dict[tuple[str, Lang], Unit] = {}
        for lang, corpus in corpora.items():
            for doc in corpus.regulations:
                for art in doc.articles:
                    title = f"{art.heading} {art.title}".strip()
                    self._add(art.id, lang, title, art.text)
                    for par in art.paragraphs:
                        self._add(par.id, lang, title, par.text)
                        for pt in par.points:
                            self._add(f"{par.id}:pt:{pt.label}", lang, title, pt.text)
                for rec in doc.recitals:
                    self._add(rec.id, lang, f"({rec.number})", rec.text)
                for annex in doc.annexes:
                    self._add(annex.id, lang, annex.title, annex.text)
                    for pt in annex.points:
                        self._add(f"{annex.id}:pt:{pt.label}", lang, annex.title, pt.text)
        self.glossary = glossary
        for entry in glossary:
            self._add(entry.id, "en", entry.term_en, entry.definition_en)
            self._add(entry.id, "it", entry.term_it, entry.definition_it)
        self.xrefs = xrefs
        self._incoming: dict[str, list[str]] = {}
        for source, targets in xrefs.items():
            src_article = str(parse_id(source).article_level())
            for target in targets:
                self._incoming.setdefault(target, [])
                if src_article not in self._incoming[target]:
                    self._incoming[target].append(src_article)

    def _add(self, unit_id: str, lang: Lang, title: str, text: str) -> None:
        self._units[(unit_id, lang)] = Unit(unit_id, lang, title, text)

    @classmethod
    def from_dir(cls, processed: Path) -> ArticleStore:
        corpora = {
            lang: Corpus.model_validate_json((processed / f"corpus_{lang}.json").read_text())
            for lang in LANGS
        }
        glossary = [
            GlossaryEntry.model_validate(e)
            for e in json.loads((processed / "glossary.json").read_text())
        ]
        xrefs = json.loads((processed / "xrefs.json").read_text())
        return cls(corpora, glossary, xrefs)

    def exists(self, unit_id: str) -> bool:
        return (unit_id, "en") in self._units

    def get(self, unit_id: str, lang: Lang = "en") -> Unit | None:
        """Exact unit, or the closest existing ancestor (e.g. a point merged into its paragraph)."""
        try:
            cid = parse_id(unit_id)
        except InvalidIdError:
            return None
        node: CanonicalId | None = cid
        while node is not None:
            unit = self._units.get((str(node), lang))
            if unit is not None:
                return unit
            node = node.parent()
        return None

    def contains_quote(self, unit_id: str, quote: str) -> bool:
        """True if ``quote`` appears (normalised) in the unit text in either language."""
        needle = normalize(quote)
        if not needle:
            return True
        for lang in LANGS:
            unit = self.get(unit_id, lang)
            if unit is not None and needle in normalize(unit.text):
                return True
        return False

    def find_definitions(self, term: str, limit: int = 3) -> list[GlossaryEntry]:
        needle = normalize(term)
        exact = [e for e in self.glossary if needle in (normalize(e.term_en), normalize(e.term_it))]
        if exact:
            return exact[:limit]
        partial = [
            e
            for e in self.glossary
            if needle in normalize(e.term_en) or needle in normalize(e.term_it)
        ]
        return partial[:limit]

    def references(self, article_id: str) -> dict[str, list[str]]:
        """Outgoing and incoming article-level cross-references of an article."""
        prefix = f"{article_id}:"
        outgoing: list[str] = []
        for source, targets in self.xrefs.items():
            if source == article_id or source.startswith(prefix):
                outgoing += [t for t in targets if t not in outgoing]
        return {"cites": outgoing, "cited_by": self._incoming.get(article_id, [])}
