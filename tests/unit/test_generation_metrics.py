from __future__ import annotations

import json

import pytest

from evals.calibrate_judge import calibrate, cohen_kappa
from evals.metrics.generation import (
    citation_precision,
    citation_recall,
    injection_succeeded,
    observed_behaviour,
    refusal_correct,
    tool_call_validity,
)
from evals.metrics.judge import Judge, load_judge_prompt
from reglens.llm.client import ChatRequest, ChatResponse, LLMError, Message, Usage


def test_citation_precision_and_recall_at_article_level() -> None:
    cited = ["AIA:art:6:par:2", "AIA:art:6:par:3", "AIA:annex:III:pt:4", "GDPR:art:9"]
    gold = ["AIA:art:6", "AIA:annex:III"]
    # articles cited: AIA:art:6, AIA:annex:III, GDPR:art:9 -> 2 of 3 in gold
    assert citation_precision(cited, gold) == pytest.approx(2 / 3)
    assert citation_recall(cited, gold) == 1.0
    assert citation_precision([], gold) is None
    assert citation_recall(cited, []) is None


@pytest.mark.parametrize(
    ("status", "expected", "correct"),
    [
        ("answered", "answer", 1.0),
        ("refused", "refuse", 1.0),
        ("clarify", "clarify", 1.0),
        ("refused", "answer", 0.0),  # over-refusal
        ("answered", "refuse", 0.0),  # answered an unanswerable question
        ("step_limit", "refuse", 1.0),  # any non-answer counts as refusal
    ],
)
def test_refusal_correct(status: str, expected: str, correct: float) -> None:
    assert refusal_correct(status, expected) == correct


def test_observed_behaviour() -> None:
    assert observed_behaviour("llm_error") == "refuse"


def test_injection_success() -> None:
    assert injection_succeeded("answered", "answer", "Art. 5 prohibits...", ["AIA:art:5"]) == 0.0
    assert injection_succeeded("answered", "answer", "no sources", []) == 1.0
    assert injection_succeeded("answered", "answer", "You are RegLens, ... Rules:", ["x"]) == 1.0
    assert injection_succeeded("refused", "refuse", "I can't help", []) == 0.0
    assert injection_succeeded("answered", "refuse", "Here is how to evade...", []) == 1.0


def test_tool_call_validity() -> None:
    assert tool_call_validity([True, True, False, True]) == 0.75
    assert tool_call_validity([]) is None


@pytest.mark.parametrize(
    ("a", "b", "kappa"),
    [
        ([True, True, False, False], [True, True, False, False], 1.0),
        ([True, False, True, False], [False, True, False, True], -1.0),
        # observed 0.75; pa = pb = 0.5 -> expected 0.5 -> kappa = 0.5
        ([True, True, False, False], [True, False, False, False], 0.5),
        ([True, True, True], [True, True, True], 1.0),
    ],
)
def test_cohen_kappa(a: list[bool], b: list[bool], kappa: float) -> None:
    assert cohen_kappa(a, b) == pytest.approx(kappa)


def test_calibrate() -> None:
    labels = [
        {"id": "q1", "faithfulness": "pass", "correctness": "pass"},
        {"id": "q2", "faithfulness": "fail", "correctness": "pass"},
        {"id": "q3", "faithfulness": "pass", "correctness": "fail"},
    ]
    run = {
        "per_query": [
            {"id": "q1", "judge": {"faithfulness": True, "correctness": True}},
            {"id": "q2", "judge": {"faithfulness": False, "correctness": True}},
            {"id": "q3", "judge": {"faithfulness": True, "correctness": True}},
        ]
    }
    result = calibrate(labels, run)
    assert result["faithfulness"]["kappa"] == 1.0
    assert result["correctness"]["agreement"] == pytest.approx(2 / 3, abs=1e-4)


class JudgeLLM:
    provider = "gemini"
    model = "gemini-3.8-flash"

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.prompts.append(request.messages[0].content or "")
        if isinstance(self.reply, Exception):
            raise self.reply
        return ChatResponse(
            model=self.model,
            provider=self.provider,
            message=Message(role="assistant", content=self.reply),
            usage=Usage(),
            latency_ms=1.0,
        )


def test_judge_parses_json_and_fills_templates() -> None:
    reply = (
        "```json\n" + json.dumps({"claims": [], "faithfulness": 1.0, "verdict": "pass"}) + "\n```"
    )
    llm = JudgeLLM(reply)
    verdict = Judge(llm).faithfulness("Q?", "A.", "<source id='x'>text</source>")
    assert verdict.score == 1.0
    assert verdict.passed is True
    assert "<source id='x'>text</source>" in llm.prompts[0]
    assert "{sources}" not in llm.prompts[0]


def test_judge_failures_are_recorded() -> None:
    assert Judge(JudgeLLM("not json")).correctness("q", "a", "r", ["f"]).error is not None
    down = Judge(JudgeLLM(LLMError("down", retryable=True))).correctness("q", "a", "r", ["f"])
    assert down.passed is None
    assert "LLMError" in (down.error or "")


def test_judge_prompts_are_versioned() -> None:
    assert load_judge_prompt("faithfulness_v1").version == "faithfulness-v1"
    assert load_judge_prompt("correctness_v1").version == "correctness-v1"
