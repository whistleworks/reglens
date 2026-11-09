from __future__ import annotations

import pytest

from reglens.config import Settings


def test_defaults_load_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "dev"
    assert settings.raw_dir.name == "raw"
    assert settings.processed_dir.parent == settings.data_dir


def test_csv_lists_and_secrets_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "k1, k2,,")
    monkeypatch.setenv("CORS_ORIGINS", "http://a,http://b")
    monkeypatch.setenv("QDRANT_API_KEY", "")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert [k.get_secret_value() for k in settings.api_keys] == ["k1", "k2"]
    assert settings.cors_origins == ["http://a", "http://b"]
    assert settings.qdrant_api_key is None
    assert "k1" not in repr(settings)


def test_invalid_env_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValueError, match="app_env"):
        Settings(_env_file=None)  # type: ignore[call-arg]
