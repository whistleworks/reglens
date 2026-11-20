"""Disk cache of LLM responses keyed by the canonical request (also the CI replay cache).

``mode``: ``readwrite`` (default) | ``replay`` (cache only: a miss is an error, used by
the smoke eval in CI with no secrets) | ``off``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from reglens.llm.client import ChatClient, ChatRequest, ChatResponse, LLMError

CacheMode = Literal["readwrite", "replay", "off"]


def cache_key(model_ref: str, request: ChatRequest) -> str:
    canonical = json.dumps(
        {"model": model_ref, "request": request.model_dump(mode="json")},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CachedClient:
    def __init__(self, inner: ChatClient, directory: Path, mode: CacheMode = "readwrite") -> None:
        self.inner = inner
        self.provider = inner.provider
        self.model = inner.model
        self.directory = directory
        self.mode = mode
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def chat(self, request: ChatRequest) -> ChatResponse:
        if self.mode == "off":
            return self.inner.chat(request)
        key = cache_key(f"{self.provider}/{self.model}", request)
        path = self._path(key)
        if path.exists():
            self.hits += 1
            cached = ChatResponse.model_validate_json(path.read_text(encoding="utf-8"))
            return cached.model_copy(update={"cached": True, "latency_ms": 0.0})
        self.misses += 1
        if self.mode == "replay":
            raise LLMError(f"replay cache miss {key[:12]}", retryable=False)
        response = self.inner.chat(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(), encoding="utf-8")
        return response
