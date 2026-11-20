"""Minimal client for OpenAI-compatible ``/chat/completions`` endpoints (ADR-0005).

Groq, Gemini (OpenAI compatibility layer) and OpenRouter all speak this protocol, so
one client covers every provider of ADR-0001. No provider SDK is used.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str = Field(description="Raw JSON string as produced by the model")

    def parsed_arguments(self) -> dict[str, Any]:
        value = json.loads(self.arguments or "{}")
        if not isinstance(value, dict):
            raise ValueError("tool arguments must be a JSON object")
        return value


class Message(BaseModel):
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        if self.tool_call_id is not None:
            out["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            out["name"] = self.name
        return out


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]

    def to_api(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ChatRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    tool_choice: Literal["auto", "required", "none"] | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    seed: int | None = 0
    json_mode: bool = False


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatResponse(BaseModel):
    model: str
    provider: str
    message: Message
    usage: Usage
    latency_ms: float
    finish_reason: str | None = None
    cached: bool = False


class LLMError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class ChatClient(Protocol):
    provider: str
    model: str

    def chat(self, request: ChatRequest) -> ChatResponse: ...


class OpenAICompatClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout_s: float = 20.0,
        http: httpx.Client | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=timeout_s)
        self._timeout = timeout_s

    def payload(self, request: ChatRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_api() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.seed is not None:
            body["seed"] = request.seed
        if request.tools:
            body["tools"] = [t.to_api() for t in request.tools]
            if request.tool_choice:
                body["tool_choice"] = request.tool_choice
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        try:
            response = self._http.post(
                self._url, json=self.payload(request), headers=self._headers, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise LLMError(f"{self.provider} timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise LLMError(f"{self.provider} transport error: {exc}", retryable=True) from exc
        latency = round((time.perf_counter() - started) * 1000, 2)
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMError(
                f"{self.provider} HTTP {response.status_code}",
                retryable=True,
                status=response.status_code,
            )
        if response.status_code >= 400:
            raise LLMError(
                f"{self.provider} HTTP {response.status_code}: {response.text[:300]}",
                retryable=False,
                status=response.status_code,
            )
        return self._parse(response.json(), latency)

    def _parse(self, data: dict[str, Any], latency: float) -> ChatResponse:
        try:
            choice = data["choices"][0]
            raw = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{self.provider} malformed response", retryable=True) from exc
        calls = [
            ToolCall(
                id=str(c.get("id") or f"call_{i}"),
                name=c["function"]["name"],
                arguments=c["function"].get("arguments") or "{}",
            )
            for i, c in enumerate(raw.get("tool_calls") or [])
        ]
        usage = data.get("usage") or {}
        return ChatResponse(
            model=str(data.get("model") or self.model),
            provider=self.provider,
            message=Message(role="assistant", content=raw.get("content"), tool_calls=calls),
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            ),
            latency_ms=latency,
            finish_reason=choice.get("finish_reason"),
        )


# Base URLs of the OpenAI-compatible endpoints (ADR-0001 / ADR-0005).
PROVIDER_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
}


def parse_model_ref(ref: str) -> tuple[str, str]:
    """``groq/openai/gpt-oss-120b`` -> (``groq``, ``openai/gpt-oss-120b``)."""
    provider, _, model = ref.partition("/")
    if provider not in PROVIDER_BASE_URLS or not model:
        raise ValueError(f"model reference must be '<provider>/<model>', got {ref!r}")
    return provider, model
