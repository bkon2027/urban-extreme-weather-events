"""Pure statistics: paired tests, bootstrap confidence intervals, Holm correction."""
from __future__ import annotations

import numpy as np
from scipy import stats


def bootstrap_ci(values, rng: np.random.Generator, n_boot: int = 10_000, level: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean."""
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        raise ValueError("cannot bootstrap an empty sample")
    means = rng.choice(x, size=(n_boot, x.size), replace=True).mean(axis=1)
    alpha = (1 - level) / 2
    lo, hi = np.percentile(means, [100 * alpha, 100 * (1 - alpha)])
    return float(lo), float(hi)


def holm(pvalues) -> np.ndarray:
    """Holm-Bonferroni adjusted p-values (step-down, monotone, capped at 1)."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adjusted[i] = min(1.0, running)
    return adjusted


def paired_summary(diffs, rng: np.random.Generator, n_boot: int = 10_000) -> dict:
    """Mean/median urban-minus-rural difference, bootstrap CI, share of pairs urban higher, Wilcoxon p."""
    d = np.asarray(diffs, dtype=float)
    d = d[~np.isnan(d)]
    if d.size < 2:
        raise ValueError("need at least two pairs for a paired test")
    lo, hi = bootstrap_ci(d, rng, n_boot)
    p = 1.0 if np.allclose(d, 0) else float(stats.wilcoxon(d).pvalue)
    return {"n_pairs": int(d.size), "mean_diff": float(d.mean()), "median_diff": float(np.median(d)),
            "ci_low": lo, "ci_high": hi, "share_urban_higher": float((d > 0).mean()), "wilcoxon_p": p}
