"""Shadow cost: what each call would cost at the paid list price (we run on free tiers).

Prices are USD per 1M tokens, checked on 2026-11-20. Unknown models are priced at the
most expensive known entry, so that the shadow cost is never under-estimated.
"""

from __future__ import annotations

from dataclasses import dataclass

from reglens.llm.client import Usage


@dataclass(frozen=True, slots=True)
class Price:
    input_per_m: float
    output_per_m: float
    source: str
    checked: str
    confidence: str


PRICES: dict[str, Price] = {
    "groq/openai/gpt-oss-120b": Price(
        0.15,
        0.60,
        "third-party trackers (flexprice.io, llmreference.com); Groq launch post said 0.75 out",
        "2026-11-20",
        "medium: Groq pricing page not reachable from the research tools",
    ),
    "gemini/gemini-3.8-flash": Price(
        0.75,
        3.75,
        "Vertex AI pricing page, introductory price until 2026-12-31 (1.50 / 7.50 from 2027)",
        "2026-11-20",
        "low: Gemini API paid tier may differ from Vertex AI",
    ),
}
_FALLBACK = max(PRICES.values(), key=lambda p: p.input_per_m + p.output_per_m)


# Self-hosted models have no per-token list price; hardware and energy are not modelled.
_LOCAL = Price(0.0, 0.0, "self-hosted (Ollama): no per-token price", "2026-11-20", "n/a")


def price_of(model_ref: str) -> Price:
    if model_ref.startswith("ollama/"):
        return _LOCAL
    return PRICES.get(model_ref, _FALLBACK)


def shadow_cost_usd(model_ref: str, usage: Usage) -> float:
    price = price_of(model_ref)
    cost = (
        usage.prompt_tokens * price.input_per_m + usage.completion_tokens * price.output_per_m
    ) / 1_000_000
    return round(cost, 8)
