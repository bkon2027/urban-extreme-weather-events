"""Pure rules for the urban-rural extreme-weather comparison.

Nothing in this module touches files, the network or the terminal: every function takes
Python/pandas values and returns values, so each rule can be unit-tested directly.

Station data frames passed in here have columns: date (datetime64), TMAX, TMIN (deg C), PRCP (mm),
with QC-flagged or missing values already set to NaN by io.read_station_csv.
"""
from __future__ import annotations

import calendar
from collections.abc import Iterable

import numpy as np
import pandas as pd

ELEMENTS = ("TMAX", "TMIN", "PRCP")
INDICES = ("hot_days", "warm_nights", "heavy_rain_days", "cold_nights")


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def coverage_by_year(station: pd.DataFrame, years: Iterable[int]) -> dict[str, dict[int, float]]:
    """Fraction of days with a valid value, per element and year (0.0 for absent elements)."""
    years = list(years)
    if station.empty:
        return {e: {y: 0.0 for y in years} for e in ELEMENTS}
    yr = station["date"].dt.year
    out = {}
    for e in ELEMENTS:
        if e not in station:
            out[e] = {y: 0.0 for y in years}
            continue
        counts = station.loc[station[e].notna()].groupby(yr[station[e].notna()]).size()
        out[e] = {y: float(counts.get(y, 0)) / days_in_year(y) for y in years}
    return out


def good_years(cov_urban: dict, cov_rural: dict, years: Iterable[int], threshold: float) -> list[int]:
    """Years in which BOTH stations meet the coverage threshold for EVERY element."""
    return [y for y in years
            if all(cov_urban[e][y] >= threshold and cov_rural[e][y] >= threshold for e in ELEMENTS)]


def rural_thresholds(rural: pd.DataFrame, years: Iterable[int], settings: dict) -> dict[str, float]:
    """Event thresholds computed from the RURAL station over the pair's usable years.

    Using the rural station's distribution for both stations is what lets the comparison work:
    a station's own percentile would give every station ~10% hot days by construction.
    """
    r = rural[rural["date"].dt.year.isin(list(years))]
    if r.empty:
        raise ValueError("no rural data in the requested years")
    wet = r.loc[r["PRCP"] >= settings["wet_day_mm"], "PRCP"]
    if wet.empty:
        raise ValueError("rural station has no wet days in the requested years")
    return {
        "hot_days": float(np.nanpercentile(r["TMAX"], settings["hot_pct"])),
        "warm_nights": float(np.nanpercentile(r["TMIN"], settings["warm_pct"])),
        "heavy_rain_days": float(np.nanpercentile(wet, settings["heavy_rain_pct"])),
        "cold_nights": float(np.nanpercentile(r["TMIN"], settings["cold_pct"])),
    }


def _rate(values: pd.Series, mask: pd.Series) -> float:
    """Events per 365 valid days (normalizes for up to 10% missing days)."""
    n = int(values.notna().sum())
    return 365.0 * int(mask.sum()) / n if n else float("nan")


def annual_rates(station: pd.DataFrame, thresholds: dict[str, float], years: Iterable[int]) -> pd.DataFrame:
    """Event rate per year for each index. Exceedance is strict: a value equal to the threshold is not an event."""
    rows = []
    yr = station["date"].dt.year
    for y in years:
        s = station[yr == y]
        rows.append({
            "year": y,
            "hot_days": _rate(s["TMAX"], s["TMAX"] > thresholds["hot_days"]),
            "warm_nights": _rate(s["TMIN"], s["TMIN"] > thresholds["warm_nights"]),
            "heavy_rain_days": _rate(s["PRCP"], s["PRCP"] > thresholds["heavy_rain_days"]),
            "cold_nights": _rate(s["TMIN"], s["TMIN"] < thresholds["cold_nights"]),
        })
    return pd.DataFrame(rows, columns=["year", *INDICES])


def pair_year_differences(urban: pd.DataFrame, rural: pd.DataFrame, settings: dict) -> tuple[pd.DataFrame, list[int]]:
    """Urban-minus-rural event rates per usable year, plus the list of usable years."""
    years = list(range(settings["start_year"], settings["end_year"] + 1))
    usable = good_years(coverage_by_year(urban, years), coverage_by_year(rural, years),
                        years, settings["coverage_threshold"])
    if not usable:
        return pd.DataFrame(columns=["year", *INDICES]), []
    thr = rural_thresholds(rural, usable, settings)
    u, r = annual_rates(urban, thr, usable), annual_rates(rural, thr, usable)
    diff = u[list(INDICES)] - r[list(INDICES)]
    diff.insert(0, "year", usable)
    for k in INDICES:
        diff[f"{k}_rural"] = r[k].to_numpy()
    return diff, usable
