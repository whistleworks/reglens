"""Tiny EN/IT language detector for picking the BM25 stemmer of a query.

Stopword voting is enough for two languages and adds no dependency; ties go to English.
"""

from __future__ import annotations

import re

from reglens.ingestion.sources import Lang

_WORD = re.compile(r"[a-zàèéìíòóù']+")
_IT_WORDS = """
il lo la i gli le un una uno di da del della dei delle dello degli nel nella nei nelle
al alla ai alle sul sulla con per tra fra che chi cosa come quando quale quali quanto
è sono essere ha hanno deve devono può possono non anche ma o e se si ci dell all
dall nell sull questo questa questi queste quello quella perché dove mio mia
"""
_EN_WORDS = """
the a an of to in on for with by from at is are was were be been being has have had
do does did can could should would must may might shall will what which who whom
when where why how this that these those and or but not if it its as than my your
"""
_IT = frozenset(_IT_WORDS.split())
_EN = frozenset(_EN_WORDS.split())


def detect_lang(text: str) -> Lang:
    words = _WORD.findall(text.lower().replace("’", "'"))
    tokens = [w.split("'")[0] if "'" in w else w for w in words]
    it_votes = sum(t in _IT for t in tokens)
    en_votes = sum(t in _EN for t in tokens)
    return "it" if it_votes > en_votes else "en"
