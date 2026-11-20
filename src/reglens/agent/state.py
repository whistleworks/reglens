"""Explicit agent state and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from reglens.agent.tools import Citation
from reglens.llm.client import Message


class Status(StrEnum):
    RUNNING = "running"
    ANSWERED = "answered"
    REFUSED = "refused"
    CLARIFY = "clarify"
    STEP_LIMIT = "step_limit"
    TIMEOUT = "timeout"
    TOKEN_BUDGET = "token_budget"
    LLM_ERROR = "llm_error"


@dataclass
class ToolCallRecord:
    step: int
    name: str
    arguments: str
    valid: bool
    error: str | None = None
    retrieved: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class AgentState:
    question: str
    messages: list[Message] = field(default_factory=list)
    step: int = 0
    status: Status = Status.RUNNING
    retrieved_ids: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    repairs: int = 0
    nudges: int = 0

    def add_retrieved(self, ids: list[str]) -> None:
        for unit_id in ids:
            if unit_id not in self.retrieved_ids:
                self.retrieved_ids.append(unit_id)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class AgentResult:
    answer: str
    citations: list[Citation]
    status: Status
    reason: str | None
    retrieved_ids: list[str]
    tool_calls: list[ToolCallRecord]
    steps: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    route: str = "agent"
    prompt_versions: dict[str, str] = field(default_factory=dict)
    injection_suspected: bool = False

    @property
    def refused(self) -> bool:
        return self.status not in (Status.ANSWERED, Status.CLARIFY)
