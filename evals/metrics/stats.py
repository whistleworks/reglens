"""Bootstrap confidence intervals and paired comparisons (seeded, reproducible)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

N_RESAMPLES = 1000


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_resamples: int = N_RESAMPLES,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean."""
    if len(values) == 0:
        raise ValueError("cannot bootstrap an empty sample")
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(n_resamples, len(arr)))].mean(axis=1)
    low, high = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return round(float(low), 4), round(float(high), 4)


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_resamples: int = N_RESAMPLES,
    seed: int = 0,
) -> dict[str, float | tuple[float, float]]:
    """Paired bootstrap of mean(b - a) over the same queries.

    ``p_value`` is the one-sided fraction of resamples where b is not better than a.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    diff = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    rng = np.random.default_rng(seed)
    means = diff[rng.integers(0, len(diff), size=(n_resamples, len(diff)))].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return {
        "delta": round(float(diff.mean()), 4),
        "ci95": (round(float(low), 4), round(float(high), 4)),
        "p_value": round(float((means <= 0).mean()), 4),
    }


def percentiles(values: Sequence[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    p50, p95, p99 = np.percentile(arr, [50, 95, 99])
    return {"p50": round(float(p50), 2), "p95": round(float(p95), 2), "p99": round(float(p99), 2)}
