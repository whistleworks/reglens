from __future__ import annotations

import pytest

from evals.metrics.stats import bootstrap_ci, paired_bootstrap, percentiles


def test_bootstrap_ci_contains_mean_and_is_deterministic() -> None:
    values = [0.0, 1.0] * 50
    low, high = bootstrap_ci(values, n_resamples=1000, seed=0)
    assert low < 0.5 < high
    assert (low, high) == bootstrap_ci(values, n_resamples=1000, seed=0)
    assert 0.35 < low < 0.45  # se = 0.05 -> about 0.40..0.60
    assert 0.55 < high < 0.65


def test_bootstrap_ci_degenerate() -> None:
    assert bootstrap_ci([1.0, 1.0, 1.0]) == (1.0, 1.0)
    with pytest.raises(ValueError, match="empty"):
        bootstrap_ci([])


def test_paired_bootstrap_detects_consistent_improvement() -> None:
    a = [0.0] * 30 + [1.0] * 30
    b = [1.0] * 60  # b better on 30 queries, never worse
    result = paired_bootstrap(a, b, seed=0)
    assert result["delta"] == pytest.approx(0.5)
    assert result["ci95"][0] > 0
    assert result["p_value"] < 0.01


def test_paired_bootstrap_requires_aligned_inputs() -> None:
    with pytest.raises(ValueError, match="same length"):
        paired_bootstrap([1.0], [1.0, 0.0])


def test_percentiles() -> None:
    result = percentiles(list(range(1, 101)))
    assert result == {"p50": 50.5, "p95": 95.05, "p99": 99.01}
