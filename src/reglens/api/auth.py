"""API-key authentication with constant-time comparison."""

from __future__ import annotations

import hmac

from fastapi import Request


def extract_key(request: Request) -> str | None:
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def key_matches(candidate: str | None, valid_keys: list[str]) -> bool:
    if not candidate:
        return False
    # compare against every key so timing does not reveal how many keys exist or match early
    matched = False
    for key in valid_keys:
        matched |= hmac.compare_digest(candidate.encode(), key.encode())
    return matched
