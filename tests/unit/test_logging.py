from __future__ import annotations

import json

import pytest

from reglens.observability.logging import configure_logging, get_logger, mask_pii


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("write to mario.rossi@example.com now", "write to [EMAIL] now"),
        ("call +39 333 123 4567 today", "call [PHONE] today"),
        ("Article 6(1) of Regulation 2024/1689", "Article 6(1) of Regulation 2024/1689"),
    ],
)
def test_mask_pii(raw: str, expected: str) -> None:
    assert mask_pii(raw) == expected


def test_logger_emits_json_and_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("test").info("hello", api_key="super-secret", user="a@b.io", n=3)
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["api_key"] == "[REDACTED]"
    assert record["user"] == "[EMAIL]"
    assert record["n"] == 3
    assert record["level"] == "info"
