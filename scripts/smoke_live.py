"""Post-deploy smoke test: /health, /ready and 3 golden questions on the live URL.

    python scripts/smoke_live.py --url https://<space>.hf.space [--api-key KEY]

Without an API key the public /ui/ask route is used. Exit code 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

GOLDEN = [
    ("Quali pratiche di IA sono vietate dall'AI Act?", "AIA:art:5"),
    ("Within how many hours must a personal data breach be notified?", "GDPR:art:33"),
    ("Are AI systems for recruitment high-risk?", "AIA:annex:III"),
]


def ask(client: httpx.Client, url: str, question: str, key: str | None) -> dict[str, object]:
    if key:
        r = client.post(f"{url}/v1/ask", json={"question": question}, headers={"X-API-Key": key})
        r.raise_for_status()
        return dict(r.json())
    r = client.post(f"{url}/ui/ask", json={"question": question})
    r.raise_for_status()
    for block in r.text.split("\n\n"):
        if block.startswith("event: answer"):
            return dict(json.loads(block.split("data: ", 1)[1]))
    raise RuntimeError("no answer event in the SSE stream")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    failures: list[str] = []
    with httpx.Client(timeout=90) as client:
        if client.get(f"{url}/health").status_code != 200:
            failures.append("/health not 200")
        ready = client.get(f"{url}/ready")
        sys.stdout.write(f"/ready {ready.status_code} {ready.text[:200]}\n")
        for question, expected in GOLDEN:
            try:
                body = ask(client, url, question, args.api_key)
            except Exception as exc:
                failures.append(f"{question!r}: {exc}")
                continue
            ids = [str(c["id"]) for c in body.get("citations", [])]  # type: ignore[union-attr]
            ids += [str(s["id"]) for s in body.get("sources", [])]  # type: ignore[union-attr]
            ok = any(i.startswith(expected) for i in ids)
            sys.stdout.write(
                f"{'OK ' if ok else 'BAD'} {question} -> {ids[:4]} ({body.get('mode')})\n"
            )
            if not ok:
                failures.append(f"{question!r}: {expected} not among citations/sources")
    for failure in failures:
        sys.stdout.write(f"FAIL {failure}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
