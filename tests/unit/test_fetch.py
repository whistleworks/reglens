from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from reglens.ingestion.fetch import MIN_EXPECTED_BYTES, Fetcher, FetchError, HashMismatchError
from reglens.ingestion.sources import SOURCES, source_by_key

BODY = b"<html>" + b"x" * MIN_EXPECTED_BYTES + b"</html>"
Handler = Callable[[httpx.Request], httpx.Response]


def make_fetcher(tmp_path: Path, handler: Handler, *, update_lock: bool = False) -> Fetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher(tmp_path / "raw", tmp_path / "lock.json", client, update_lock=update_lock)


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=BODY + request.headers["Accept-Language"].encode())


def test_downloads_with_content_negotiation_and_pins_hash(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    fetcher = make_fetcher(tmp_path, handler)
    files = fetcher.fetch_all()

    assert len(files) == len(SOURCES) * 2
    assert {r.headers["Accept-Language"] for r in seen} == {"eng", "ita"}
    assert all(r.headers["Accept"] == "application/xhtml+xml" for r in seen)
    lock = json.loads((tmp_path / "lock.json").read_text())
    assert lock["aia_consolidated_it"]["celex"] == "02024R1689-20260727"
    assert lock["gdpr_oj_en"]["sha256"] == files[-2].sha256


def test_second_run_uses_cache_without_network(tmp_path: Path) -> None:
    make_fetcher(tmp_path, ok).fetch_all()

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be used when the cache is warm")

    files = make_fetcher(tmp_path, no_network).fetch_all()
    assert all(f.from_cache for f in files)


def test_cached_file_with_different_hash_is_rejected(tmp_path: Path) -> None:
    make_fetcher(tmp_path, ok).fetch_all()
    target = tmp_path / "raw" / "gdpr_oj_en.html"
    target.write_bytes(BODY + b"tampered")
    with pytest.raises(HashMismatchError, match="gdpr_oj_en"):
        make_fetcher(tmp_path, ok).fetch(source_by_key("gdpr_oj"), "en")
    # --update-lock accepts the new content on purpose
    fetched = make_fetcher(tmp_path, ok, update_lock=True).fetch(source_by_key("gdpr_oj"), "en")
    assert fetched.from_cache


def test_waf_challenge_body_gives_manual_instructions(tmp_path: Path) -> None:
    fetcher = make_fetcher(tmp_path, lambda r: httpx.Response(200, content=b""))
    with pytest.raises(FetchError, match="Download it once by hand") as exc:
        fetcher.fetch(source_by_key("aia_oj"), "it")
    assert "eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32024R1689" in str(exc.value)


def test_retries_transient_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else ok(request)

    fetched = make_fetcher(tmp_path, flaky).fetch(source_by_key("aia_oj"), "en")
    assert calls["n"] == 3
    assert fetched.path.exists()


def test_non_retryable_status_fails_fast(tmp_path: Path) -> None:
    calls = {"n": 0}

    def not_found(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(FetchError, match="HTTP 404"):
        make_fetcher(tmp_path, not_found).fetch(source_by_key("aia_oj"), "en")
    assert calls["n"] == 1
