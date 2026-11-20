"""Single source of configuration. Everything is read from environment variables (or .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "ci", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    git_sha: str = "unknown"

    # Paths
    data_dir: Path = REPO_ROOT / "data"

    # Ingestion
    http_user_agent: str = "RegLens/0.1 (+https://github.com/; research, contact via repo)"
    http_timeout_s: float = 60.0

    # API (M4)
    api_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    rate_limit_per_min: int = 30
    max_input_chars: int = 2000
    daily_budget_usd: float = 1.0

    # LLM (ADR-0001, ADR-0005): "<provider>/<model>" references
    llm_primary_model: str = "groq/openai/gpt-oss-120b"
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gemini/gemini-3.8-flash"]
    )
    llm_timeout_s: float = 20.0
    judge_model: str = "gemini/gemini-3.8-flash"
    llm_cache_dir: Path = REPO_ROOT / "evals" / "cache"
    llm_cache_mode: Literal["readwrite", "replay", "off"] = "readwrite"
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    agent_max_steps: int = 6
    agent_timeout_s: float = 25.0
    agent_max_tokens: int = 24_000

    # Observability (M4): Langfuse via OTLP, metrics via OTLP to Grafana Cloud
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: str | None = None

    # Retrieval
    embedding_model: str = "intfloat/multilingual-e5-large"
    sparse_model: str = "Qdrant/bm25"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = ""
    index_mode: Literal["cloud", "local_snapshot"] = "cloud"
    index_snapshot_path: Path = REPO_ROOT / "index_snapshot"

    @field_validator("api_keys", "cors_origins", "llm_fallback_models", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator(
        "qdrant_api_key",
        "groq_api_key",
        "gemini_api_key",
        "openrouter_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "otel_exporter_otlp_endpoint",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    def provider_key(self, provider: str) -> str | None:
        secret = {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openrouter": self.openrouter_api_key,
        }.get(provider)
        return secret.get_secret_value() if secret else None

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
