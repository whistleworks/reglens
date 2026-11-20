"""Query router: simple questions -> single-step RAG, complex ones -> agent loop.

Single-step RAG = one retrieval + one LLM call that must call final_answer, so it costs
about one LLM round-trip instead of up to six. The router is a transparent heuristic;
its effect on cost and correctness is measured in the eval (brief, M3).
"""

from __future__ import annotations

import re
from typing import Literal

from reglens.agent.guardrails import GuardrailResult
from reglens.agent.loop import AgentLoop
from reglens.agent.prompts import load_prompt
from reglens.agent.state import AgentResult
from reglens.agent.tools import DATA_NOTICE, ToolRegistry, _block
from reglens.llm.client import Message
from reglens.retrieval.qdrant import Hit

Route = Literal["rag", "agent"]

_COMPLEX = re.compile(
    r"\b(and|e|versus|vs\.?|compar\w*|confront\w*|rapporto|relation\w*|relazione|differen\w*|"
    r"both|entramb\w*|which obligations|quali obblighi|scenario|caso|case|is it high-risk|"
    r"è ad alto rischio|how do|come si|relate|interplay)\b",
    re.IGNORECASE,
)
_BOTH_REGS = re.compile(
    r"(ai act|aia|regolamento ia).*(gdpr|rgpd)|(gdpr|rgpd).*(ai act|aia)", re.IGNORECASE | re.DOTALL
)


def route(question: str) -> Route:
    words = len(question.split())
    if _BOTH_REGS.search(question) or words > 28:
        return "agent"
    if _COMPLEX.search(question) and words > 10:
        return "agent"
    return "rag"


class RoutedAssistant:
    def __init__(
        self, agent: AgentLoop, tools: ToolRegistry, *, rag_k: int = 6, router_enabled: bool = True
    ) -> None:
        self.agent = agent
        self.tools = tools
        self.rag_k = rag_k
        self.router_enabled = router_enabled
        self.rag_prompt = load_prompt("rag")

    def answer(self, guarded: GuardrailResult) -> AgentResult:
        chosen: Route = route(guarded.text) if self.router_enabled else "agent"
        if chosen == "agent":
            result = self.agent.run(guarded)
            result.route = "agent"
            return result
        hits: list[Hit] = self.tools.search_hits(guarded.text)[: self.rag_k]
        sources = "\n".join(
            _block(h.unit_id, str(h.payload.get("title", "")), str(h.payload.get("text", "")))
            for h in hits
        )
        prompt = self.rag_prompt.text.format(
            sources=DATA_NOTICE + "\n" + sources, question=guarded.text
        )
        result = self.agent.run(
            guarded,
            preloaded=[Message(role="user", content=prompt)],
            preloaded_ids=[h.unit_id for h in hits],
        )
        result.route = "rag"
        result.prompt_versions["rag"] = self.rag_prompt.version
        return result
