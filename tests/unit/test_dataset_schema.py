from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from evals.dataset import load_dataset
from reglens.ids import parse_id

ROOT = Path(__file__).parents[2]
SCHEMA = json.loads((ROOT / "evals" / "datasets" / "schema.json").read_text())
DATASETS = sorted((ROOT / "evals" / "datasets").glob("*.jsonl"))


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.name)
def test_every_record_matches_schema_and_model(path: Path) -> None:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    for line in lines:
        record = json.loads(line)
        jsonschema.validate(record, SCHEMA)
        for gold in record["gold_ids"]:
            parse_id(gold)  # same grammar as the regex in schema.json
    assert len(load_dataset(path)) == len(lines)


def test_schema_rejects_inconsistent_records() -> None:
    base = json.loads(DATASETS[0].read_text().splitlines()[0])
    bad_refuse = {**base, "expected_behavior": "refuse", "should_refuse": False}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_refuse, SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**base, "gold_ids": ["AIA:article:5"]}, SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**base, "extra": 1}, SCHEMA)
