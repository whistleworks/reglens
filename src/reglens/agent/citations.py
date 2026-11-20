"""Citation validation: every cited id must exist, be among the retrieved sources (at
article level) and, if a quote is given, the quote must appear verbatim in that source."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from reglens.agent.tools import Citation
from reglens.ids import InvalidIdError, parse_id
from reglens.retrieval.store import ArticleStore


@dataclass
class CitationReport:
    valid: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def article_levels(ids: Iterable[str]) -> set[str]:
    out = set()
    for unit_id in ids:
        try:
            out.add(str(parse_id(unit_id).article_level()))
        except InvalidIdError:
            continue
    return out


def validate_citations(
    citations: list[Citation], retrieved_ids: Iterable[str], store: ArticleStore
) -> CitationReport:
    report = CitationReport()
    allowed = article_levels(retrieved_ids)
    for citation in citations:
        cid = citation.id
        if not store.exists(str(parse_id(cid).article_level())) or store.get(cid) is None:
            report.errors.append(f"{cid}: does not exist in the corpus")
            continue
        if str(parse_id(cid).article_level()) not in allowed:
            report.errors.append(f"{cid}: was not retrieved in this conversation")
            continue
        if citation.quote and not store.contains_quote(cid, citation.quote):
            report.errors.append(f"{cid}: quoted text not found in the source")
            continue
        report.valid.append(cid)
    return report
