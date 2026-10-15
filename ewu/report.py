"""Build docs/RESULTS.md from the result tables. Pure: tables in, Markdown text out.

Every number and every "significant / not significant" phrase is computed from the tables,
so the page cannot drift from the data when the pipeline is rerun.
"""
from __future__ import annotations

import pandas as pd

ALPHA = 0.05
LABEL = {"hot_days": "hot days", "warm_nights": "warm nights", "heavy_rain_days": "heavy-rain days", "cold_nights": "cold nights"}
SUBSETS = ["All pairs", "Rural station beyond size-scaled buffer", "Coast-matched pairs", "Urban station not an airport",
           "Excluding interior West", "Buffer + coast-matched", "Buffer + coast-matched, excluding interior West",
           "Buffer + coast-matched + non-airport"]


def p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def signed(x: float, nd: int = 1) -> str:
    return f"{x:+.{nd}f}".replace("-", "−")


def md_table(df: pd.DataFrame, align: str | None = None) -> str:
    """Minimal Markdown table (no extra dependency). align: one of 'l'/'r' per column."""
    align = align or "l" * len(df.columns)
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    rule = "|" + "|".join(":---" if a == "l" else "---:" for a in align) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, rule, *rows])


def effect_sentence(r, what: str) -> str:
    sig = r.holm_p < ALPHA
    core = (f"{signed(r.mean_diff)} {what} per year (95% CI {signed(r.ci_low)} to {signed(r.ci_high)}; Holm {p_text(r.holm_p)}; "
            f"urban higher in {r.share_urban_higher:.0%} of {int(r.n_pairs)} pairs)")
    return core if sig else core + ", which is **not statistically significant**"


def build(overall: pd.DataFrame, tests: pd.DataFrame, influence: pd.DataFrame, ranking: pd.DataFrame,
          pairs: pd.DataFrame, meta: dict, top_n: int = 10, ranking_no_west: pd.DataFrame | None = None) -> str:
    o = overall.set_index("index")
    t = tests.set_index(["subset", "index"])
    inf = influence.set_index("index")
    rk = meta["rank_index"]
    n_pairs, n_years = len(pairs), int(pairs["n_years"].sum())
    w, h = o.loc["warm_nights"], o.loc["hot_days"]

    def sub(label, k):
        return t.loc[(label, k)] if (label, k) in t.index else None

    # --- key findings -------------------------------------------------------------------------
    findings = [f"- **Warm nights.** Urban stations recorded {effect_sentence(w, 'warm nights')}."]
    h_na = sub("Urban station not an airport", "hot_days")
    hot = f"- **Hot days.** Urban stations recorded {effect_sentence(h, 'hot days')}."
    if h_na is not None and h.holm_p < ALPHA and h_na.holm_p >= ALPHA:
        hot += (f" The effect largely disappears when the urban station is not an airport "
                f"({signed(h_na.mean_diff)}/yr, Holm {p_text(h_na.holm_p)}, n = {int(h_na.n_pairs)}), so much of it is an airport effect.")
    findings.append(hot)
    null = [LABEL[k] for k in ("heavy_rain_days", "cold_nights") if o.loc[k, "holm_p"] >= ALPHA]
    if null:
        findings.append(f"- **No clear urban effect** on {' or '.join(null)} (Holm p ≥ {ALPHA}).")
    rho, p_inf = inf.loc[rk, "spearman_rho_vs_rural_edge_km"], inf.loc[rk, "p"]
    n_buf = int(pairs["passes_buffer"].sum())
    contaminated = p_inf < ALPHA and rho > 0
    findings.append(
        f"- **Urban influence on rural stations.** The gap in {LABEL[rk]} does {'' if contaminated else 'not '}grow with the rural "
        f"station's distance from the city (Spearman ρ = {signed(rho, 2)}, {p_text(p_inf)}), so there is "
        f"{'evidence' if contaminated else 'no evidence'} that cities warm their rural partners enough to bias the comparison. "
        f"{n_buf} of {n_pairs} pairs pass the size-scaled buffer.")
    iw = sub("Excluding interior West", rk)
    n_iw = int(pairs["interior_west"].sum()) if "interior_west" in pairs else 0
    if iw is not None and n_iw:
        findings.append(
            f"- **Terrain sensitivity.** Excluding the {n_iw} interior-West pairs (mountain and basin terrain, where valley sites "
            f"pool cold air at night), the effect on {LABEL[rk]} is {signed(iw.mean_diff)}/yr (95% CI {signed(iw.ci_low)} to "
            f"{signed(iw.ci_high)}; Holm {p_text(iw.holm_p)}; n = {int(iw.n_pairs)}), so the result "
            f"{'does not depend' if iw.holm_p < ALPHA and iw.mean_diff > 0 else 'depends'} on those pairs.")
    rob = [s for s in SUBSETS[1:] if sub(s, rk) is not None and sub(s, rk).holm_p < ALPHA]
    fail = [s for s in SUBSETS[1:] if sub(s, rk) is not None and sub(s, rk).holm_p >= ALPHA]
    line = f"- **Robustness.** The effect on {LABEL[rk]} stays significant in {len(rob)} of {len(rob) + len(fail)} robustness subsets"
    if fail:
        worst = sub(fail[-1], rk)
        line += (f"; in the strictest subset ({fail[-1].lower()}, n = {int(worst.n_pairs)}) it stays positive "
                 f"({signed(worst.mean_diff)}/yr) but is not significant" if worst.mean_diff > 0 else
                 f"; it is not significant in: {', '.join(fail).lower()}")
    findings.append(line + ".")
    top3 = ", ".join(ranking.head(3)["urban_area"])
    findings.append(f"- **Largest urban excess of {LABEL[rk]}** among {len(ranking)} vetted pairs: {top3} (see the ranking below).")

    # --- tables -----------------------------------------------------------------------------------
    t1 = pd.DataFrame({
        "Index": [LABEL[k].capitalize() for k in overall["index"]],
        "Rural mean (days/yr)": overall["rural_mean_per_yr"].map("{:.1f}".format),
        "Urban − rural (95% CI)": [f"{signed(m)} ({signed(a)} to {signed(b)})" for m, a, b in
                                   zip(overall["mean_diff"], overall["ci_low"], overall["ci_high"])],
        "Median": overall["median_diff"].map(signed),
        "Pairs urban higher": overall["share_urban_higher"].map("{:.0%}".format),
        "Holm p": overall["holm_p"].map(lambda p: "< 0.001" if p < 0.001 else f"{p:.3f}"),
    })
    rows = []
    for s in SUBSETS:
        cells = [s, str(int(sub(s, rk).n_pairs)) if sub(s, rk) is not None else "–"]
        for k in (rk, "hot_days" if rk != "hot_days" else "warm_nights"):
            r = sub(s, k)
            cells.append("–" if r is None else f"{signed(r.mean_diff)} ({'< 0.001' if r.holm_p < 0.001 else f'{r.holm_p:.3f}'})")
        rows.append(cells)
    other = "hot_days" if rk != "hot_days" else "warm_nights"
    t2 = pd.DataFrame(rows, columns=["Subset of pairs", "Pairs", f"{LABEL[rk].capitalize()}: Δ/yr (Holm p)",
                                     f"{LABEL[other].capitalize()}: Δ/yr (Holm p)"])
    top = ranking.head(top_n)
    t3 = pd.DataFrame({
        "Rank": top["rank"], "Urban area": top["urban_area"], "Size": top["size_group"],
        f"Extra {LABEL[rk]}/yr (95% CI)": [f"{signed(m, 0)} ({signed(a, 0)} to {signed(b, 0)})"
                                           for m, a, b in zip(top["mean_diff"], top["ci_low"], top["ci_high"])],
        "Airport urban station": top["urban_airport"].map({True: "yes", False: "no"}),
    })
    n_west = int(ranking.head(5)["interior_west"].sum()) if "interior_west" in ranking else 0
    alt = ""
    if ranking_no_west is not None and len(ranking_no_west):
        t4 = ranking_no_west.head(top_n)
        t4 = pd.DataFrame({
            "Rank": t4["rank"], "Urban area": t4["urban_area"], "Size": t4["size_group"],
            f"Extra {LABEL[rk]}/yr (95% CI)": [f"{signed(m, 0)} ({signed(a, 0)} to {signed(b, 0)})"
                                               for m, a, b in zip(t4["mean_diff"], t4["ci_low"], t4["ci_high"])],
            "Airport urban station": t4["urban_airport"].map({True: "yes", False: "no"}),
        })
        alt = f"""
**The same ranking without the interior West** (a terrain sensitivity check):

{md_table(t4, "rllrl")}
"""

    # --- page -------------------------------------------------------------------------------------
    return f"""# Results: does urbanization change how often places experience extreme weather?

*Generated by `python -m ewu.cli --config config/ewu.json --stage report` on {meta['date']} from commit `{meta['commit']}`.
Every number on this page is computed from the pipeline's result tables; rerunning the pipeline regenerates it.*

**Design in one line:** {n_pairs} pairs of NOAA weather stations ({n_years} station-pair-years, {meta['years']}): one inside a Census
urban area, one rural partner 20–75 km away at similar elevation. Extreme-event thresholds come from the rural station and apply
to both, so the difference measures what the city adds.

## Key findings

{chr(10).join(findings)}

## 1. How much more often do cities see extremes?

![Urban minus rural events per year for four indices](figures/effects_by_index.png)

{md_table(t1, "lrrrrr")}

*Differences are events per year (per 365 valid days). CI: 95% bootstrap over pairs. p: Wilcoxon signed-rank test,
Holm-corrected across the four indices.*

## 2. Where the pairs are

![Map of station pairs coloured by the urban excess of {LABEL[rk]}](figures/map_{rk}.png)

## 3. Do large cities warm their rural partners?

Reviewers asked whether big cities heat the surrounding countryside enough to shrink the measured gap. If so, pairs whose
rural station sits just outside the city should show smaller gaps than pairs whose rural station is farther out.

![Urban minus rural {LABEL[rk]} against the rural station's distance from the urban edge](figures/urban_influence_check.png)

Spearman ρ = {signed(rho, 2)} ({p_text(p_inf)}): {'the gap rises with distance, consistent with urban influence on the nearest rural stations.' if contaminated else 'no relationship, so there is no sign that nearby cities are inflating rural temperatures.'}
A size-scaled buffer (rural station at least max(10 km, half the city's effective radius) outside the urban edge) keeps
{n_buf} of {n_pairs} pairs; results for that subset are in the next table.

## 4. Robustness

{md_table(t2, "lrrr")}

![Robustness of the {LABEL[rk]} effect across subsets](figures/robustness_{rk}.png)

*Coast-matched: excludes pairs where exactly one station is within {meta['coast_near_km']:.0f} km of the ocean.
Non-airport: urban station is not at an airport. Interior West: west of 104°W with no ocean within 100 km of either
station (mountain and basin terrain).*

## 5. Where does urbanization add the most {LABEL[rk]}?

Ranking of the {len(ranking)} pairs that pass the buffer and are coast-matched, by the urban excess of {LABEL[rk]}
(CI: 95% bootstrap across each pair's years).

![Top {len(top)} urban areas by urban excess of {LABEL[rk]}](figures/ranking_{rk}.png)

{md_table(t3, "rllrl")}

**Read with care.** Each row is one pair of stations, so a ranking reflects that pair's specific sites as well as the city.
{n_west} of the top 5 are in the interior West (west of 104°W, more than 100 km from the ocean), where cold air pooling in
valleys at rural sites can widen night-time gaps. Terrain is not modelled directly, so the ranking is repeated without
those pairs below. This ranks where urbanization adds the most {LABEL[rk]} today in this sample; it is not a forecast.
{alt}

## Methods in brief

- **Data:** NOAA GHCN-Daily (TMAX, TMIN, PRCP), {meta['years']}; Census 2020 urban areas (boundaries, population, density).
- **Coverage:** a station-year counts if both stations have ≥ {meta['coverage_threshold']:.0%} valid days for all three elements;
  pairs need ≥ {meta['min_good_years']} usable years. Values with a GHCN quality flag are treated as missing.
- **Events:** hot day = TMAX above the rural 90th percentile; warm night = TMIN above the rural 90th percentile;
  heavy-rain day = precipitation above the rural 95th percentile of wet days; cold night = TMIN below the rural 10th percentile.

## Limitations

- Many urban stations are at airports; the hot-day signal depends heavily on them.
- Terrain (valleys, cold-air pooling) is not modelled directly; it is tested only by excluding interior-West pairs.
  A topographic position index from a digital elevation model would be the next step. The coast flag uses the ocean
  only (Great Lakes not flagged).
- {n_pairs} pairs is a sample, not every U.S. city; the strictest robustness subset is small.
- Ten years is too short to estimate trends: results describe {meta['years']}, not the future.

## Reproduce

```bash
python -m pip install -e ".[dev]"
python -m ewu.cli --config config/ewu.json     # fetch, analyze, report
```
"""
