"""Judge calibration: agreement and Cohen's kappa between the LLM judge and human labels.

    python -m evals.calibrate_judge evals/human_labels/calibration.jsonl \
        evals/results/<judged run>.json

``calibration.jsonl``: one object per labelled answer
    {"id": "q012", "faithfulness": "pass"|"fail", "correctness": "pass"|"fail", "notes": "..."}
labelled by the project owner on answers of a dev run (40 labels, brief M3).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Cohen's kappa for two binary raters. 1.0 if both are constant and identical."""
    if len(a) != len(b) or not a:
        raise ValueError("need two non-empty label lists of equal length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def calibrate(labels: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    judged = {q["id"]: q for q in run["per_query"]}
    out: dict[str, Any] = {}
    for criterion in ("faithfulness", "correctness"):
        human, judge = [], []
        for label in labels:
            verdict = (judged.get(label["id"]) or {}).get("judge", {}).get(criterion)
            if label.get(criterion) not in ("pass", "fail") or verdict is None:
                continue
            human.append(label[criterion] == "pass")
            judge.append(bool(verdict))
        if not human:
            out[criterion] = {"n": 0}
            continue
        agreement = sum(h == j for h, j in zip(human, judge, strict=True)) / len(human)
        out[criterion] = {
            "n": len(human),
            "agreement": round(agreement, 4),
            "kappa": round(cohen_kappa(human, judge), 4),
            "judge_prompt": run.get("prompt_versions", {}).get(f"judge_{criterion}"),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibrate_judge")
    parser.add_argument("labels", type=Path)
    parser.add_argument("run", type=Path)
    args = parser.parse_args(argv)
    labels = [json.loads(line) for line in args.labels.read_text().splitlines() if line.strip()]
    result = calibrate(labels, json.loads(args.run.read_text()))
    sys.stdout.write(json.dumps(result, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
