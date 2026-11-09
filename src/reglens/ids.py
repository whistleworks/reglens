"""Canonical identifiers for every addressable unit of the corpus.

Grammar (tokens separated by ``:``)::

    <REG>:art:<N>[:par:<P>][:pt:<X>]     article, paragraph, point
    <REG>:art:<N>:def:<N>                 numbered definition (AIA art. 3, GDPR art. 4)
    <REG>:rec:<N>                         recital
    <REG>:annex:<ROMAN>[:pt:<X>]          annex and annex point

``N`` and ``P`` are positive integers without leading zeros, optionally followed by
a lowercase letter for inserted provisions (``4a``, ``75d``, ``par:3a``). ``X`` is a
letter point (``a``, ``ha``) or a number (``4``, ``2a``). Articles inserted by amending
acts use the English letter suffix in every language (``Articolo 4 bis`` -> ``4a``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal, cast, get_args

from pydantic import AfterValidator

Regulation = Literal["AIA", "GDPR"]
Kind = Literal["art", "rec", "annex"]

REGULATIONS: tuple[Regulation, ...] = get_args(Regulation)
_KIND_ORDER: dict[str, int] = {"art": 0, "rec": 1, "annex": 2}

_NUM = r"[1-9][0-9]{0,2}"
_NUM_SUFFIX = rf"{_NUM}[a-z]?"
_POINT = rf"(?:[a-z]{{1,3}}|{_NUM_SUFFIX})"
_ROMAN = r"[IVXL]+"

_PATTERN = re.compile(
    rf"""^(?P<reg>{"|".join(REGULATIONS)}):(?:
        art:(?P<art>{_NUM_SUFFIX})
            (?::def:(?P<def>{_NUM_SUFFIX})
            |(?::par:(?P<par>{_NUM_SUFFIX}))?(?::pt:(?P<art_pt>{_POINT}))?)
        |rec:(?P<rec>{_NUM})
        |annex:(?P<annex>{_ROMAN})(?::pt:(?P<annex_pt>{_POINT}))?
    )$""",
    re.VERBOSE,
)

_ROMAN_VALUES = [
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


class InvalidIdError(ValueError):
    """Raised when a string is not a canonical RegLens identifier."""


def to_roman(n: int) -> str:
    if not 1 <= n < 90:
        raise ValueError(f"roman numerals supported in [1, 89], got {n}")
    out = []
    for value, symbol in _ROMAN_VALUES:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


def from_roman(roman: str) -> int:
    total, i = 0, 0
    for value, symbol in _ROMAN_VALUES:
        while roman.startswith(symbol, i):
            total += value
            i += len(symbol)
    if i != len(roman) or total == 0 or to_roman(total) != roman:
        raise ValueError(f"not a canonical roman numeral: {roman!r}")
    return total


def _num_key(token: str) -> tuple[int, str]:
    """``"4a"`` -> ``(4, "a")``; letter-only points sort after numbers by code point."""
    match = re.match(r"(\d+)(.*)", token)
    if match is None:
        return (10**6, token)
    return (int(match.group(1)), match.group(2))


@dataclass(frozen=True, slots=True)
class CanonicalId:
    regulation: Regulation
    kind: Kind
    number: str
    paragraph: str | None = None
    point: str | None = None
    definition: str | None = None

    def __post_init__(self) -> None:
        # Re-validate through the grammar so that hand-built ids obey the same rules.
        parse_id(self._render())

    def _render(self) -> str:
        parts = [self.regulation, self.kind, self.number]
        if self.definition is not None:
            parts += ["def", self.definition]
        if self.paragraph is not None:
            parts += ["par", self.paragraph]
        if self.point is not None:
            parts += ["pt", self.point]
        return ":".join(parts)

    def __str__(self) -> str:
        return self._render()

    def article_level(self) -> CanonicalId:
        """Top-level unit (article, recital or annex) used for article-level retrieval metrics."""
        return CanonicalId(self.regulation, self.kind, self.number)

    def parent(self) -> CanonicalId | None:
        if self.point is not None:
            return CanonicalId(self.regulation, self.kind, self.number, self.paragraph)
        if self.paragraph is not None or self.definition is not None:
            return CanonicalId(self.regulation, self.kind, self.number)
        return None

    def sort_key(self) -> tuple[object, ...]:
        number = (from_roman(self.number), "") if self.kind == "annex" else _num_key(self.number)
        return (
            REGULATIONS.index(self.regulation),
            _KIND_ORDER[self.kind],
            number,
            _num_key(self.definition) if self.definition else (0, ""),
            _num_key(self.paragraph) if self.paragraph else (0, ""),
            _num_key(self.point) if self.point else (0, ""),
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, CanonicalId):
            return NotImplemented
        return self.sort_key() < other.sort_key()


def parse_id(raw: str) -> CanonicalId:
    match = _PATTERN.match(raw)
    if match is None:
        raise InvalidIdError(f"not a canonical id: {raw!r}")
    groups = match.groupdict()
    regulation = cast(Regulation, groups["reg"])
    if groups["art"] is not None:
        return _unchecked(
            regulation,
            "art",
            groups["art"],
            paragraph=groups["par"],
            point=groups["art_pt"],
            definition=groups["def"],
        )
    if groups["rec"] is not None:
        return _unchecked(regulation, "rec", groups["rec"])
    try:
        from_roman(groups["annex"])
    except ValueError as exc:
        raise InvalidIdError(str(exc)) from exc
    return _unchecked(regulation, "annex", groups["annex"], point=groups["annex_pt"])


def _unchecked(
    regulation: Regulation,
    kind: Kind,
    number: str,
    paragraph: str | None = None,
    point: str | None = None,
    definition: str | None = None,
) -> CanonicalId:
    """Build without re-running ``__post_init__`` (the caller already validated)."""
    obj = object.__new__(CanonicalId)
    for name, value in (
        ("regulation", regulation),
        ("kind", kind),
        ("number", number),
        ("paragraph", paragraph),
        ("point", point),
        ("definition", definition),
    ):
        object.__setattr__(obj, name, value)
    return obj


def article_id(
    regulation: Regulation,
    number: str,
    *,
    paragraph: str | None = None,
    point: str | None = None,
    definition: str | None = None,
) -> CanonicalId:
    return CanonicalId(regulation, "art", number, paragraph, point, definition)


def recital_id(regulation: Regulation, number: int) -> CanonicalId:
    return CanonicalId(regulation, "rec", str(number))


def annex_id(regulation: Regulation, roman: str, *, point: str | None = None) -> CanonicalId:
    return CanonicalId(regulation, "annex", roman, point=point)


def _validate_citation(value: str) -> str:
    parse_id(value)
    return value


CitationID = Annotated[str, AfterValidator(_validate_citation)]
"""String type for Pydantic models: a canonical id, kept as ``str`` for JSON friendliness."""
