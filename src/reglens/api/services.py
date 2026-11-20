"""Service layer behind the API, with controlled degradation (brief M4).

* reranker failure      -> hybrid results without rerank (inside RetrievalPipeline)
* LLM down / over budget -> "sources only" answer with the retrieved passages
* Qdrant unreachable     -> RetrievalUnavailableError -> HTTP 503 with Retry-After
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from reglens.agent.guardrails import GuardrailResult
from reglens.agent.state import AgentResult, Status
from reglens.api.schemas import CitationOut, SourceOut
from reglens.llm.budget import BudgetExceededError, DailyBudget
from reglens.llm.client import LLMError
from reglens.observability.logging import get_logger, mask_pii
from reglens.observability.metrics import METRICS
from reglens.observability.tracing import span
from reglens.retrieval.qdrant import Hit
from reglens.retrieval.store import ArticleStore

log = get_logger(__name__)


class RetrievalUnavailableError(RuntimeError):
    pass


class _Retriever(Protocol):
    def __call__(self, question: str) -> list[Hit]: ...


class _Answerer(Protocol):
    def __call__(self, guarded: GuardrailResult) -> AgentResult: ...


@dataclass
class AnswerOutcome:
    answer: str
    status: str
    reason: str | None
    route: str | None
    citations: list[CitationOut]
    sources: list[SourceOut]
    mode: Literal["full", "sources_only"] = "full"
    degraded: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


@dataclass
class Services:
    retrieve: _Retriever
    answer: _Answerer | None
    store: ArticleStore | None
    budget: DailyBudget
    feedback_path: Path
    versions: dict[str, str] = field(default_factory=dict)
    ready_checks: dict[str, Any] = field(default_factory=dict)
    info_checks: dict[str, Any] = field(default_factory=dict)
    _feedback_lock: threading.Lock = field(default_factory=threading.Lock)

    def sources_from(self, hits: list[Hit], limit: int = 5) -> list[SourceOut]:
        out: list[SourceOut] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.unit_id in seen:
                continue
            seen.add(hit.unit_id)
            text = " ".join(str(hit.payload.get("text", "")).split())
            out.append(
                SourceOut(
                    id=hit.unit_id,
                    title=str(hit.payload.get("title", "")),
                    url=str(hit.payload.get("url_eurlex", "")),
                    snippet=text[:300] + ("…" if len(text) > 300 else ""),
                )
            )
            if len(out) == limit:
                break
        return out

    def _citation_out(self, cid: str, quote: str | None, hits: list[Hit]) -> CitationOut:
        url = next(
            (
                str(h.payload.get("url_eurlex"))
                for h in hits
                if h.unit_id == cid or h.article_id == cid.rsplit(":par:", 1)[0]
            ),
            None,
        )
        title = None
        if self.store is not None:
            unit = self.store.get(cid)
            title = unit.title if unit else None
        return CitationOut(id=cid, quote=quote, title=title, url=url)

    def ask(self, guarded: GuardrailResult) -> AnswerOutcome:
        with span(
            "request",
            question=guarded.text,
            injection=guarded.injection_suspected,
            **{f"version.{k}": v for k, v in self.versions.items()},
        ) as root:
            outcome = self._ask(guarded)
            root.set_attribute("status", outcome.status)
            root.set_attribute("mode", outcome.mode)
            root.set_attribute("cost_usd", outcome.cost_usd)
        if outcome.mode == "sources_only":
            METRICS.inc("degraded_total", mode=outcome.degraded[0] if outcome.degraded else "?")
        if outcome.status not in ("answered", "clarify", "sources_only"):
            METRICS.inc("refusals_total", reason=outcome.status)
        METRICS.inc("cost_usd_total", outcome.cost_usd)
        METRICS.set("budget_remaining_usd", self.budget.remaining_usd)
        return outcome

    def _ask(self, guarded: GuardrailResult) -> AnswerOutcome:
        try:
            with span("retrieval"):
                hits = self.retrieve(guarded.text)
        except Exception as exc:
            log.error("api.retrieval_unavailable", error_type=type(exc).__name__)
            METRICS.inc("errors_total", type="retrieval_unavailable")
            raise RetrievalUnavailableError(str(exc)) from exc
        if hits:
            METRICS.observe("retrieval_top_score", hits[0].score)
        sources = self.sources_from(hits)

        degraded: list[str] = []
        if self.answer is None:
            degraded.append("llm_not_configured")
        else:
            try:
                self.budget.check()
            except BudgetExceededError:
                degraded.append("budget_exhausted")
        if degraded:
            return self._sources_only(sources, degraded)

        assert self.answer is not None
        try:
            with span("answer"):
                result = self.answer(guarded)
        except LLMError as exc:
            log.warning("api.llm_unavailable", error=str(exc))
            METRICS.inc("errors_total", type="llm_unavailable")
            if exc.status == 429:
                METRICS.inc("provider_429_total")
            return self._sources_only(sources, ["llm_unavailable"])
        self.budget.record(result.cost_usd)
        METRICS.observe("agent_steps", result.steps, route=result.route)
        METRICS.inc("tokens_total", result.prompt_tokens, direction="in")
        METRICS.inc("tokens_total", result.completion_tokens, direction="out")
        METRICS.inc("tool_errors_total", sum(1 for t in result.tool_calls if t.error))
        if result.reason and "citations could not be validated" in result.reason:
            METRICS.inc("citation_failures_total")
        if result.status is Status.LLM_ERROR:
            return self._sources_only(sources, ["llm_unavailable"])
        return AnswerOutcome(
            answer=result.answer,
            status=result.status.value,
            reason=result.reason,
            route=result.route,
            citations=[self._citation_out(c.id, c.quote, hits) for c in result.citations],
            sources=sources,
            cost_usd=result.cost_usd,
        )

    @staticmethod
    def _sources_only(sources: list[SourceOut], degraded: list[str]) -> AnswerOutcome:
        return AnswerOutcome(
            answer=(
                "The answer generator is temporarily unavailable. These are the most "
                "relevant passages found in the AI Act and the GDPR."
            ),
            status="sources_only",
            reason=degraded[0],
            route=None,
            citations=[],
            sources=sources,
            mode="sources_only",
            degraded=degraded,
        )

    def record_feedback(self, request_id: str, value: str, comment: str | None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "request_id": request_id,
            "value": value,
            "comment": mask_pii(comment) if comment else None,
        }
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with self._feedback_lock, self.feedback_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def build_services() -> Services:  # pragma: no cover - wiring of real components
    import json as _json

    from reglens.agent.loop import AgentLoop
    from reglens.agent.router import RoutedAssistant
    from reglens.agent.tools import ToolRegistry
    from reglens.config import get_settings
    from reglens.llm.factory import MissingAPIKeyError, generation_client
    from reglens.retrieval.factory import PipelineConfig, build_pipeline

    settings = get_settings()
    import yaml

    from reglens.config import REPO_ROOT

    serving = yaml.safe_load((REPO_ROOT / "configs" / "serving.yaml").read_text())
    retrieval = PipelineConfig.model_validate(
        {
            **serving,
            "rerank": settings.rerank_enabled or serving.get("rerank", False),
            "rerank_model": settings.reranker_model,
        }
    )
    pipeline, model_ids, collection = build_pipeline(retrieval)
    store = ArticleStore.from_dir(settings.processed_dir)
    tools = ToolRegistry(store, lambda q, f: pipeline.search(q, f).hits)
    answer: _Answerer | None
    try:
        agent = AgentLoop(
            generation_client(settings),
            tools,
            max_steps=settings.agent_max_steps,
            timeout_s=settings.agent_timeout_s,
            max_tokens_total=settings.agent_max_tokens,
        )
        assistant = RoutedAssistant(agent, tools)

        def answer(guarded: GuardrailResult) -> AgentResult:
            return assistant.answer(guarded)

        prompt_versions = {"system": agent.system.version, "rag": assistant.rag_prompt.version}
    except MissingAPIKeyError as exc:
        log.warning("api.llm_not_configured", error=str(exc))
        answer, prompt_versions = None, {}
    manifest = _json.loads((settings.processed_dir / "manifest.json").read_text())
    return Services(
        retrieve=lambda q: pipeline.search(q).hits,
        answer=answer,
        store=store,
        budget=DailyBudget(settings.daily_budget_usd),
        feedback_path=settings.data_dir / "feedback" / "feedback.jsonl",
        versions={
            "git_sha": settings.git_sha,
            "index": collection,
            "dataset_content_hash": manifest["content_hash"][:12],
            **model_ids,
            **{f"prompt_{k}": v for k, v in prompt_versions.items()},
        },
        ready_checks={
            "qdrant": lambda: pipeline.search("health check", None).hits is not None,
        },
        info_checks={"llm": lambda: answer is not None},
    )
