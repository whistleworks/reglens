"""In-memory token-bucket rate limiting per API key and per client IP."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """``per_minute`` requests per identity, with bursts up to ``per_minute``."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(max(1, per_minute))
        self.rate = self.capacity / 60.0
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, identity: str) -> tuple[bool, float]:
        """(allowed, seconds until the next token)."""
        now = self.clock()
        with self._lock:
            bucket = self._buckets.get(identity)
            if bucket is None:
                bucket = self._buckets[identity] = _Bucket(self.capacity, now)
            bucket.tokens = min(self.capacity, bucket.tokens + (now - bucket.updated) * self.rate)
            bucket.updated = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0.0
            return False, (1 - bucket.tokens) / self.rate


def hash_ip(ip: str, salt: str = "reglens") -> str:
    """Pseudonymous IP for logs and rate-limit keys (never log raw IPs)."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]
