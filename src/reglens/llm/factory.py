"""Build LLM clients from settings: cached fallback chain for generation, judge client."""

from __future__ import annotations

from reglens.config import Settings
from reglens.llm.cache import CachedClient
from reglens.llm.client import PROVIDER_BASE_URLS, ChatClient, OpenAICompatClient, parse_model_ref
from reglens.llm.fallback import FallbackChain


class MissingAPIKeyError(RuntimeError):
    pass


def make_client(settings: Settings, model_ref: str, *, required: bool = True) -> ChatClient | None:
    provider, model = parse_model_ref(model_ref)
    key = settings.provider_key(provider)
    if key is None and settings.llm_cache_mode != "replay":
        if required:
            raise MissingAPIKeyError(f"set {provider.upper()}_API_KEY to use {model_ref}")
        return None
    inner = OpenAICompatClient(
        provider=provider,
        base_url=PROVIDER_BASE_URLS[provider],
        model=model,
        api_key=key or "replay-only",
        timeout_s=settings.llm_timeout_s,
    )
    return CachedClient(inner, settings.llm_cache_dir, mode=settings.llm_cache_mode)


def generation_client(settings: Settings) -> ChatClient:
    clients = [make_client(settings, settings.llm_primary_model)]
    clients += [make_client(settings, ref, required=False) for ref in settings.llm_fallback_models]
    available = [c for c in clients if c is not None]
    return FallbackChain(available)


def judge_client(settings: Settings) -> ChatClient:
    client = make_client(settings, settings.judge_model)
    assert client is not None
    return client
