"""Versioned prompt files. The first line of each file is ``version: <id>``; the version
is recorded in every trace and eval run. Bump it on every change."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    text: str


def load_prompt(name: str) -> Prompt:
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    header, sep, body = raw.partition("\n---\n")
    if not sep or not header.startswith("version:"):
        raise ValueError(f"prompt {name} has no 'version:' header")
    return Prompt(name=name, version=header.removeprefix("version:").strip(), text=body.strip())
