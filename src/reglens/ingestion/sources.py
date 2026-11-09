"""Registry of the legal sources that make up the corpus (see data/README.md and ADR-0001)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from reglens.ids import Regulation

Lang = Literal["en", "it"]
LANGS: tuple[Lang, ...] = ("en", "it")

# Cellar content negotiation uses ISO 639-2/B codes; EUR-Lex uses upper-case ISO 639-1.
_CELLAR_LANG: dict[Lang, str] = {"en": "eng", "it": "ita"}

CELLAR_BASE = "http://publications.europa.eu/resource/celex/"
EURLEX_BASE = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    regulation: Regulation
    celex: str
    role: Literal["articles", "recitals", "full"]
    description: str

    def cellar_url(self) -> str:
        return CELLAR_BASE + self.celex

    def eurlex_url(self, lang: Lang) -> str:
        return EURLEX_BASE.format(lang=lang.upper(), celex=self.celex)

    def raw_filename(self, lang: Lang) -> str:
        return f"{self.key}_{lang}.html"

    @staticmethod
    def cellar_lang(lang: Lang) -> str:
        return _CELLAR_LANG[lang]


SOURCES: tuple[Source, ...] = (
    Source(
        key="aia_consolidated",
        regulation="AIA",
        celex="02024R1689-20260727",
        role="articles",
        description="AI Act consolidated text 27.07.2026 (incl. Reg. (EU) 2026/1744); no recitals",
    ),
    Source(
        key="aia_oj",
        regulation="AIA",
        celex="32024R1689",
        role="recitals",
        description="AI Act as published in the OJ (L, 12.7.2024); used for the 180 recitals",
    ),
    Source(
        key="gdpr_oj",
        regulation="GDPR",
        celex="32016R0679",
        role="full",
        description="GDPR as published in the OJ (L 119, 4.5.2016)",
    ),
)


def source_by_key(key: str) -> Source:
    for source in SOURCES:
        if source.key == key:
            return source
    raise KeyError(key)
