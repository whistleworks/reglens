"""Chunking strategies behind one interface.

Three strategies, compared in the M2 ablation (ADR-0002):

* ``paragraph``: one chunk per article paragraph and per recital (M1 baseline);
* ``article``: one chunk per whole article (split on line boundaries if too long);
* ``fixed``: windows of ``max_tokens`` with ``overlap_tokens`` over the running text of
  each regulation, ignoring the legal structure (a window is attributed to the unit
  where it starts, which is the realistic cost of structure-blind chunking).

Recitals and annexes are chunked the same way by ``paragraph`` and ``article``. Any unit
over the token budget is split on line, then sentence boundaries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, Field

from reglens.ids import Regulation
from reglens.ingestion.parse import Article, Corpus, RegulationDoc
from reglens.ingestion.sources import EURLEX_BASE, Lang

UnitType = Literal["article", "recital", "annex"]
TokenCounter = Callable[[str], int]

# Which CELEX the EUR-Lex link of each unit type points to (anchors are the ELI ids).
_LINK_CELEX: dict[tuple[Regulation, UnitType], str] = {
    ("AIA", "article"): "02024R1689-20260727",
    ("AIA", "annex"): "02024R1689-20260727",
    ("AIA", "recital"): "32024R1689",
    ("GDPR", "article"): "32016R0679",
    ("GDPR", "recital"): "32016R0679",
}
_REG_LABEL: dict[Regulation, str] = {"AIA": "AI Act", "GDPR": "GDPR"}
# Structural labels in the language of the chunk (titles and paths are shown to users).
_LABELS: dict[Lang, dict[str, str]] = {
    "en": {
        "recital": "Recital",
        "annex": "Annex",
        "chapter": "Chapter",
        "section": "Section",
        "par": "par.",
    },
    "it": {
        "recital": "Considerando",
        "annex": "Allegato",
        "chapter": "Capo",
        "section": "Sezione",
        "par": "par.",
    },
}


Strategy = Literal["paragraph", "article", "fixed"]


class ChunkingConfig(BaseModel):
    strategy: Strategy = "paragraph"
    max_tokens: int = Field(
        default=500, description="Budget for the text, below the model limit (512 for e5)"
    )
    overlap_tokens: int = Field(default=64, description="Only for the fixed strategy")
    tokenizer: str = "intfloat/multilingual-e5-large"

    @classmethod
    def from_yaml(cls, path: Path) -> ChunkingConfig:
        """The first (baseline) strategy of configs/ingest.yaml."""
        return cls.all_from_yaml(path)[0]

    @classmethod
    def all_from_yaml(cls, path: Path) -> list[ChunkingConfig]:
        raw = yaml.safe_load(path.read_text())["chunking"]
        items = raw if isinstance(raw, list) else [raw]
        return [cls.model_validate(item) for item in items]


class Chunk(BaseModel):
    id: str = Field(description="<unit_id>#<lang>[~<part>], unique across the corpus")
    unit_id: str = Field(description="Canonical id of the paragraph/recital/annex")
    article_id: str = Field(description="Article-level id used by retrieval metrics")
    regulation: Regulation
    lang: Lang
    type: UnitType
    article: str | None = None
    paragraph: str | None = None
    title: str
    path: str = Field(description="Human-readable hierarchy, e.g. 'AI Act > Chapter III > Art. 6'")
    url_eurlex: str
    text: str
    n_tokens: int


class Chunker(Protocol):
    def chunk(self, corpus: Corpus) -> list[Chunk]: ...


def eurlex_url(regulation: Regulation, unit_type: UnitType, lang: Lang, anchor: str) -> str:
    celex = _LINK_CELEX[(regulation, unit_type)]
    return EURLEX_BASE.format(lang=lang.upper(), celex=celex) + f"#{anchor}"


def split_to_budget(text: str, max_tokens: int, count: TokenCounter) -> list[str]:
    """Greedy split on line boundaries, then on sentence boundaries for overlong lines."""
    if count(text) <= max_tokens:
        return [text]
    pieces: list[str] = []
    for line in text.split("\n"):
        if count(line) <= max_tokens:
            pieces.append(line)
            continue
        sentences = [s for s in _sentences(line) if s]
        for sentence in sentences:
            if count(sentence) <= max_tokens:
                pieces.append(sentence)
            else:  # pathological: a single sentence over budget -> hard word split
                pieces.extend(_word_windows(sentence, max_tokens, count))
    parts: list[str] = []
    current: list[str] = []
    for piece in pieces:
        candidate = "\n".join([*current, piece])
        if current and count(candidate) > max_tokens:
            parts.append("\n".join(current))
            current = [piece]
        else:
            current.append(piece)
    if current:
        parts.append("\n".join(current))
    return parts


def _sentences(line: str) -> Iterator[str]:
    start = 0
    for i, char in enumerate(line):
        if char in ".;:" and i + 1 < len(line) and line[i + 1] == " ":
            yield line[start : i + 1].strip()
            start = i + 1
    yield line[start:].strip()


def _word_windows(sentence: str, max_tokens: int, count: TokenCounter) -> list[str]:
    windows: list[str] = []
    current: list[str] = []
    for word in sentence.split(" "):
        if current and count(" ".join([*current, word])) > max_tokens:
            windows.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        windows.append(" ".join(current))
    return windows


class ParagraphChunker:
    def __init__(self, config: ChunkingConfig, count_tokens: TokenCounter) -> None:
        self.config = config
        self.count = count_tokens

    def chunk(self, corpus: Corpus) -> list[Chunk]:
        chunks: list[Chunk] = []
        for doc in corpus.regulations:
            labels = _LABELS[doc.lang]
            for article in doc.articles:
                chunks.extend(self._article_chunks(doc, article))
            for recital in doc.recitals:
                chunks.extend(
                    self._make(
                        doc,
                        unit_id=recital.id,
                        article_id=recital.id,
                        unit_type="recital",
                        title=f"{labels['recital']} {recital.number}",
                        path=(
                            f"{_REG_LABEL[doc.regulation]} > {labels['recital']} ({recital.number})"
                        ),
                        anchor=f"rct_{recital.number}",
                        text=recital.text,
                    )
                )
            for annex in doc.annexes:
                # Whole annex text, packed on line boundaries up to the budget: annexes mix
                # points, section headings and free text, and nothing must be dropped.
                chunks.extend(
                    self._make(
                        doc,
                        unit_id=annex.id,
                        article_id=annex.id,
                        unit_type="annex",
                        title=f"{labels['annex']} {annex.number}: {annex.title}",
                        path=(
                            f"{_REG_LABEL[doc.regulation]} > {labels['annex']} {annex.number} "
                            f"{annex.title}"
                        ),
                        anchor=f"anx_{annex.number}",
                        text=annex.text,
                    )
                )
        return chunks

    def _article_chunks(self, doc: RegulationDoc, article: Article) -> list[Chunk]:
        labels = _LABELS[doc.lang]
        parts = [_REG_LABEL[doc.regulation]]
        if article.chapter:
            parts.append(
                f"{labels['chapter']} {article.chapter} {article.chapter_title or ''}".strip()
            )
        if article.section:
            parts.append(
                f"{labels['section']} {article.section} {article.section_title or ''}".strip()
            )
        parts.append(f"{article.heading} {article.title}".strip())
        out: list[Chunk] = []
        for paragraph in article.paragraphs:
            path = " > ".join(
                parts + ([f"{labels['par']} {paragraph.number}"] if paragraph.number else [])
            )
            out.extend(
                self._make(
                    doc,
                    unit_id=paragraph.id,
                    article_id=article.id,
                    unit_type="article",
                    title=f"{article.heading} {article.title}".strip(),
                    path=path,
                    anchor=f"art_{article.number}",
                    text=paragraph.text,
                    article=article.number,
                    paragraph=paragraph.number,
                )
            )
        return out

    def _make(
        self,
        doc: RegulationDoc,
        *,
        unit_id: str,
        article_id: str,
        unit_type: UnitType,
        title: str,
        path: str,
        anchor: str,
        text: str,
        article: str | None = None,
        paragraph: str | None = None,
    ) -> list[Chunk]:
        parts = split_to_budget(text, self.config.max_tokens, self.count)
        return [
            Chunk(
                id=f"{unit_id}#{doc.lang}" + (f"~{i}" if len(parts) > 1 else ""),
                unit_id=unit_id,
                article_id=article_id,
                regulation=doc.regulation,
                lang=doc.lang,
                type=unit_type,
                article=article,
                paragraph=paragraph,
                title=title,
                path=path,
                url_eurlex=eurlex_url(doc.regulation, unit_type, doc.lang, anchor),
                text=part,
                n_tokens=self.count(part),
            )
            for i, part in enumerate(parts)
            if part.strip()
        ]


def hf_token_counter(tokenizer_name: str) -> TokenCounter:
    """Token counter of the embedding model (special tokens included)."""
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(tokenizer_name)
    tokenizer.no_truncation()
    tokenizer.no_padding()

    def count(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    return count


class ArticleChunker(ParagraphChunker):
    """Whole articles; recitals and annexes as in the paragraph strategy."""

    def _article_chunks(self, doc: RegulationDoc, article: Article) -> list[Chunk]:
        labels = _LABELS[doc.lang]
        parts = [_REG_LABEL[doc.regulation]]
        if article.chapter:
            parts.append(
                f"{labels['chapter']} {article.chapter} {article.chapter_title or ''}".strip()
            )
        if article.section:
            parts.append(
                f"{labels['section']} {article.section} {article.section_title or ''}".strip()
            )
        parts.append(f"{article.heading} {article.title}".strip())
        return self._make(
            doc,
            unit_id=article.id,
            article_id=article.id,
            unit_type="article",
            title=f"{article.heading} {article.title}".strip(),
            path=" > ".join(parts),
            anchor=f"art_{article.number}",
            text=article.text,
            article=article.number,
        )


class FixedChunker:
    """Structure-blind token windows with overlap (per regulation and unit type)."""

    def __init__(self, config: ChunkingConfig, count_tokens: TokenCounter) -> None:
        if config.overlap_tokens >= config.max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        self.config = config
        self.count = count_tokens
        self._units = ParagraphChunker(
            config.model_copy(update={"max_tokens": 10**9}), count_tokens
        )
        self._word_cost: dict[str, int] = {}

    def _cost(self, word: str) -> int:
        # tokens of a word on its own, without the 2 special tokens the counter adds
        if word not in self._word_cost:
            self._word_cost[word] = max(1, self.count(word) - self.count(""))
        return self._word_cost[word]

    def chunk(self, corpus: Corpus) -> list[Chunk]:
        units = self._units.chunk(corpus)  # one unsplit chunk per unit, in document order
        out: list[Chunk] = []
        groups: dict[tuple[str, str], list[Chunk]] = {}
        for unit in units:
            groups.setdefault((unit.regulation, unit.type), []).append(unit)
        for group in groups.values():  # windows never cross regulations or unit types
            words: list[tuple[str, Chunk]] = [(w, u) for u in group for w in u.text.split()]
            out.extend(self._windows(words))
        return out

    def _windows(self, words: list[tuple[str, Chunk]]) -> list[Chunk]:
        windows: list[Chunk] = []
        start = 0
        n = 0
        budget, overlap = self.config.max_tokens, self.config.overlap_tokens
        while start < len(words):
            end, used = start, self.count("")
            while end < len(words) and used + self._cost(words[end][0]) <= budget:
                used += self._cost(words[end][0])
                end += 1
            end = max(end, start + 1)
            text = " ".join(w for w, _ in words[start:end])
            while self.count(text) > budget and end - start > 1:  # estimate was optimistic
                end -= 1
                text = " ".join(w for w, _ in words[start:end])
            first = words[start][1]
            windows.append(
                first.model_copy(
                    update={
                        "id": f"{first.unit_id}#{first.lang}~w{n}",
                        "paragraph": first.paragraph,
                        "text": text,
                        "n_tokens": self.count(text),
                    }
                )
            )
            n += 1
            if end >= len(words):
                break
            # step back by roughly ``overlap`` tokens
            back, cost = end, 0
            while back > start + 1 and cost < overlap:
                back -= 1
                cost += self._cost(words[back][0])
            start = back
        return windows


def make_chunker(config: ChunkingConfig, count_tokens: TokenCounter) -> Chunker:
    if config.strategy == "paragraph":
        return ParagraphChunker(config, count_tokens)
    if config.strategy == "article":
        return ArticleChunker(config, count_tokens)
    if config.strategy == "fixed":
        return FixedChunker(config, count_tokens)
    raise ValueError(f"unknown chunking strategy {config.strategy!r}")  # pragma: no cover
