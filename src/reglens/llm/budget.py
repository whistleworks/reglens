"""Daily budget kill-switch on the shadow cost (DAILY_BUDGET_USD).

Over budget the API switches to "sources only" mode (M4): retrieval still answers,
generation is skipped. State is in memory per process; the day rolls over at UTC midnight.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime


class BudgetExceededError(RuntimeError):
    pass


class DailyBudget:
    def __init__(self, limit_usd: float, today: Callable[[], date] | None = None) -> None:
        self.limit_usd = limit_usd
        self._today = today or (lambda: datetime.now(UTC).date())
        self._day = self._today()
        self._spent = 0.0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        current = self._today()
        if current != self._day:
            self._day, self._spent = current, 0.0

    @property
    def spent_usd(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def check(self) -> None:
        if self.remaining_usd <= 0:
            raise BudgetExceededError(f"daily budget of ${self.limit_usd:.2f} exhausted")

    def record(self, cost_usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += cost_usd
