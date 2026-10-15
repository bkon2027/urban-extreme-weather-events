"""Figures. Each function takes result tables and returns a matplotlib Figure; io.save_figure writes it."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BLUE, GREY, INK, INK2, GRID, SURF = "#2a78d6", "#9a9994", "#0b0b0b", "#52514e", "#d9d8d4", "#fcfcfb"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})


def _clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_axisbelow(True)


def ranking(top, title: str, xlabel: str):
    """Horizontal dot-and-interval chart of the top-ranked pairs; airport urban stations drawn as open markers."""
    n = len(top)
    fig, ax = plt.subplots(figsize=(9, 0.45 * n + 1.6))
    y = np.arange(n)[::-1]
    ax.axvline(0, color=INK2, lw=1)
    for yi, r in zip(y, top.itertuples()):
        ax.plot([r.ci_low, r.ci_high], [yi, yi], color=BLUE, lw=2, solid_capstyle="round")
        filled = not getattr(r, "urban_airport", False)
        ax.plot(r.mean_diff, yi, "o", ms=8, color=BLUE, mfc=BLUE if filled else SURF, mew=2)
        ax.text(r.ci_high + 1, yi, f"{r.mean_diff:+.0f}", va="center", color=INK, fontsize=9.5)
    ax.set_yticks(y, [f"{r.rank}. {r.urban_area}" for r in top.itertuples()], color=INK, fontsize=10)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", color=GRID, lw=0.6)
    _clean(ax); ax.spines["left"].set_visible(False)
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=12.5)
    fig.text(0.01, 0.01, "Dot: mean over usable years. Line: 95% bootstrap CI across years. Open dot: urban station is an airport.",
             color=INK2, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    return fig


def distance_check(pairs, index: str, ylabel: str, rho: float, p: float):
    """Urban-minus-rural difference against the rural station's distance outside the urban edge."""
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ok = pairs["passes_buffer"]
    ax.axhline(0, color=INK2, lw=1)
    ax.scatter(pairs.loc[ok, "rural_edge_km"], pairs.loc[ok, f"{index}_diff"], s=44, color=BLUE, edgecolor=SURF, lw=1.5,
               label="passes size-scaled buffer", zorder=3)
    ax.scatter(pairs.loc[~ok, "rural_edge_km"], pairs.loc[~ok, f"{index}_diff"], s=44, facecolor=SURF, edgecolor=GREY, lw=1.5,
               label="fails buffer (rural station close to city)", zorder=3)
    ax.set_xlabel("Rural station's distance outside the urban-area edge (km)")
    ax.set_ylabel(ylabel)
    ax.grid(color=GRID, lw=0.6); _clean(ax)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.suptitle("Urban-influence check: does the gap grow when the rural station is farther from the city?\n"
                 f"Spearman rho = {rho:+.2f}, p = {p:.2f} (no trend means nearby cities are not warming the rural stations)",
                 x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return fig


def robustness(tests, index: str, title: str):
    """Mean difference with CI for each subset of pairs, for one index."""
    t = tests[tests["index"] == index].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(t) + 1.6))
    y = np.arange(len(t))[::-1]
    ax.axvline(0, color=INK2, lw=1)
    for yi, r in zip(y, t.itertuples()):
        ax.plot([r.ci_low, r.ci_high], [yi, yi], color=BLUE, lw=2, solid_capstyle="round")
        ax.plot(r.mean_diff, yi, "o", ms=8, color=BLUE, mec=SURF, mew=2)
        p = "p<0.001" if r.holm_p < 0.001 else f"p={r.holm_p:.3f}"
        ax.text(r.ci_high + 0.8, yi, f"{r.mean_diff:+.1f}/yr ({p}, n={r.n_pairs})", va="center", color=INK, fontsize=9.5)
    ax.set_yticks(y, list(t["subset"]), color=INK, fontsize=10)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Urban minus rural, events per year (mean, 95% bootstrap CI; Holm-corrected p)")
    ax.grid(axis="x", color=GRID, lw=0.6); _clean(ax); ax.spines["left"].set_visible(False)
    lo, hi = t["ci_low"].min(), t["ci_high"].max()
    ax.set_xlim(min(-2, lo - 1), hi + (hi - min(0, lo)) * 0.6)
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=12.5)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig
