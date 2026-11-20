"""LLM-as-judge for faithfulness and correctness (prompts versioned in evals/judge_prompts/).

The judge must be a different model family from the generator (ADR-0001) and must be
calibrated against human labels (`evals/calibrate_judge.py`, Cohen's kappa) before its
scores are reported.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reglens.llm.client import ChatClient, ChatRequest, LLMError, Message

PROMPTS = Path(__file__).parents[1] / "judge_prompts"


@dataclass(frozen=True, slots=True)
class JudgePrompt:
    name: str
    version: str
    template: str


def load_judge_prompt(name: str) -> JudgePrompt:
    raw = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    header, _, body = raw.partition("\n---\n")
    return JudgePrompt(name, header.removeprefix("version:").strip(), body.strip())


@dataclass
class JudgeVerdict:
    score: float | None
    passed: bool | None
    raw: dict[str, Any]
    error: str | None = None


def _fill(template: str, **values: str) -> str:
    # str.format would choke on the JSON braces of the template
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def _parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("no JSON object in judge output")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("judge output is not a JSON object")
    return value


class Judge:
    def __init__(self, llm: ChatClient) -> None:
        self.llm = llm
        self.faithfulness_prompt = load_judge_prompt("faithfulness_v1")
        self.correctness_prompt = load_judge_prompt("correctness_v1")

    @property
    def versions(self) -> dict[str, str]:
        return {
            "faithfulness": self.faithfulness_prompt.version,
            "correctness": self.correctness_prompt.version,
        }

    def _ask(self, prompt: str, score_key: str) -> JudgeVerdict:
        request = ChatRequest(
            messages=[Message(role="user", content=prompt)], json_mode=True, max_tokens=1200
        )
        try:
            data = _parse_json(self.llm.chat(request).message.content or "")
        except (LLMError, ValueError) as exc:
            return JudgeVerdict(None, None, {}, error=f"{type(exc).__name__}: {exc}")
        score = data.get(score_key)
        verdict = data.get("verdict")
        return JudgeVerdict(
            float(score) if isinstance(score, int | float) else None,
            verdict == "pass" if verdict in ("pass", "fail") else None,
            data,
        )

    def faithfulness(self, question: str, answer: str, sources: str) -> JudgeVerdict:
        prompt = _fill(
            self.faithfulness_prompt.template, question=question, answer=answer, sources=sources
        )
        return self._ask(prompt, "faithfulness")

    def correctness(
        self, question: str, answer: str, reference: str, key_facts: list[str]
    ) -> JudgeVerdict:
        prompt = _fill(
            self.correctness_prompt.template,
            question=question,
            answer=answer,
            reference=reference,
            key_facts="\n".join(f"- {f}" for f in key_facts),
        )
        return self._ask(prompt, "coverage")
