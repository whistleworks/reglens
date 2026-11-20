"""Paired comparison of two eval runs on the same queries.

    python -m evals.compare A.json B.json

For every metric: value in A and B, delta (B - A), paired-bootstrap 95% CI of the delta
and one-sided p-value (fraction of resamples where B is not better than A).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals.metrics.stats import paired_bootstrap


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if a.get("dataset_version") != b.get("dataset_version"):
        raise ValueError(
            f"runs use different datasets: {a.get('dataset_version')} vs {b.get('dataset_version')}"
        )
    rows_a = {q["id"]: q for q in a["per_query"] if q.get("error") is None}
    rows_b = {q["id"]: q for q in b["per_query"] if q.get("error") is None}
    common = sorted(rows_a.keys() & rows_b.keys())
    if not common:
        raise ValueError("no query scored in both runs")
    out: dict[str, dict[str, Any]] = {}
    for metric in a["metrics"]:
        if metric not in b["metrics"]:
            continue
        xs = [rows_a[q]["scores"][metric] for q in common]
        ys = [rows_b[q]["scores"][metric] for q in common]
        result = paired_bootstrap(xs, ys)
        out[metric] = {
            "a": round(sum(xs) / len(xs), 4),
            "b": round(sum(ys) / len(ys), 4),
            "n": len(common),
            **result,
        }
    return out


def to_markdown(name_a: str, name_b: str, table: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"| metric | {name_a} | {name_b} | Δ | CI95 Δ | p |",
        "|---|---|---|---|---|---|",
    ]
    for metric, r in table.items():
        arrow = "▲" if r["delta"] > 0 else ("▼" if r["delta"] < 0 else "=")
        low, high = r["ci95"]
        lines.append(
            f"| {metric} | {r['a']:.4f} | {r['b']:.4f} | {arrow} {r['delta']:+.4f} | "
            f"[{low:+.4f}, {high:+.4f}] | {r['p_value']:.3f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare")
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    args = parser.parse_args(argv)
    a, b = load(args.a), load(args.b)
    table = compare(a, b)
    sys.stdout.write(to_markdown(a["config"]["name"], b["config"]["name"], table) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
