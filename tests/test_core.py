import numpy as np
import pandas as pd
import pytest

from ewu import core
from conftest import make_station


def test_leap_year_uses_366_day_denominator():
    st = make_station([2016])
    cov = core.coverage_by_year(st, [2016])
    assert cov["TMAX"][2016] == pytest.approx(1.0)
    assert core.days_in_year(2016) == 366 and core.days_in_year(2015) == 365


def test_coverage_89_percent_rejected_91_kept():
    years = [2015]
    def station_with(valid_days):
        st = make_station(years)
        st.loc[valid_days:, ["TMAX", "TMIN", "PRCP"]] = np.nan
        return core.coverage_by_year(st, years)
    low, high = station_with(int(0.89 * 365)), station_with(int(0.91 * 365) + 1)
    assert core.good_years(low, high, years, 0.90) == []
    assert core.good_years(high, high, years, 0.90) == [2015]


def test_all_missing_station_has_zero_coverage_without_crashing():
    st = make_station([2015])
    st[["TMAX", "TMIN", "PRCP"]] = np.nan
    cov = core.coverage_by_year(st, [2015])
    assert all(cov[e][2015] == 0.0 for e in core.ELEMENTS)


def test_empty_station_frame_gives_zero_coverage():
    empty = pd.DataFrame({"date": pd.to_datetime([]), "TMAX": [], "TMIN": [], "PRCP": []})
    assert core.coverage_by_year(empty, [2015])["PRCP"][2015] == 0.0


def test_value_equal_to_threshold_is_not_an_event():
    st = make_station([2015], tmax=30.0)
    rates = core.annual_rates(st, {"hot_days": 30.0, "warm_nights": 99, "heavy_rain_days": 99, "cold_nights": -99}, [2015])
    assert rates.loc[0, "hot_days"] == 0.0
    rates = core.annual_rates(st, {"hot_days": 29.9, "warm_nights": 99, "heavy_rain_days": 99, "cold_nights": -99}, [2015])
    assert rates.loc[0, "hot_days"] == pytest.approx(365.0)


def test_rates_are_normalized_to_365_valid_days():
    st = make_station([2015], tmax=30.0, drop_frac=0.05, seed=1)
    rates = core.annual_rates(st, {"hot_days": 0.0, "warm_nights": 99, "heavy_rain_days": 99, "cold_nights": -99}, [2015])
    assert rates.loc[0, "hot_days"] == pytest.approx(365.0)


def test_thresholds_come_from_rural_station_and_warmer_urban_gets_more_warm_nights(settings):
    years = [2015, 2016]
    rng = np.random.default_rng(3)
    rural = make_station(years, prcp=2.0)
    rural["TMIN"] = rng.normal(10, 3, len(rural))
    rural["TMAX"] = rural["TMIN"] + 12
    urban = rural.copy()
    urban["TMIN"] = urban["TMIN"] + 2.0          # urban nights 2 C warmer
    diff, usable = core.pair_year_differences(urban, rural, settings)
    assert usable == years
    assert (diff["warm_nights"] > 0).all()        # more warm nights in the city
    assert (diff["cold_nights"] < 0).all()        # negative control: fewer cold nights
    assert diff["hot_days"].abs().max() == pytest.approx(0.0)  # TMAX unchanged
    assert diff["warm_nights_rural"].mean() == pytest.approx(36.5, abs=2)  # rural ~10% by construction


def test_pair_with_no_usable_years_returns_empty(settings):
    years = [2015, 2016]
    urban = make_station(years)
    rural = make_station(years, drop_frac=0.5)
    diff, usable = core.pair_year_differences(urban, rural, settings)
    assert usable == [] and diff.empty


def test_rural_station_without_wet_days_raises(settings):
    rural = make_station([2015], prcp=0.0)
    with pytest.raises(ValueError, match="wet days"):
        core.rural_thresholds(rural, [2015], settings)
