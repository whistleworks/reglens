"""Evaluation dataset records (one JSON object per line, see evals/datasets/schema.json)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from reglens.ids import CitationID

Split = Literal["dev", "test"]
Category = Literal[
    "single_hop",
    "multi_hop",
    "definitional",
    "scenario",
    "unanswerable",
    "adversarial",
    "ambiguous",
]


class EvalRecord(BaseModel):
    id: str = Field(pattern=r"^q\d{3,4}$")
    split: Split
    lang: Literal["en", "it"]
    category: Category
    question: str = Field(min_length=5)
    gold_ids: list[CitationID]
    reference_answer: str
    key_facts: list[str]
    should_refuse: bool
    expected_behavior: Literal["answer", "refuse", "clarify"]
    difficulty: Literal["easy", "medium", "hard"]
    source: Literal["synthetic_reviewed", "handwritten"]
    reviewed: bool

    @property
    def has_retrieval_target(self) -> bool:
        return self.expected_behavior == "answer" and bool(self.gold_ids)


def load_dataset(path: Path) -> list[EvalRecord]:
    records = [
        EvalRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [r.id for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate ids in {path}")
    return records


def dataset_version(path: Path) -> str:
    """``<file stem>@<sha256[:8]>``: changes whenever a single byte of the dataset changes."""
    return f"{path.stem}@{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"
