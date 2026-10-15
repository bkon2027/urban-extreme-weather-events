"""Command-line entry point:  python -m ewu.cli --config config/ewu.json [--stage fetch|analyze|all]

Settings resolve CLI > config file > defaults in one function (resolve), are validated once
(validate), and every run logs the command, effective settings, Git commit, counts and outputs.
Exit status: 0 success, 1 a run error (bad config, missing input, failed downloads), 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from ewu import core, geo, io, plots, report, stats

log = logging.getLogger("ewu.cli")
ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "start_year": 2015, "end_year": 2024, "coverage_threshold": 0.90, "min_good_years": 8,
    "hot_pct": 90, "warm_pct": 90, "cold_pct": 10, "heavy_rain_pct": 95, "wet_day_mm": 1.0,
    "seed": 703, "n_boot": 10_000,
    "buffer_min_km": 10.0, "buffer_radius_fraction": 0.5, "coast_near_km": 25.0, "rank_index": "warm_nights", "top_n": 10,
    "pairs": "config/final_pairs.csv", "raw_dir": "data/raw", "reference_dir": "data/reference",
    "manifest": "data_manifest.csv", "results_dir": "results", "docs_dir": "docs",
}
PATH_KEYS = ("pairs", "raw_dir", "reference_dir", "manifest", "results_dir", "docs_dir")


class ConfigError(ValueError):
    pass


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ewu", description="Urban vs. rural extreme-weather frequency from paired NOAA stations.")
    p.add_argument("--config", help="JSON settings file (e.g. config/ewu.json)")
    p.add_argument("--stage", choices=["fetch", "analyze", "report", "all"], default="all",
                   help="fetch: download data; analyze: compute result tables; report: figures + docs/RESULTS.md; all (default)")
    p.add_argument("--coverage-threshold", type=float, help="minimum share of valid days per station-year (default 0.90)")
    p.add_argument("--min-good-years", type=int, help="minimum usable years for a pair to be kept (default 8)")
    p.add_argument("--seed", type=int, help="random seed for bootstrap CIs (default 703)")
    p.add_argument("--verbose", action="store_true", help="show DEBUG log lines")
    return p.parse_args(argv)


def load_config(path: str | None) -> dict:
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ConfigError(f"{path} is not valid JSON: {err}") from err
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown setting(s) in {path}: {sorted(unknown)}")
    return cfg


def resolve(args: argparse.Namespace, cfg: dict) -> dict:
    """CLI beats file beats default."""
    s = dict(DEFAULTS)
    s.update(cfg)
    for key in ("coverage_threshold", "min_good_years", "seed"):
        val = getattr(args, key)
        if val is not None:
            s[key] = val
    for key in PATH_KEYS:
        s[key] = str((ROOT / s[key]).resolve()) if not Path(s[key]).is_absolute() else s[key]
    return s


def validate(s: dict, stage: str) -> None:
    if not 0 < s["coverage_threshold"] <= 1:
        raise ConfigError(f"coverage_threshold must be in (0, 1]; got {s['coverage_threshold']}")
    if s["start_year"] > s["end_year"]:
        raise ConfigError(f"start_year {s['start_year']} is after end_year {s['end_year']}")
    span = s["end_year"] - s["start_year"] + 1
    if not 1 <= s["min_good_years"] <= span:
        raise ConfigError(f"min_good_years must be between 1 and {span}; got {s['min_good_years']}")
    for key in ("hot_pct", "warm_pct", "cold_pct", "heavy_rain_pct"):
        if not 0 < s[key] < 100:
            raise ConfigError(f"{key} must be between 0 and 100; got {s[key]}")
    if s["rank_index"] not in core.INDICES:
        raise ConfigError(f"rank_index must be one of {list(core.INDICES)}; got {s['rank_index']!r}")
    if s["buffer_min_km"] < 0 or not 0 <= s["buffer_radius_fraction"] <= 5:
        raise ConfigError("buffer_min_km must be >= 0 and buffer_radius_fraction between 0 and 5")
    if not Path(s["pairs"]).exists():
        raise ConfigError(f"pairs file not found: {s['pairs']}")


def setup_logging(verbose: bool, log_file: Path | None) -> None:
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def stage_fetch(s: dict, pairs: list[dict]) -> int:
    stations = [p["urban_station"] for p in pairs] + [p["rural_station"] for p in pairs]
    combined = sorted(Path(s["raw_dir"]).parent.glob("stations_part*.csv"))
    if combined:
        n = len(io.split_combined_station_files(combined, Path(s["raw_dir"])))
        log.info("split %d browser-downloaded station files from %d combined CSVs", n, len(combined))
    failures = io.fetch_all(stations, Path(s["raw_dir"]), Path(s["reference_dir"]), Path(s["manifest"]),
                            s["start_year"], s["end_year"])
    if failures:
        for name, err in failures:
            log.error("download failed: %s (%s)", name, err)
        log.error("%d downloads failed; re-run to retry (finished files are kept)", len(failures))
        return 1
    log.info("fetch complete: %d stations in %s", len(set(stations)), s["raw_dir"])
    return 0


def iter_pair_results(pairs: list[dict], s: dict) -> Iterator[tuple[dict, pd.DataFrame, list[int]]]:
    """Process one pair at a time so memory stays bounded."""
    raw = Path(s["raw_dir"])
    for p in pairs:
        urban = io.read_station_csv(raw / f"{p['urban_station']}.csv")
        rural = io.read_station_csv(raw / f"{p['rural_station']}.csv")
        diff, usable = core.pair_year_differences(urban, rural, s)
        yield p, diff, usable


def add_site_flags(pair_summary: pd.DataFrame, s: dict) -> pd.DataFrame:
    """Urban-influence buffer, coast distance and airport flags for each pair (see ewu.geo for the rules)."""
    from global_land_mask import globe
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    ref = Path(s["reference_dir"])
    stations = list(pair_summary["urban_station"]) + list(pair_summary["rural_station"])
    meta = io.read_station_metadata(ref / "ghcnd-stations.txt", stations)
    areas = io.read_urban_areas(ref / "tl_2020_us_uac20.zip")
    tree = STRtree([a["geom"] for a in areas])
    coast = {sid: geo.coast_distance_km(m["lat"], m["lon"], globe.is_land) for sid, m in meta.items()}

    rows = []
    for p in pair_summary.itertuples():
        u, r = meta[p.urban_station], meta[p.rural_station]
        upt = Point(u["lon"], u["lat"])
        home = [areas[i] for i in tree.query(upt) if areas[i]["geom"].contains(upt)]
        if not home:
            raise ValueError(f"{p.urban_area}: urban station {p.urban_station} is not inside any Census urban area")
        area = home[0]
        edge = geo.distance_to_edge_km(r["lat"], r["lon"], area["geom"])
        radius = geo.effective_radius_km(area["aland"])
        near = tree.query(Point(r["lon"], r["lat"]).buffer(1.5))
        any_edge = min((geo.distance_to_edge_km(r["lat"], r["lon"], areas[i]["geom"]) for i in near), default=float("nan"))
        rows.append({
            "urban_area_census": area["name"], "ua_radius_km": radius, "rural_edge_km": edge,
            "required_buffer_km": geo.required_buffer_km(radius, s["buffer_min_km"], s["buffer_radius_fraction"]),
            "passes_buffer": geo.passes_buffer(edge, radius, s["buffer_min_km"], s["buffer_radius_fraction"]),
            "rural_nearest_any_ua_km": any_edge,
            "urban_coast_km": coast[p.urban_station], "rural_coast_km": coast[p.rural_station],
            "coastal_mismatch": geo.coastal_mismatch(coast[p.urban_station], coast[p.rural_station], s["coast_near_km"]),
            "urban_airport": geo.is_airport(p.urban_station, u["name"]), "rural_airport": geo.is_airport(p.rural_station, r["name"]),
            "urban_station_name": u["name"], "rural_station_name": r["name"],
            "urban_lat": u["lat"], "urban_lon": u["lon"], "rural_lat": r["lat"], "rural_lon": r["lon"],
        })
    return pd.concat([pair_summary.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def robustness_and_ranking(pair_summary: pd.DataFrame, pair_years: pd.DataFrame, s: dict, out: Path) -> None:
    from scipy import stats as sps

    rng = np.random.default_rng(s["seed"] + 1)
    clean = pair_summary["passes_buffer"] & ~pair_summary["coastal_mismatch"]
    subsets = {
        "All pairs": pd.Series(True, index=pair_summary.index),
        "Rural station beyond size-scaled buffer": pair_summary["passes_buffer"],
        "Coast-matched pairs": ~pair_summary["coastal_mismatch"],
        "Urban station not an airport": ~pair_summary["urban_airport"],
        "Buffer + coast-matched": clean,
        "Buffer + coast-matched + non-airport": clean & ~pair_summary["urban_airport"],
    }
    tests = stats.subset_tests(pair_summary, subsets, core.INDICES, rng, s["n_boot"])
    io.write_csv(tests, out / "robustness_tests.csv")
    for label, mask in subsets.items():
        log.info("subset %-42s n=%d", label, int(mask.sum()))

    influence = []
    for k in core.INDICES:
        rho, p = sps.spearmanr(pair_summary["rural_edge_km"], pair_summary[f"{k}_diff"])
        influence.append({"index": k, "spearman_rho_vs_rural_edge_km": float(rho), "p": float(p), "n_pairs": len(pair_summary)})
    influence = pd.DataFrame(influence)
    io.write_csv(influence, out / "urban_influence_check.csv")
    w = influence.set_index("index").loc[s["rank_index"]]
    log.info("urban-influence check (%s vs rural distance outside edge): rho=%+.2f p=%.2f; %d of %d pairs pass the buffer",
             s["rank_index"], w["spearman_rho_vs_rural_edge_km"], w["p"], int(pair_summary["passes_buffer"].sum()), len(pair_summary))

    eligible = set(pair_summary.loc[clean, "urban_area"])
    ranked = stats.rank_pairs(pair_years[pair_years["urban_area"].isin(eligible)], s["rank_index"], rng, s["n_boot"])
    flags = pair_summary[["urban_area", "size_group", "pop", "popden", "urban_airport", "rural_edge_km", "urban_station", "rural_station"]]
    ranked = ranked.merge(flags, on="urban_area", how="left")
    io.write_csv(ranked, out / f"ranking_{s['rank_index']}.csv")
    if len(ranked) < s["top_n"]:
        log.warning("only %d pairs eligible for ranking (fewer than top_n=%d)", len(ranked), s["top_n"])
    top = ranked.head(s["top_n"])
    for r in top.itertuples():
        log.info("rank %2d  %-40s %+6.1f/yr  CI %+.1f..%+.1f%s", r.rank, r.urban_area, r.mean_diff, r.ci_low, r.ci_high,
                 "  [airport]" if r.urban_airport else "")



def stage_analyze(s: dict, pairs: list[dict]) -> int:
    raw = Path(s["raw_dir"])
    missing = [sid for p in pairs for sid in (p["urban_station"], p["rural_station"]) if not (raw / f"{sid}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} station files missing from {raw} (e.g. {missing[0]}); run --stage fetch first")
    ua = io.read_urban_area_list(Path(s["reference_dir"]) / "2020_Census_ua_list_all.xlsx").set_index("NAME")

    year_rows, pair_rows, dropped = [], [], []
    for p, diff, usable in iter_pair_results(pairs, s):
        if len(usable) < s["min_good_years"]:
            dropped.append((p["urban_area"], len(usable)))
            continue
        diff = diff.assign(urban_area=p["urban_area"])
        year_rows.append(diff)
        row = {k: p[k] for k in ("size_group", "urban_area", "urban_station", "rural_station", "distance_km")}
        row.update(pop=ua["POP"].get(p["urban_area"], np.nan), popden=ua["POPDEN"].get(p["urban_area"], np.nan),
                   n_years=len(usable))
        for k in core.INDICES:
            row[f"{k}_diff"] = diff[k].mean()
            row[f"{k}_rural"] = diff[f"{k}_rural"].mean()
        pair_rows.append(row)
    for name, n in dropped:
        log.warning("dropped %s: only %d usable years (< %d)", name, n, s["min_good_years"])

    pair_summary = pd.DataFrame(pair_rows)
    rng = np.random.default_rng(s["seed"])
    overall = []
    for k in core.INDICES:
        r = stats.paired_summary(pair_summary[f"{k}_diff"], rng, s["n_boot"])
        overall.append({"index": k, "rural_mean_per_yr": pair_summary[f"{k}_rural"].mean(), **r})
    overall = pd.DataFrame(overall)
    overall["holm_p"] = stats.holm(overall["wilcoxon_p"])

    out = Path(s["results_dir"])
    pair_years = pd.concat(year_rows, ignore_index=True)
    pair_summary = add_site_flags(pair_summary, s)
    io.write_csv(pair_years, out / "pair_year_differences.csv")
    io.write_csv(pair_summary, out / "pair_summary.csv")
    io.write_csv(overall, out / "results_overall.csv")
    log.info("analyzed %d pairs (%d pair-years); dropped %d", len(pair_summary), int(pair_summary["n_years"].sum()), len(dropped))
    for r in overall.itertuples():
        log.info("%-15s urban-rural %+6.1f/yr  CI %+.1f..%+.1f  Holm p=%.3g", r.index, r.mean_diff, r.ci_low, r.ci_high, r.holm_p)
    robustness_and_ranking(pair_summary, pair_years, s, out)
    log.info("wrote %s", out)
    return 0


def stage_report(s: dict) -> int:
    """Figures and docs/RESULTS.md from the result tables (committed, so the findings show on GitHub)."""
    from datetime import date
    out, docs = Path(s["results_dir"]), Path(s["docs_dir"])
    need = ["results_overall.csv", "pair_summary.csv", "robustness_tests.csv", "urban_influence_check.csv", f"ranking_{s['rank_index']}.csv"]
    missing = [n for n in need if not (out / n).exists()]
    if missing:
        raise FileNotFoundError(f"missing result tables in {out}: {missing}; run --stage analyze first")
    overall, pairs = pd.read_csv(out / need[0]), pd.read_csv(out / need[1])
    tests, influence, ranking = pd.read_csv(out / need[2]), pd.read_csv(out / need[3]), pd.read_csv(out / need[4])
    rk, label, figs = s["rank_index"], s["rank_index"].replace("_", " "), docs / "figures"
    years = f"{s['start_year']}\u2013{s['end_year']}"
    w = influence.set_index("index").loc[rk]
    areas = io.read_urban_areas(Path(s["reference_dir"]) / "tl_2020_us_uac20.zip")
    io.save_figure(plots.effects(overall, len(pairs), years), figs / "effects_by_index.png")
    io.save_figure(plots.pair_map(pairs, [(a["lon"], a["lat"]) for a in areas], rk), figs / f"map_{rk}.png")
    io.save_figure(plots.distance_check(pairs, rk, f"Urban minus rural {label} per year", w["spearman_rho_vs_rural_edge_km"], w["p"]),
                   figs / "urban_influence_check.png")
    io.save_figure(plots.robustness(tests, rk, f"Robustness: extra {label} at urban stations across subsets of pairs"),
                   figs / f"robustness_{rk}.png")
    top = ranking.head(s["top_n"])
    io.save_figure(plots.ranking(top, f"Top {len(top)} urban areas by extra {label} vs. their rural partner, {years}",
                                 f"Urban minus rural {label} per year"), figs / f"ranking_{rk}.png")
    meta = {"date": date.today().isoformat(), "commit": git_commit(), "years": years, "rank_index": rk,
            "coverage_threshold": s["coverage_threshold"], "min_good_years": s["min_good_years"], "coast_near_km": s["coast_near_km"]}
    io.write_text(report.build(overall, tests, influence, ranking, pairs, meta, s["top_n"]), docs / "RESULTS.md")
    log.info("wrote %s and %d figures in %s", docs / "RESULTS.md", 5, figs)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.monotonic()
    try:
        s = resolve(args, load_config(args.config))
        setup_logging(args.verbose, Path(s["results_dir"]) / "run.log")
        validate(s, args.stage)
        log.info("command: %s", " ".join(["python -m ewu.cli", *(argv if argv is not None else sys.argv[1:])]))
        log.info("git commit: %s", git_commit())
        log.info("settings: %s", json.dumps({k: s[k] for k in sorted(s)}))
        pairs = io.read_pairs(Path(s["pairs"]))
        log.info("read %d pairs from %s", len(pairs), s["pairs"])
        if args.stage in ("fetch", "all") and stage_fetch(s, pairs) != 0:
            return 1
        if args.stage in ("analyze", "all"):
            stage_analyze(s, pairs)
        if args.stage in ("report", "all"):
            stage_report(s)
    except (ConfigError, FileNotFoundError, KeyError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    log.info("finished in %.1f s", time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
