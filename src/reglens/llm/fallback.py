"""Retry with exponential backoff + jitter, per-provider circuit breaker, fallback chain."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from reglens.llm.client import ChatClient, ChatRequest, ChatResponse, LLMError
from reglens.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; half-opens after ``cooldown_s``."""

    threshold: int = 3
    cooldown_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return self.clock() - self.opened_at >= self.cooldown_s  # half-open: one probe

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.allow() else "open"


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_s: float = 0.5
    max_s: float = 8.0
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=lambda: random.Random(0))

    def backoff(self, attempt: int) -> float:
        """Full jitter: uniform(0, min(max, base * 2^attempt))."""
        return self.rng.uniform(0, min(self.max_s, self.base_s * 2**attempt))


class AllProvidersFailedError(LLMError):
    pass


def _key(client: ChatClient) -> str:
    return f"{client.provider}/{client.model}"


class FallbackChain:
    """Try each client in order; retry retryable errors; skip providers with an open breaker."""

    def __init__(
        self,
        clients: Sequence[ChatClient],
        *,
        retry: RetryPolicy | None = None,
        breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        if not clients:
            raise ValueError("at least one client is required")
        self.clients = list(clients)
        self.retry = retry or RetryPolicy()
        # One breaker per provider/model: a 503 "high demand" on one Gemini model must not
        # block a fallback to another model of the same provider.
        self.breakers = breakers or {_key(c): CircuitBreaker() for c in self.clients}
        self.provider = "+".join(c.provider for c in self.clients)
        self.model = self.clients[0].model
        self.fallbacks_used = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        errors: list[str] = []
        for position, client in enumerate(self.clients):
            breaker = self.breakers.setdefault(_key(client), CircuitBreaker())
            if not breaker.allow():
                errors.append(f"{_key(client)}: circuit open")
                continue
            for attempt in range(self.retry.attempts):
                try:
                    response = client.chat(request)
                except LLMError as exc:
                    breaker.record_failure()
                    errors.append(f"{_key(client)}: {exc}")
                    log.warning(
                        "llm.error",
                        provider=client.provider,
                        model=client.model,
                        attempt=attempt,
                        retryable=exc.retryable,
                        status=exc.status,
                    )
                    if not exc.retryable or not breaker.allow():
                        break
                    if attempt + 1 < self.retry.attempts:
                        self.retry.sleep(self.retry.backoff(attempt))
                    continue
                breaker.record_success()
                if position > 0:
                    self.fallbacks_used += 1
                    log.info("llm.fallback_used", provider=client.provider)
                return response
        raise AllProvidersFailedError("; ".join(errors), retryable=False)
