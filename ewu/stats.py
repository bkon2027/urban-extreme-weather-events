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


def rank_pairs(pair_years, index: str, rng: np.random.Generator, n_boot: int = 10_000):
    """Per-pair mean urban-minus-rural difference with a bootstrap CI over that pair's usable years, ranked high to low."""
    import pandas as pd
    rows = []
    for name, g in pair_years.groupby("urban_area", sort=True):
        vals = g[index].dropna().to_numpy()
        if vals.size < 2:
            continue
        lo, hi = bootstrap_ci(vals, rng, n_boot)
        rows.append({"urban_area": name, "mean_diff": float(vals.mean()), "ci_low": lo, "ci_high": hi, "n_years": int(vals.size)})
    out = pd.DataFrame(rows).sort_values("mean_diff", ascending=False, kind="mergesort").reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    return out


def subset_tests(pair_summary, subsets: dict, indices, rng: np.random.Generator, n_boot: int = 10_000):
    """Paired summary for each named subset (boolean mask over pair_summary), Holm-corrected within each subset."""
    import pandas as pd
    rows = []
    for label, mask in subsets.items():
        sub = pair_summary[mask]
        block = []
        for k in indices:
            if len(sub) < 2:
                continue
            block.append({"subset": label, "index": k, **paired_summary(sub[f"{k}_diff"], rng, n_boot)})
        if block:
            adj = holm([b["wilcoxon_p"] for b in block])
            for b, a in zip(block, adj):
                b["holm_p"] = float(a)
            rows.extend(block)
    return pd.DataFrame(rows)
