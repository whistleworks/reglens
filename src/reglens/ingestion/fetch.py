"""Download the legal sources from the Publications Office Cellar, with cache and hash pinning.

EUR-Lex HTML pages sit behind a WAF challenge (HTTP 202, empty body), so we use Cellar
content negotiation instead. Every file is cached in ``data/raw/`` and its sha256 is
pinned in ``data/sources.lock.json`` (committed): a later download whose hash differs
is rejected unless ``update_lock=True``, which keeps ``make ingest`` reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from reglens.ingestion.sources import LANGS, SOURCES, Lang, Source
from reglens.observability.logging import get_logger

log = get_logger(__name__)

MIN_EXPECTED_BYTES = 100_000  # every source is >= 400 KB; smaller bodies are challenge pages


class FetchError(RuntimeError):
    pass


class HashMismatchError(FetchError):
    pass


class _RetryableHTTPError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FetchedFile:
    source_key: str
    lang: Lang
    path: Path
    sha256: str
    url: str
    from_cache: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def manual_instructions(source: Source, lang: Lang, target: Path) -> str:
    return (
        f"Automatic download of {source.key} [{lang}] failed. Download it once by hand:\n"
        f"  1. Open {source.eurlex_url(lang)} in a browser\n"
        f"  2. Save the HTML page ('Save as... > Webpage, HTML only') to {target}\n"
        f"  3. Re-run `make ingest`: the file will be hash-checked against data/sources.lock.json"
    )


class Fetcher:
    def __init__(
        self,
        raw_dir: Path,
        lock_path: Path,
        client: httpx.Client,
        *,
        update_lock: bool = False,
    ) -> None:
        self.raw_dir = raw_dir
        self.lock_path = lock_path
        self.client = client
        self.update_lock = update_lock
        self.lock: dict[str, dict[str, str]] = (
            json.loads(lock_path.read_text()) if lock_path.exists() else {}
        )

    def fetch_all(self) -> list[FetchedFile]:
        fetched = [self.fetch(source, lang) for source in SOURCES for lang in LANGS]
        self._write_lock()
        return fetched

    def fetch(self, source: Source, lang: Lang) -> FetchedFile:
        target = self.raw_dir / source.raw_filename(lang)
        lock_key = f"{source.key}_{lang}"
        pinned = self.lock.get(lock_key, {}).get("sha256")

        if target.exists():
            digest = sha256_file(target)
            self._check_pin(lock_key, digest, pinned, target)
            log.info("fetch.cache_hit", source=source.key, lang=lang, sha256=digest[:12])
            url = self.lock.get(lock_key, {}).get("url", source.cellar_url())
            self._pin(lock_key, digest, url, source)
            return FetchedFile(source.key, lang, target, digest, url, from_cache=True)

        try:
            body, url = self._download(source, lang)
        except (httpx.HTTPError, _RetryableHTTPError, FetchError) as exc:
            raise FetchError(f"{exc}\n\n{manual_instructions(source, lang, target)}") from exc

        digest = hashlib.sha256(body).hexdigest()
        self._check_pin(lock_key, digest, pinned, target)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(target)
        self._pin(lock_key, digest, url, source)
        log.info("fetch.downloaded", source=source.key, lang=lang, bytes=len(body), url=url)
        return FetchedFile(source.key, lang, target, digest, url, from_cache=False)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, _RetryableHTTPError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=20),
        reraise=True,
    )
    def _download(self, source: Source, lang: Lang) -> tuple[bytes, str]:
        response = self.client.get(
            source.cellar_url(),
            headers={
                "Accept": "application/xhtml+xml",
                "Accept-Language": Source.cellar_lang(lang),
            },
            follow_redirects=True,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableHTTPError(f"HTTP {response.status_code} from {response.url}")
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} from {response.url}")
        if len(response.content) < MIN_EXPECTED_BYTES:
            raise FetchError(
                f"suspiciously small body ({len(response.content)} bytes) from {response.url}"
            )
        return response.content, str(response.url)

    def _check_pin(self, lock_key: str, digest: str, pinned: str | None, target: Path) -> None:
        if pinned is not None and pinned != digest and not self.update_lock:
            raise HashMismatchError(
                f"{target} has sha256 {digest[:12]}..., but sources.lock.json pins "
                f"{pinned[:12]}... for {lock_key}. If the source changed on purpose, "
                "re-run with --update-lock and record it in data/README.md."
            )

    def _pin(self, lock_key: str, digest: str, url: str, source: Source) -> None:
        self.lock[lock_key] = {"sha256": digest, "url": url, "celex": source.celex}

    def _write_lock(self) -> None:
        self.lock_path.write_text(json.dumps(self.lock, indent=2, sort_keys=True) + "\n")


def default_client(user_agent: str, timeout_s: float) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout_s)
