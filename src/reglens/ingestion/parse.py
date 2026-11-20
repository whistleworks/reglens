"""Parse EUR-Lex/Cellar XHTML into a structured corpus.

Two layouts are supported, both keyed on the stable ELI ids (``art_6``, ``rct_53``,
``anx_III``, ``cpt_III.sct_1``) that are identical across languages:

* **consolidated** (``02024R1689-...``): paragraphs are ``div.norm > span.no-parag``,
  points are ``div.grid-container`` with a label column and a content column,
  amendment markers live in ``p.modref``;
* **oj** (Official Journal, ``3....R....``): paragraphs are ``div#NNN.NNN``, points
  and recitals are two-column ``table`` rows, footnotes are ``span.oj-note-tag``.

Labels are normalised to the canonical id convention: ``(a)``/``a)`` -> ``a``,
``(14a)``/``14 bis)`` -> ``14a``, ``1 bis.`` -> ``1a``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal

from lxml import html
from lxml.html import HtmlElement
from pydantic import BaseModel, Field

from reglens.ids import Regulation, annex_id, article_id, recital_id
from reglens.ingestion.sources import Lang

Layout = Literal["consolidated", "oj"]

# Latin ordinal suffixes used by the Italian texts for inserted provisions.
_LATIN_SUFFIX = {
    "bis": "a",
    "ter": "b",
    "quater": "c",
    "quinquies": "d",
    "sexies": "e",
    "septies": "f",
    "octies": "g",
    "novies": "h",
    "nonies": "h",
    "decies": "i",
}
_LABEL_RE = re.compile(
    r"^[(\[]?\s*(?P<core>[0-9]{1,3}|[a-z]{1,3}|[ivxl]+)\s*(?P<latin>[a-z]+)?\s*[)\].]?$"
)
_QUOTE_CHARS = "‘’'\"«»“”"
_PARA_LEAD_RE = re.compile(r"^(?P<num>[0-9]{1,3})\.?\s+")
# Inline point labels as printed in some OJ texts: "1)   «dato personale»: ...", "(a)   ...".
# The run of 2+ (non-breaking) spaces after the label distinguishes them from prose.
_INLINE_POINT_RE = re.compile(
    r"^\s*(?P<label>\(?[0-9a-z]{1,3}(?:[ \xa0](?:bis|ter|quater|quinquies|sexies))?\))[ \xa0]{2,}"
)
_WS_RE = re.compile(r"\s+")

_NOISE_CLASSES = {
    "modref",
    "arrow",
    "footnote",
    "oj-note",
    "oj-note-tag",
    "separator-annex",
    "separator",
    "oj-doc-sep",
}
_BLOCK_TAGS = {"p", "div", "table", "tbody", "tr", "td", "ul", "ol", "li"}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Point(BaseModel):
    label: str
    raw_label: str
    text: str = Field(description="Rendered text of the point, including nested sub-points")


class Paragraph(BaseModel):
    id: str
    number: str | None = Field(description="None for articles without numbered paragraphs")
    text: str
    points: list[Point] = Field(default_factory=list)


class Article(BaseModel):
    id: str
    number: str
    heading: str = Field(description="'Article 6' / 'Articolo 6' as printed")
    title: str
    chapter: str | None = None
    chapter_title: str | None = None
    section: str | None = None
    section_title: str | None = None
    paragraphs: list[Paragraph]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


class Recital(BaseModel):
    id: str
    number: int
    text: str


class Annex(BaseModel):
    id: str
    number: str
    title: str
    text: str
    points: list[Point] = Field(default_factory=list)


class RegulationDoc(BaseModel):
    regulation: Regulation
    lang: Lang
    celex: list[str]
    articles: list[Article] = Field(default_factory=list)
    recitals: list[Recital] = Field(default_factory=list)
    annexes: list[Annex] = Field(default_factory=list)


class Corpus(BaseModel):
    lang: Lang
    regulations: list[RegulationDoc]


# ---------------------------------------------------------------------------
# Label normalisation
# ---------------------------------------------------------------------------


def normalize_label(raw: str) -> str | None:
    """Return the canonical label, or None if ``raw`` is not a structural label."""
    text = _WS_RE.sub(" ", raw.replace("\xa0", " ")).strip()
    if not text or text[0] in _QUOTE_CHARS:
        return None
    match = _LABEL_RE.match(text.lower())
    if match is None:
        return None
    core, latin = match.group("core"), match.group("latin")
    if latin is None:
        return core
    suffix = _LATIN_SUFFIX.get(latin)
    if suffix is None:
        # EN style "14a" is matched as core="14", latin="a"
        return core + latin if len(latin) == 1 else None
    return core + suffix


def _is_quoted(raw: str) -> bool:
    stripped = raw.replace("\xa0", " ").strip()
    return bool(stripped) and stripped[0] in _QUOTE_CHARS


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def _classes(el: HtmlElement) -> set[str]:
    return set((el.get("class") or "").split())


def _is_noise(el: HtmlElement) -> bool:
    if not isinstance(el.tag, str):
        return True  # comments, processing instructions
    if el.tag in {"hr", "col", "colgroup", "script", "style", "img"}:
        return True
    if _classes(el) & _NOISE_CLASSES:
        return True
    # consolidated footnote references: <a href="#E0001" id="src.E0001"><span>1</span></a>
    return el.tag == "a" and (el.get("id") or "").startswith(("src.", "ntr", "ntc"))


def _inline_text(el: HtmlElement) -> str:
    """Text of an inline subtree, dropping footnote markers and rendering exponents."""
    parts: list[str] = [el.text or ""]
    for child in el:
        if not _is_noise(child):
            if "superscript" in _classes(child) or "oj-super" in _classes(child):
                sup = _inline_text(child).strip()
                previous = "".join(parts).rstrip()
                parts.append(f"^{sup}" if previous[-1:].isdigit() else sup)
            else:
                parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def clean(text: str) -> str:
    text = _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()
    return re.sub(r"\(\s*\)", "", text).replace(" ,", ",").replace(" .", ".").strip()


# Segments are either text lines or points (label + nested segments).
class _PointSeg:
    __slots__ = ("children", "label", "raw_label")

    def __init__(self, raw_label: str, label: str, children: list[_Seg]) -> None:
        self.raw_label = raw_label
        self.label = label
        self.children = children


_Seg = str | _PointSeg


def _has_block_children(el: HtmlElement) -> bool:
    return any(isinstance(c.tag, str) and c.tag in _BLOCK_TAGS for c in el)


def _grid_point(el: HtmlElement) -> _PointSeg | None:
    """``div.grid-container.grid-list`` (consolidated) -> point."""
    if el.tag != "div" or not {"grid-container", "grid-list"} <= _classes(el):
        return None
    label_col = next((c for c in el if "grid-list-column-1" in _classes(c)), None)
    body_col = next((c for c in el if "grid-list-column-2" in _classes(c)), None)
    if label_col is None or body_col is None:
        return None
    raw = clean(_inline_text(label_col))
    label = normalize_label(raw)
    if label is None:
        # dashes and quoted items are rendered as text with their marker
        return _PointSeg(raw, "", segments(body_col))
    return _PointSeg(raw, label, segments(body_col))


def _table_points(el: HtmlElement) -> list[_PointSeg] | None:
    """Two-column OJ table rows ``| (a) | text |`` -> points. None if it is a real table."""
    if el.tag != "table":
        return None
    rows = [tr for tr in el.iter("tr")]
    points: list[_PointSeg] = []
    for tr in rows:
        cells = [td for td in tr if isinstance(td.tag, str) and td.tag == "td"]
        if len(cells) != 2:
            return None
        raw = clean(_inline_text(cells[0]) if not _has_block_children(cells[0]) else "")
        if not raw:
            raw = clean(" ".join(_inline_text(p) for p in cells[0]))
        label = normalize_label(raw)
        if label is None and raw not in {"—", "–", "-", "•"} and not _is_quoted(raw):
            return None
        points.append(_PointSeg(raw, label or "", segments(cells[1])))
    return points or None


def segments(el: HtmlElement) -> list[_Seg]:
    if _is_noise(el):
        return []
    grid = _grid_point(el)
    if grid is not None:
        return [grid]
    table = _table_points(el)
    if table is not None:
        return list(table)
    if not _has_block_children(el):
        raw_text = _inline_text(el)
        inline = _INLINE_POINT_RE.match(raw_text) if "oj-normal" in _classes(el) else None
        if inline is not None:
            label = normalize_label(inline.group("label"))
            if label is not None:
                rest = clean(raw_text[inline.end() :])
                return [_PointSeg(clean(inline.group("label")), label, [rest] if rest else [])]
        text = clean(raw_text)
        return [text] if text else []
    out: list[_Seg] = []
    if el.text and el.text.strip():
        out.append(clean(el.text))
    for child in el:
        out.extend(segments(child))
        if child.tail and child.tail.strip():
            out.append(clean(child.tail))
    return out


def _label_kind(label: str, prev_alpha: str | None) -> str:
    if label[0].isdigit():
        return "num"
    if re.fullmatch(r"[ivxl]+", label):
        follows_letter = (
            prev_alpha is not None and len(label) == 1 and ord(label) == ord(prev_alpha[-1]) + 1
        )
        if not follows_letter:
            return "roman"
    return "alpha"


def nest(segs: list[_Seg]) -> list[_Seg]:
    """Attach sub-points printed as siblings (OJ tables) to their parent point.

    At each level the kind of the first point (number, letter, roman) defines the
    level; a point of another kind that follows a point is its child. Text that
    follows a sub-point list stays at the current level.
    """
    out: list[_Seg] = []
    level_kind: str | None = None
    prev_alpha: str | None = None
    for seg in segs:
        if isinstance(seg, _PointSeg) and seg.label:
            kind = _label_kind(seg.label, prev_alpha)
            if level_kind is None:
                level_kind = kind
            last_point = next((s for s in reversed(out) if isinstance(s, _PointSeg)), None)
            if kind != level_kind and last_point is not None and out[-1] is last_point:
                last_point.children = nest([*last_point.children, seg])
                continue
            if kind == "alpha":
                prev_alpha = seg.label
            seg.children = nest(seg.children)
        out.append(seg)
    return out


def render(segs: Iterable[_Seg], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for seg in segs:
        if isinstance(seg, str):
            lines.append(seg)
            continue
        body = render(seg.children, depth + 1)
        head = f"{seg.raw_label} {body[0]}" if body else seg.raw_label
        lines.append(head.strip())
        lines.extend(body[1:])
    return lines


def _points(segs: Iterable[_Seg]) -> list[Point]:
    """Top-level points. Labels repeated in one unit (e.g. Annex VIII sections A/B/C, two
    lists in AIA art. 43(1)) are merged under the first occurrence, since canonical ids
    have no section level."""
    merged: dict[str, Point] = {}
    for seg in segs:
        if not isinstance(seg, _PointSeg) or not seg.label:
            continue
        text = "\n".join(render([seg]))
        if seg.label in merged:
            merged[seg.label].text += "\n" + text
        else:
            merged[seg.label] = Point(label=seg.label, raw_label=seg.raw_label, text=text)
    return list(merged.values())


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def _first_text(el: HtmlElement, classes: set[str]) -> str | None:
    for node in el.iter():
        if isinstance(node.tag, str) and _classes(node) & classes:
            text = clean(_inline_text(node))
            if text:
                return text
    return None


def _heading_text(div: HtmlElement, level: Literal[1, 2]) -> str | None:
    """Chapter/section headings, looking only at the division's own header elements."""
    wanted = {f"title-division-{level}", f"oj-ti-section-{level}"}
    for child in div:
        if not isinstance(child.tag, str):
            continue
        if child.get("id", "").startswith(("art_", "cpt_")) and ".tit_" not in child.get("id", ""):
            break
        if _classes(child) & wanted:
            return clean(_inline_text(child))
        if child.get("id", "").endswith(".tit_1"):
            found = _first_text(child, wanted)
            if found:
                return found
    return None


def _division_context(article: HtmlElement) -> dict[str, str | None]:
    context: dict[str, str | None] = {
        "chapter": None,
        "chapter_title": None,
        "section": None,
        "section_title": None,
    }
    for ancestor in article.iterancestors():
        el_id = ancestor.get("id") or ""
        match = re.fullmatch(r"cpt_([IVXL]+)(?:\.sct_(\d+))?", el_id)
        if match is None:
            continue
        if match.group(2):
            context["section"] = match.group(2)
            context["section_title"] = _heading_text(ancestor, 2)
        else:
            context["chapter"] = match.group(1)
            context["chapter_title"] = _heading_text(ancestor, 2)
    return context


def _header_children(article: HtmlElement) -> Iterator[HtmlElement]:
    for child in article:
        if not isinstance(child.tag, str):
            continue
        cls = _classes(child)
        if cls & {"title-article-norm", "oj-ti-art"} or child.get("id", "").endswith(".tit_1"):
            continue
        yield child


def _consolidated_paragraphs(
    article: HtmlElement,
) -> list[tuple[str | None, list[_Seg]]]:
    paragraphs: list[tuple[str | None, list[_Seg]]] = []
    for child in _header_children(article):
        if _is_noise(child):
            continue
        marker = next((c for c in child if "no-parag" in _classes(c)), None)
        if child.tag == "div" and marker is not None:
            raw = _inline_text(marker)
            body: list[_Seg] = []
            for sub in child:
                if sub is not marker:
                    body.extend(segments(sub))
            number = normalize_label(raw)
            if number is not None and not _is_quoted(raw):
                paragraphs.append((number, body))
                continue
            # quoted paragraph of an amended act: keep it, with its label, as content
            body = [f"{clean(raw)} {render(body)[0]}" if body else clean(raw), *render(body)[1:]]
        else:
            body = segments(child)
        if not paragraphs:
            paragraphs.append((None, []))
        paragraphs[-1][1].extend(body)
    return paragraphs


def _oj_paragraphs(article: HtmlElement) -> list[tuple[str | None, list[_Seg]]]:
    paragraphs: list[tuple[str | None, list[_Seg]]] = []
    for child in _header_children(article):
        if _is_noise(child):
            continue
        segs = segments(child)
        if child.tag == "div" and re.fullmatch(r"\d{3}\.\d{3}", child.get("id", "")):
            # the div id (NNN.PPP) is authoritative; the printed "1." lead is stripped
            number: str | None = str(int(child.get("id", "").split(".")[1]))
            if segs and isinstance(segs[0], str):
                lead = _PARA_LEAD_RE.match(segs[0])
                if lead is not None and lead.group("num") == number:
                    segs[0] = segs[0][lead.end() :]
            paragraphs.append((number, segs))
            continue
        if not paragraphs:
            paragraphs.append((None, []))
        paragraphs[-1][1].extend(segs)
    return paragraphs


def parse_article(article: HtmlElement, regulation: Regulation, layout: Layout) -> Article:
    number = article.get("id", "").removeprefix("art_")
    heading = _first_text(article, {"title-article-norm", "oj-ti-art"}) or ""
    title = _first_text(article, {"stitle-article-norm", "oj-sti-art"}) or ""
    raw_paragraphs = (
        _consolidated_paragraphs(article) if layout == "consolidated" else _oj_paragraphs(article)
    )
    nested = [(par_number, nest(segs)) for par_number, segs in raw_paragraphs]
    paragraphs = [
        Paragraph(
            id=str(article_id(regulation, number, paragraph=par_number)),
            number=par_number,
            text="\n".join(render(segs)),
            points=_points(segs),
        )
        for par_number, segs in nested
        if render(segs)
    ]
    return Article(
        id=str(article_id(regulation, number)),
        number=number,
        heading=heading,
        title=title,
        paragraphs=paragraphs,
        **_division_context(article),
    )


def parse_recital(div: HtmlElement, regulation: Regulation) -> Recital:
    number = int(div.get("id", "").removeprefix("rct_"))
    segs = segments(div)
    if len(segs) == 1 and isinstance(segs[0], _PointSeg):
        segs = segs[0].children
    return Recital(
        id=str(recital_id(regulation, number)), number=number, text="\n".join(render(segs))
    )


def _is_annex_heading(text: str) -> bool:
    return re.fullmatch(r"(ANNEX|ALLEGATO)\s+[IVXL]+", text) is not None


def parse_annex(div: HtmlElement, regulation: Regulation) -> Annex:
    number = div.get("id", "").removeprefix("anx_")
    title = ""
    segs: list[_Seg] = []
    for child in div:
        if not isinstance(child.tag, str) or _is_noise(child):
            continue
        cls = _classes(child)
        text = clean(_inline_text(child))
        # The title is the first heading that is not "ANNEX X" itself: usually
        # title-annex-2, a second title-annex-1 in Annex X, a plain paragraph in Annex XIV.
        if not title and cls & {"title-annex-1", "title-annex-2"} and _is_annex_heading(text):
            continue
        if not title and text and (cls & {"title-annex-1", "title-annex-2", "norm"}):
            title = text
            continue
        segs.extend(segments(child))
    segs = nest(segs)
    return Annex(
        id=str(annex_id(regulation, number)),
        number=number,
        title=title,
        text="\n".join(render(segs)),
        points=_points(segs),
    )


def _divs(root: HtmlElement, pattern: str) -> list[HtmlElement]:
    regex = re.compile(pattern)
    return [el for el in root.iter("div") if regex.fullmatch(el.get("id") or "")]


def load(path: Path) -> HtmlElement:
    # Cellar always serves UTF-8; do not rely on the (sometimes missing) meta charset.
    parser = html.HTMLParser(encoding="utf-8")
    root: HtmlElement = html.parse(str(path), parser=parser).getroot()
    return root


def parse_document(
    root: HtmlElement,
    regulation: Regulation,
    layout: Layout,
    *,
    articles: bool = True,
    recitals: bool = True,
    annexes: bool = True,
) -> tuple[list[Article], list[Recital], list[Annex]]:
    return (
        [parse_article(a, regulation, layout) for a in _divs(root, r"art_\d+[a-z]?")]
        if articles
        else [],
        [parse_recital(r, regulation) for r in _divs(root, r"rct_\d+")] if recitals else [],
        [parse_annex(a, regulation) for a in _divs(root, r"anx_[IVXL]+")] if annexes else [],
    )


def build_corpus(raw_dir: Path, lang: Lang) -> Corpus:
    """Assemble the corpus for one language from the raw sources (see data/README.md)."""
    aia_articles, _, aia_annexes = parse_document(
        load(raw_dir / f"aia_consolidated_{lang}.html"), "AIA", "consolidated", recitals=False
    )
    _, aia_recitals, _ = parse_document(
        load(raw_dir / f"aia_oj_{lang}.html"), "AIA", "oj", articles=False, annexes=False
    )
    gdpr_articles, gdpr_recitals, gdpr_annexes = parse_document(
        load(raw_dir / f"gdpr_oj_{lang}.html"), "GDPR", "oj"
    )
    return Corpus(
        lang=lang,
        regulations=[
            RegulationDoc(
                regulation="AIA",
                lang=lang,
                celex=["02024R1689-20260727", "32024R1689"],
                articles=aia_articles,
                recitals=aia_recitals,
                annexes=aia_annexes,
            ),
            RegulationDoc(
                regulation="GDPR",
                lang=lang,
                celex=["32016R0679"],
                articles=gdpr_articles,
                recitals=gdpr_recitals,
                annexes=gdpr_annexes,
            ),
        ],
    )
