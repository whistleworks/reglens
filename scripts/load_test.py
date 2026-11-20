"""Minimal async load test: N concurrent users for D seconds against /ui/ask or /v1/ask.

    python scripts/load_test.py --url http://localhost:8000 --users 5 --duration 60 [--api-key K]

Reports throughput, p50/p95/p99 latency, error rate and the share of 429 / sources_only
responses (provider rate limits surface as degraded answers, not errors).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time

import httpx

QUESTIONS = [
    "Quali pratiche di IA sono vietate?",
    "What is a deep fake under the AI Act?",
    "Entro quanto va notificato un data breach?",
    "Is an AI system used for credit scoring high-risk?",
    "What are the GDPR principles?",
    "Chi deve nominare un DPO?",
]


async def user(
    client: httpx.Client | httpx.AsyncClient,
    url: str,
    key: str | None,
    deadline: float,
    out: list[dict[str, object]],
) -> None:
    assert isinstance(client, httpx.AsyncClient)
    while time.monotonic() < deadline:
        question = random.choice(QUESTIONS)
        started = time.perf_counter()
        status, mode = 0, None
        try:
            if key:
                r = await client.post(
                    f"{url}/v1/ask", json={"question": question}, headers={"X-API-Key": key}
                )
                status = r.status_code
                mode = r.json().get("mode") if r.status_code == 200 else None
            else:
                r = await client.post(f"{url}/ui/ask", json={"question": question})
                status = r.status_code
                if '"mode": "sources_only"' in r.text:
                    mode = "sources_only"
        except httpx.HTTPError:
            status = -1
        out.append(
            {"latency_ms": (time.perf_counter() - started) * 1000, "status": status, "mode": mode}
        )


async def run(url: str, users: int, duration: int, key: str | None) -> dict[str, object]:
    results: list[dict[str, object]] = []
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient(timeout=60) as client:
        await asyncio.gather(*(user(client, url, key, deadline, results) for _ in range(users)))
    latencies = sorted(float(r["latency_ms"]) for r in results)  # type: ignore[arg-type]
    n = len(results)
    q = statistics.quantiles(latencies, n=100) if n >= 2 else latencies * 99
    return {
        "users": users,
        "duration_s": duration,
        "requests": n,
        "rps": round(n / duration, 2),
        "p50_ms": round(q[49], 1),
        "p95_ms": round(q[94], 1),
        "p99_ms": round(q[98], 1),
        "error_rate": round(sum(r["status"] not in (200, 429) for r in results) / max(n, 1), 4),
        "rate_limited_429": round(sum(r["status"] == 429 for r in results) / max(n, 1), 4),
        "sources_only": round(sum(r["mode"] == "sources_only" for r in results) / max(n, 1), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=5)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--api-key")
    args = parser.parse_args()
    report = asyncio.run(run(args.url.rstrip("/"), args.users, args.duration, args.api_key))
    sys.stdout.write(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
