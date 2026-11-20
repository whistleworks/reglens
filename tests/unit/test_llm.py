from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from reglens.llm.budget import BudgetExceededError, DailyBudget
from reglens.llm.cache import CachedClient, cache_key
from reglens.llm.client import (
    ChatRequest,
    ChatResponse,
    LLMError,
    Message,
    OpenAICompatClient,
    ToolSpec,
    Usage,
    parse_model_ref,
)
from reglens.llm.fallback import AllProvidersFailedError, CircuitBreaker, FallbackChain, RetryPolicy
from reglens.llm.pricing import price_of, shadow_cost_usd

REQUEST = ChatRequest(messages=[Message(role="user", content="hi")])


def completion(
    content: str | None = "ok", tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "model": "m",
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def client(handler: Any, provider: str = "groq") -> OpenAICompatClient:
    return OpenAICompatClient(
        provider=provider,
        base_url="https://example.invalid/v1",
        model="m",
        api_key="secret",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_payload_and_parsing_with_tools() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        call = {
            "id": "c1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query": "art 5"}'},
        }
        return httpx.Response(200, json=completion(None, [call]))

    tool = ToolSpec(name="search", description="d", parameters={"type": "object"})
    req = ChatRequest(messages=REQUEST.messages, tools=[tool], tool_choice="auto")
    response = client(handler).chat(req)
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/chat/completions")
    assert seen[0].headers["Authorization"] == "Bearer secret"
    assert (body["temperature"], body["seed"]) == (0.0, 0)
    assert body["tools"][0]["function"]["name"] == "search"
    assert response.message.tool_calls[0].parsed_arguments() == {"query": "art 5"}
    assert response.usage == Usage(prompt_tokens=10, completion_tokens=5)


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)]
)
def test_error_classification(status: int, retryable: bool) -> None:
    with pytest.raises(LLMError) as exc:
        client(lambda r: httpx.Response(status, text="nope")).chat(REQUEST)
    assert exc.value.retryable is retryable
    assert exc.value.status == status


def test_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError) as exc:
        client(handler).chat(REQUEST)
    assert exc.value.retryable


def test_malformed_response_is_retryable() -> None:
    with pytest.raises(LLMError, match="malformed"):
        client(lambda r: httpx.Response(200, json={"choices": []})).chat(REQUEST)


class Scripted:
    """Fake client returning queued results (an exception instance is raised)."""

    def __init__(self, provider: str, outcomes: list[Any]) -> None:
        self.provider = provider
        self.model = "m"
        self.outcomes = outcomes
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ChatResponse(
            model="m",
            provider=self.provider,
            message=Message(role="assistant", content=outcome),
            usage=Usage(),
            latency_ms=1.0,
        )


NO_SLEEP = RetryPolicy(attempts=3, sleep=lambda s: None)


def test_retry_then_success() -> None:
    primary = Scripted("groq", [LLMError("429", retryable=True), "ok"])
    chain = FallbackChain([primary], retry=NO_SLEEP)
    assert chain.chat(REQUEST).message.content == "ok"
    assert primary.calls == 2


def test_fallback_on_non_retryable_and_exhausted_retries() -> None:
    primary = Scripted("groq", [LLMError("400", retryable=False)])
    backup = Scripted("gemini", ["from gemini"])
    chain = FallbackChain([primary, backup], retry=NO_SLEEP)
    assert chain.chat(REQUEST).provider == "gemini"
    assert chain.fallbacks_used == 1
    assert primary.calls == 1  # no retry on non-retryable errors


def test_all_failed() -> None:
    chain = FallbackChain([Scripted("groq", [LLMError("x", retryable=True)] * 3)], retry=NO_SLEEP)
    with pytest.raises(AllProvidersFailedError, match="groq"):
        chain.chat(REQUEST)


def test_circuit_breaker_opens_and_half_opens() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, cooldown_s=30, clock=lambda: now[0])
    breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow()
    now[0] = 31
    assert breaker.state == "half_open"
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed"


def test_open_breaker_skips_provider() -> None:
    breaker = CircuitBreaker(threshold=1)
    breaker.record_failure()
    primary = Scripted("groq", ["never"])
    chain = FallbackChain(
        [primary, Scripted("gemini", ["ok"])], retry=NO_SLEEP, breakers={"groq": breaker}
    )
    assert chain.chat(REQUEST).provider == "gemini"
    assert primary.calls == 0


def test_backoff_is_bounded_full_jitter() -> None:
    policy = RetryPolicy(base_s=1, max_s=4)
    assert all(0 <= policy.backoff(a) <= min(4, 2**a) for a in range(6))


def test_cache_readwrite_and_replay(tmp_path: Path) -> None:
    inner = Scripted("groq", ["first"])
    cached = CachedClient(inner, tmp_path)
    assert cached.chat(REQUEST).message.content == "first"
    again = cached.chat(REQUEST)
    assert again.cached
    assert again.message.content == "first"
    assert (cached.hits, cached.misses, inner.calls) == (1, 1, 1)
    replay = CachedClient(Scripted("groq", []), tmp_path, mode="replay")
    assert replay.chat(REQUEST).cached
    other = ChatRequest(messages=[Message(role="user", content="other")])
    with pytest.raises(LLMError, match="replay cache miss"):
        replay.chat(other)


def test_cache_key_depends_on_model_and_request() -> None:
    assert cache_key("groq/a", REQUEST) != cache_key("groq/b", REQUEST)
    assert cache_key("groq/a", REQUEST) == cache_key("groq/a", REQUEST.model_copy())


def test_shadow_cost() -> None:
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert shadow_cost_usd("groq/openai/gpt-oss-120b", usage) == pytest.approx(0.75)
    # unknown models are priced at the most expensive known entry
    assert price_of("x/unknown") == price_of("gemini/gemini-3.8-flash")


def test_daily_budget_rolls_over() -> None:
    day = [date(2026, 11, 20)]
    budget = DailyBudget(1.0, today=lambda: day[0])
    budget.record(0.6)
    budget.check()
    budget.record(0.5)
    with pytest.raises(BudgetExceededError):
        budget.check()
    day[0] = date(2026, 11, 21)
    assert budget.remaining_usd == 1.0


def test_parse_model_ref() -> None:
    assert parse_model_ref("groq/openai/gpt-oss-120b") == ("groq", "openai/gpt-oss-120b")
    with pytest.raises(ValueError, match="provider"):
        parse_model_ref("unknown/x")
