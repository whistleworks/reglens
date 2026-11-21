"""End-to-end evaluation: retrieval + router + agent + citations + (optional) LLM judge.

    python -m evals.run_eval --split dev --stage e2e --config configs/e2e_hybrid.yaml

Needs provider API keys (or LLM_CACHE_MODE=replay with a filled evals/cache/).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from evals.dataset import EvalRecord, Split, dataset_version
from evals.metrics.generation import (
    citation_precision,
    citation_recall,
    injection_succeeded,
    refusal_correct,
    tool_call_validity,
)
from evals.metrics.judge import Judge
from evals.metrics.stats import bootstrap_ci, percentiles
from evals.run_eval import MetricValue, RetrievalConfig
from reglens.agent.citations import validate_citations
from reglens.agent.guardrails import InputRejectedError, check_input
from reglens.agent.state import AgentResult, Status
from reglens.retrieval.store import ArticleStore

AnswerFn = Callable[[str], AgentResult]


class E2EConfig(BaseModel):
    name: str
    retrieval: RetrievalConfig
    router: bool = True
    judge: bool = True
    max_sources_for_judge: int = 8

    @classmethod
    def from_yaml(cls, path: Path) -> E2EConfig:
        return cls.model_validate(yaml.safe_load(path.read_text()))


class E2EQuery(BaseModel):
    id: str
    lang: str
    category: str
    expected_behavior: str
    status: str
    route: str | None = None
    answer: str = ""
    cited_ids: list[str] = Field(default_factory=list)
    retrieved_ids: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    judge: dict[str, bool | None] = Field(default_factory=dict)
    steps: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens: int = 0
    error: str | None = None


class E2EResult(BaseModel):
    schema_version: int = 1
    run_id: str
    git_sha: str
    timestamp: str
    stage: Literal["e2e"] = "e2e"
    dataset_version: str
    split: Split
    config: dict[str, Any]
    model_ids: dict[str, str]
    prompt_versions: dict[str, str]
    index_version: str
    metrics: dict[str, MetricValue]
    by_category: dict[str, dict[str, MetricValue]]
    latency_ms: dict[str, float]
    cost_usd: dict[str, float]
    n_queries: int
    per_query: list[E2EQuery]


def _sources_text(store: ArticleStore, ids: Sequence[str], limit: int) -> str:
    blocks = []
    for unit_id in list(ids)[:limit]:
        unit = store.get(unit_id)
        if unit is not None:
            blocks.append(f'<source id="{unit_id}">\n{unit.text[:2000]}\n</source>')
    return "\n".join(blocks)


def evaluate_one(
    record: EvalRecord,
    answer: AnswerFn,
    store: ArticleStore,
    judge: Judge | None,
    config: E2EConfig,
) -> E2EQuery:
    started = time.perf_counter()
    try:
        check_input(record.question)
        result = answer(record.question)
    except InputRejectedError as exc:
        return E2EQuery(
            id=record.id,
            lang=record.lang,
            category=record.category,
            expected_behavior=record.expected_behavior,
            status="rejected",
            error=str(exc),
        )
    except Exception as exc:  # the run must survive any single failure
        return E2EQuery(
            id=record.id,
            lang=record.lang,
            category=record.category,
            expected_behavior=record.expected_behavior,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    cited = [c.id for c in result.citations]
    scores: dict[str, float] = {
        "refusal_accuracy": refusal_correct(result.status.value, record.expected_behavior),
        "step_limit_hit": float(result.status is Status.STEP_LIMIT),
    }
    if cited:
        report = validate_citations(result.citations, result.retrieved_ids, store)
        scores["citation_validity"] = len(report.valid) / len(cited)
    if (precision := citation_precision(cited, record.gold_ids)) is not None:
        scores["citation_precision"] = precision
    if record.gold_ids and (recall := citation_recall(cited, record.gold_ids)) is not None:
        scores["citation_recall"] = recall
    if (validity := tool_call_validity([t.valid for t in result.tool_calls])) is not None:
        scores["tool_call_validity"] = validity
    if record.category == "adversarial":
        scores["injection_success"] = injection_succeeded(
            result.status.value, record.expected_behavior, result.answer, cited
        )

    verdicts: dict[str, bool | None] = {}
    answered = result.status is Status.ANSWERED
    if judge is not None and config.judge and answered:
        sources = _sources_text(store, result.retrieved_ids, config.max_sources_for_judge)
        faith = judge.faithfulness(record.question, result.answer, sources)
        verdicts["faithfulness"] = faith.passed
        if faith.score is not None:
            scores["faithfulness"] = faith.score
        if record.expected_behavior == "answer" and record.key_facts:
            corr = judge.correctness(
                record.question, result.answer, record.reference_answer, record.key_facts
            )
            verdicts["correctness"] = corr.passed
            if corr.passed is not None:
                scores["correctness"] = float(corr.passed)
    if record.expected_behavior == "answer" and "correctness" in scores:
        scores["task_success"] = float(answered and scores["correctness"] == 1.0)

    return E2EQuery(
        id=record.id,
        lang=record.lang,
        category=record.category,
        expected_behavior=record.expected_behavior,
        status=result.status.value,
        route=result.route,
        answer=result.answer,
        cited_ids=cited,
        retrieved_ids=result.retrieved_ids,
        scores=scores,
        judge=verdicts,
        steps=result.steps,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        tokens=result.prompt_tokens + result.completion_tokens,
    )


def aggregate(rows: Sequence[E2EQuery]) -> dict[str, MetricValue]:
    names = sorted({name for r in rows for name in r.scores})
    out: dict[str, MetricValue] = {}
    for name in names:
        values = [r.scores[name] for r in rows if name in r.scores]
        out[name] = MetricValue(
            value=round(sum(values) / len(values), 4), ci95=bootstrap_ci(values), n=len(values)
        )
    # A provider failure surfaces as status "llm_error" with no exception: count it too,
    # otherwise a run where every call failed reports error_rate 0.
    errors = [float(r.error is not None or r.status == "llm_error") for r in rows]
    if errors:
        out["error_rate"] = MetricValue(
            value=round(sum(errors) / len(errors), 4), ci95=bootstrap_ci(errors), n=len(errors)
        )
    return out


def build_e2e_result(
    rows: list[E2EQuery],
    *,
    config: E2EConfig,
    split: Split,
    dataset_path: Path,
    git_sha: str,
    model_ids: dict[str, str],
    prompt_versions: dict[str, str],
    index_version: str,
    now: datetime | None = None,
) -> E2EResult:
    now = now or datetime.now(UTC)
    by_cat: dict[str, list[E2EQuery]] = {}
    for row in rows:
        by_cat.setdefault(row.category, []).append(row)
    costs = [r.cost_usd for r in rows]
    latencies = [r.latency_ms for r in rows if r.error is None]
    config_hash = RetrievalConfig.model_validate(config.retrieval).config_hash()
    return E2EResult(
        run_id=f"{now:%Y%m%d-%H%M}_{git_sha}_{config.name}_{split}",
        git_sha=git_sha,
        timestamp=now.isoformat(timespec="seconds"),
        dataset_version=dataset_version(dataset_path),
        split=split,
        config={**config.model_dump(), "retrieval_config_hash": config_hash},
        model_ids=model_ids,
        prompt_versions=prompt_versions,
        index_version=index_version,
        metrics=aggregate(rows),
        by_category={k: aggregate(v) for k, v in sorted(by_cat.items())},
        latency_ms=percentiles(latencies) if latencies else {},
        cost_usd={
            "total": round(sum(costs), 6),
            "per_query": round(sum(costs) / len(costs), 8) if costs else 0.0,
        },
        n_queries=len(rows),
        per_query=rows,
    )
