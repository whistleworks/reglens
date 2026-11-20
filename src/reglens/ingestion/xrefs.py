"""Bilingual (EN/IT) extraction of cross-references, normalised to canonical ids.

Handled forms (and their Italian equivalents):

* ``Article 6``, ``Article 6(1)``, ``Article 6(1), point (a)``, ``Article 6(1)(a)``,
  ``Article 4, point (11)`` / ``articolo 6, paragrafo 1, lettera a)``, ``articolo 4, punto 11)``
* lists and ranges: ``Articles 9 and 10``, ``Articles 9 to 15``, ``Articles 8, 9 or 10``
  / ``articoli 9 e 10``, ``articoli da 9 a 15``
* annexes: ``Annex III``, ``Annex III, point 4``, ``point 4 of Annex III``
  / ``allegato III``, ``allegato III, punto 4``, ``punto 4 dell'allegato III``
* inserted provisions: ``Article 4a`` / ``articolo 4 bis``

A reference is resolved to the regulation of the citing text unless it is followed by
``of Regulation (EU) 2016/679`` (-> GDPR), ``... 2024/1689`` (-> AIA) or by any other act
(Directive, Treaty, Charter, another Regulation...), in which case it is external and dropped.
Bare intra-article references (``paragraph 2``) are not extracted.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from reglens.ids import CanonicalId, Regulation, annex_id, article_id
from reglens.ingestion.parse import Corpus, normalize_label

_LATIN = r"(?:bis|ter|quater|quinquies|sexies|septies|octies)"
_NUM = rf"\d{{1,3}}(?:[a-z]\b|\s{_LATIN}\b)?"
_ROMAN = r"[IVXL]+\b"

# One article "item": number plus optional paragraph/point qualifiers.
_EN_ITEM = (
    rf"(?P<num>{_NUM})(?:\((?P<par>\d{{1,3}}[a-z]?)\))?"
    r"(?:\((?P<pt>[a-z]{1,3})\))?"
    r"(?:,\s*(?:first|second|third|fourth|fifth)\s+subparagraph)?"
    r"(?:,\s*points?\s*\((?P<pt2>[a-z0-9]{1,3})\))?"
)
_IT_ITEM = (
    rf"(?P<num>{_NUM})(?:,\s*paragrafo\s+(?P<par>\d{{1,3}}(?:\s{_LATIN})?))?"
    r"(?:,\s*(?:primo|secondo|terzo|quarto|quinto)\s+comma)?"
    r"(?:,\s*(?:lettera|lettere)\s+(?P<pt>[a-z]{1,3})\))?"
    r"(?:,\s*punt[oi]\s+(?P<pt2>[0-9]{1,3}[a-z]?)\)?)?"
)

_EN_ARTICLES = re.compile(
    rf"\bArticles?\s+(?P<items>{_NUM}(?:\(\d{{1,3}}[a-z]?\))*(?:\([a-z]{{1,3}}\))?"
    rf"(?:(?:,\s*|\s+(?:and|or|to)\s+){_NUM}(?:\(\d{{1,3}}[a-z]?\))*(?:\([a-z]{{1,3}}\))?)*"
    r"(?:,\s*points?\s*\([a-z0-9]{1,3}\))?)"
)
_IT_ARTICLES = re.compile(
    rf"\b[Aa]rticol[oi]\s+(?P<items>(?:da\s+)?{_NUM}"
    rf"(?:,\s*paragrafo\s+\d{{1,3}}(?:\s{_LATIN})?)?"
    r"(?:,\s*(?:primo|secondo|terzo|quarto|quinto)\s+comma)?"
    r"(?:,\s*lettera\s+[a-z]{1,3}\))?(?:,\s*punto\s+[0-9]{1,3}[a-z]?\)?)?"
    rf"(?:(?:,\s*|\s+(?:e|o|a)\s+)(?:da\s+)?{_NUM}(?:,\s*paragrafo\s+\d{{1,3}})?)*)"
)
_EN_ANNEX = re.compile(
    rf"(?:\bpoints?\s+(?P<pre_pt>\d{{1,3}}[a-z]?)(?:\([a-z]\))?\s+of\s+)?\bAnnex\s+(?P<annex>{_ROMAN})"
    r"(?:,\s*(?:Section\s+[A-Z],\s*)?points?\s+(?P<pt>\d{1,3}[a-z]?))?"
)
_IT_ANNEX = re.compile(
    rf"(?:\bpunt[oi]\s+(?P<pre_pt>\d{{1,3}}[a-z]?)(?:,\s*lettera\s+[a-z]\))?\s+dell['’]\s*)?"
    rf"\b[Aa]llegat[oi]\s+(?P<annex>{_ROMAN})"
    r"(?:,\s*(?:sezione\s+[A-Z],\s*)?punt[oi]\s+(?P<pt>\d{1,3}[a-z]?))?"
)

_EXTERNAL_TAIL = re.compile(
    r"^\s*,?\s*(?:of|to|in|under|di|del|della|dello|dei|delle|dell['’]|al|alla|nel|nella)\s*"
    r"(?:the\s+|that\s+|tal[ei]\s+|suddett[oa]\s+|medesim[oa]\s+)?"
    r"(?P<act>(?:Regulation|Directive|Decision|Framework\s+Decision|Treaty|Charter|Protocol|"
    r"Convention|regolamento|direttiva|decisione|decisione\s+quadro|trattato|Carta|protocollo|"
    r"convenzione|TFEU|TEU|TFUE|TUE)\b[^;:.]{0,60})"
)
# AIA arts. 102-110 amend other acts: their "Article 43" is an article of the amended act.
_AMENDING_TITLE = re.compile(
    r"^(?:Amendments?\s+to\s+(?:Regulation|Directive)"
    r"|Modific(?:a|he)\s+(?:del|della|dei|delle)\s+(?:regolament[oi]|dirett\w+))\b"
)
_SELF_ACT = {"2016/679": "GDPR", "2024/1689": "AIA"}
_THIS_ACT = re.compile(r"^(?:this|the\s+present|presente)\b", re.IGNORECASE)


def _canon_num(raw: str) -> str:
    label = normalize_label(raw)
    if label is None:  # pragma: no cover - the regexes only capture labels
        raise ValueError(raw)
    return label


def _resolve_regulation(text: str, end: int, default: Regulation) -> Regulation | None:
    """None if the reference points to an external act."""
    tail = text[end : end + 90]
    if re.match(r"^\s*(?:TFEU|TEU|TFUE|TUE)\b", tail):
        return None
    match = _EXTERNAL_TAIL.match(tail)
    if match is None:
        return default
    act = match.group("act")
    for number, regulation in _SELF_ACT.items():
        if number in act:
            return regulation  # type: ignore[return-value]
    if _THIS_ACT.match(act):
        return default
    return None


def _split_items(items: str, lang: str) -> Iterator[tuple[str, bool]]:
    """Yield (item_text, is_range_end) for ``9, 10 and 11`` or ``9 to 15``."""
    separator = r"(?:,\s*|\s+(?:and|or|to)\s+)" if lang == "en" else r"(?:,\s*|\s+(?:e|o|a)\s+)"
    pieces = re.split(rf"({separator})", items.removeprefix("da ").strip())
    is_range = False
    for piece in pieces:
        if re.fullmatch(separator, piece):
            is_range = bool(re.search(r"\b(?:to|a)\b", piece))
            continue
        piece = piece.strip().removeprefix("da ")
        if piece:
            yield piece, is_range
            is_range = False


def _article_refs(text: str, lang: str, default: Regulation) -> Iterator[CanonicalId]:
    pattern, item_re = (
        (_EN_ARTICLES, re.compile(_EN_ITEM))
        if lang == "en"
        else (_IT_ARTICLES, re.compile(_IT_ITEM))
    )
    for match in pattern.finditer(text):
        regulation = _resolve_regulation(text, match.end(), default)
        if regulation is None:
            continue
        previous: str | None = None
        items = match.group("items")
        # "Article 6(1), point (a)" style qualifiers can follow the comma-separated list
        pieces = list(_split_items(items, lang))
        merged: list[tuple[str, bool]] = []
        for piece, is_range in pieces:
            if (
                re.match(r"(?:points?|paragrafo|lettera|punto|primo|secondo|terzo)\b", piece)
                and merged
            ):
                merged[-1] = (f"{merged[-1][0]}, {piece}", merged[-1][1])
            else:
                merged.append((piece, is_range))
        for piece, is_range in merged:
            item = item_re.match(piece)
            if item is None:
                continue
            number = _canon_num(item.group("num"))
            if is_range and previous is not None and previous.isdigit() and number.isdigit():
                for n in range(int(previous) + 1, int(number) + 1):
                    yield article_id(regulation, str(n))
                previous = number
                continue
            paragraph = item.group("par")
            point = item.group("pt") or item.group("pt2")
            yield article_id(
                regulation,
                number,
                paragraph=_canon_num(paragraph) if paragraph else None,
                point=_canon_num(point) if point else None,
            )
            previous = number


def _annex_refs(text: str, lang: str, default: Regulation) -> Iterator[CanonicalId]:
    pattern = _EN_ANNEX if lang == "en" else _IT_ANNEX
    for match in pattern.finditer(text):
        regulation = _resolve_regulation(text, match.end(), default)
        if regulation is None:
            continue
        point = match.group("pre_pt") or match.group("pt")
        yield annex_id(regulation, match.group("annex"), point=point)


def extract_refs(text: str, lang: str, default: Regulation) -> list[CanonicalId]:
    """All internal references in ``text``, deduplicated, in order of appearance."""
    found = [*_article_refs(text, lang, default), *_annex_refs(text, lang, default)]
    return list(dict.fromkeys(found))


def build_xrefs(corpus: Corpus, known_ids: set[str]) -> dict[str, list[str]]:
    """Map every citing unit (paragraph, recital, annex) to the article-level units it cites.

    Targets are projected to article level and kept only if they exist in the corpus;
    self-references are dropped.
    """
    xrefs: dict[str, list[str]] = {}
    for doc in corpus.regulations:
        units: list[tuple[str, str, str]] = [
            (paragraph.id, art.id, paragraph.text)
            for art in doc.articles
            if not _AMENDING_TITLE.match(art.title)
            for paragraph in art.paragraphs
        ]
        units += [(r.id, r.id, r.text) for r in doc.recitals]
        units += [(a.id, a.id, a.text) for a in doc.annexes]
        for unit_id, parent_id, text in units:
            targets = []
            for ref in extract_refs(text, corpus.lang, doc.regulation):
                target = str(ref.article_level())
                if target != parent_id and target in known_ids and target not in targets:
                    targets.append(target)
            if targets:
                xrefs[unit_id] = targets
    return xrefs
