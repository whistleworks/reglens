"""Ablation table from eval results.

    python -m evals.report evals/results/A.json evals/results/B.json ... [--out docs/ablation.md]

One row per run: metric values with 95% CI, n, retrieval latency p50/p95, link to the JSON.
Every number comes from the result files; nothing is computed that is not in them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from reglens.config import REPO_ROOT

METRICS = ("recall@5", "recall@10", "mrr@10", "ndcg@10")


def describe(config: dict[str, Any]) -> str:
    parts = [config["retriever"], config.get("strategy", "paragraph")]
    if config.get("enrich", "none") != "none":
        parts.append(f"+{config['enrich']}")
    if config.get("rerank"):
        parts.append("+rerank")
    return " · ".join(parts)


def row(result: dict[str, Any], path: Path) -> str:
    cells = [f"`{result['config']['name']}`", describe(result["config"])]
    for metric in METRICS:
        m = result["metrics"].get(metric)
        cells.append(f"{m['value']:.3f} [{m['ci95'][0]:.2f}–{m['ci95'][1]:.2f}]" if m else "—")
    n = result["metrics"][METRICS[0]]["n"] if METRICS[0] in result["metrics"] else 0
    latency = result["latency_ms"].get("retrieval", {})
    cells.append(str(n))
    cells.append(f"{latency.get('p50', 0):.0f} / {latency.get('p95', 0):.0f}")
    try:
        link = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        link = path
    cells.append(f"[json]({link})")
    return "| " + " | ".join(cells) + " |"


def table(paths: list[Path]) -> str:
    results = [(json.loads(p.read_text()), p) for p in paths]
    versions = {r["dataset_version"] for r, _ in results}
    header = (
        "| config | setup | "
        + " | ".join(f"{m} (CI95)" for m in METRICS)
        + " | n | latency ms p50/p95 | run |"
    )
    lines = [header, "|" + "---|" * (len(METRICS) + 5)]
    lines += [row(r, p) for r, p in results]
    lines.append("")
    lines.append(f"Dataset: {', '.join(sorted(versions))}. Split: dev.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report")
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = table(args.results)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
