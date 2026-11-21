from __future__ import annotations

import json
from pathlib import Path

from evals.dataset import load_dataset
from evals.e2e import E2EConfig, E2EResult, build_e2e_result, evaluate_one
from evals.metrics.judge import JudgeVerdict
from evals.run_eval import RetrievalConfig
from reglens.agent.state import AgentResult, Status, ToolCallRecord
from reglens.agent.tools import Citation
from tests.unit.test_agent import store as store

DATASET = Path(__file__).parents[1] / "fixtures" / "evals" / "mini.jsonl"
CONFIG = E2EConfig(name="t", retrieval=RetrievalConfig(name="h", retriever="hybrid"))


def result(
    status: Status, cited: list[str], retrieved: list[str], answer: str = "a"
) -> AgentResult:
    return AgentResult(
        answer=answer,
        citations=[Citation(id=c) for c in cited],
        status=status,
        reason=None,
        retrieved_ids=retrieved,
        tool_calls=[ToolCallRecord(1, "search", "{}", True), ToolCallRecord(2, "x", "{", False)],
        steps=2,
        prompt_tokens=100,
        completion_tokens=10,
        cost_usd=0.0001,
        latency_ms=50.0,
        route="agent",
    )


class FakeJudge:
    def faithfulness(self, question: str, answer: str, sources: str) -> JudgeVerdict:
        return JudgeVerdict(1.0, True, {})

    def correctness(
        self, question: str, answer: str, reference: str, key_facts: list[str]
    ) -> JudgeVerdict:
        return JudgeVerdict(0.5, False, {})


def test_answered_query_scores(store) -> None:  # type: ignore[no-untyped-def]
    record = load_dataset(DATASET)[0]  # q001: gold AIA:art:5
    row = evaluate_one(
        record,
        lambda q: result(Status.ANSWERED, ["AIA:art:6:par:2"], ["AIA:art:6:par:2"]),
        store,
        FakeJudge(),
        CONFIG,  # type: ignore[arg-type]
    )
    assert row.status == "answered"
    assert row.scores["refusal_accuracy"] == 1.0
    assert row.scores["citation_precision"] == 0.0  # cited art. 6, gold art. 5
    assert row.scores["citation_validity"] == 1.0
    assert row.scores["tool_call_validity"] == 0.5
    assert row.scores["faithfulness"] == 1.0
    assert row.scores["correctness"] == 0.0
    assert row.scores["task_success"] == 0.0
    assert row.judge == {"faithfulness": True, "correctness": False}


def test_refusal_of_unanswerable_is_correct(store) -> None:  # type: ignore[no-untyped-def]
    record = load_dataset(DATASET)[2]  # q003: unanswerable
    row = evaluate_one(record, lambda q: result(Status.REFUSED, [], []), store, None, CONFIG)
    assert row.scores["refusal_accuracy"] == 1.0
    assert "faithfulness" not in row.scores


def test_errors_do_not_stop_the_run(store, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    def boom(q: str) -> AgentResult:
        raise RuntimeError("provider down")

    records = load_dataset(DATASET)
    rows = [evaluate_one(r, boom, store, None, CONFIG) for r in records]
    assert all(r.status == "error" for r in rows)
    out = build_e2e_result(
        rows,
        config=CONFIG,
        split="dev",
        dataset_path=DATASET,
        git_sha="abc",
        model_ids={},
        prompt_versions={},
        index_version="i",
    )
    assert out.metrics["error_rate"].value == 1.0
    E2EResult.model_validate(json.loads(out.model_dump_json()))


def test_llm_error_status_counts_in_error_rate(store) -> None:  # type: ignore[no-untyped-def]
    records = load_dataset(DATASET)
    rows = [
        evaluate_one(r, lambda q: result(Status.LLM_ERROR, [], [], answer=""), store, None, CONFIG)
        for r in records
    ]
    out = build_e2e_result(
        rows,
        config=CONFIG,
        split="dev",
        dataset_path=DATASET,
        git_sha="abc",
        model_ids={},
        prompt_versions={},
        index_version="i",
    )
    assert out.metrics["error_rate"].value == 1.0


def test_e2e_config_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("name: x\nrouter: false\nretrieval:\n  name: h\n  retriever: dense\n")
    config = E2EConfig.from_yaml(path)
    assert not config.router
    assert config.retrieval.retriever == "dense"
