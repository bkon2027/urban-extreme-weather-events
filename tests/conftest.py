import numpy as np
import pandas as pd
import pytest


def make_station(years, tmax=25.0, tmin=10.0, prcp=0.0, drop_frac=0.0, seed=0):
    """Synthetic daily station frame (date, TMAX, TMIN, PRCP) for whole calendar years."""
    dates = pd.date_range(f"{min(years)}-01-01", f"{max(years)}-12-31", freq="D")
    dates = dates[dates.year.isin(list(years))]
    df = pd.DataFrame({"date": dates, "TMAX": float(tmax), "TMIN": float(tmin), "PRCP": float(prcp)})
    if drop_frac:
        rng = np.random.default_rng(seed)
        df.loc[rng.random(len(df)) < drop_frac, ["TMAX", "TMIN", "PRCP"]] = np.nan
    return df


@pytest.fixture
def settings():
    return {"start_year": 2015, "end_year": 2016, "coverage_threshold": 0.9, "hot_pct": 90, "warm_pct": 90,
            "cold_pct": 10, "heavy_rain_pct": 95, "wet_day_mm": 1.0}
