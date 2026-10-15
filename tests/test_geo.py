import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from ewu import geo, stats


def test_haversine_one_degree_of_latitude_is_about_111_km():
    assert geo.haversine_km(35.0, -80.0, 36.0, -80.0) == pytest.approx(111.2, abs=0.3)


def test_distance_to_edge_is_zero_inside_and_correct_outside():
    square = box(-80.0, 35.0, -79.9, 35.1)                       # ~9 x 11 km
    assert geo.distance_to_edge_km(35.05, -79.95, square) == 0.0
    # 0.1 degree of latitude north of the box's top edge ~ 11.06 km
    assert geo.distance_to_edge_km(35.2, -79.95, square) == pytest.approx(11.06, abs=0.15)


def test_effective_radius_of_a_circle_area():
    area = np.pi * (12_000.0 ** 2)
    assert geo.effective_radius_km(area) == pytest.approx(12.0)
    with pytest.raises(ValueError):
        geo.effective_radius_km(0)


def test_buffer_scales_with_city_size_and_boundary_is_inclusive():
    assert geo.required_buffer_km(6.0) == 10.0                   # small town: 10 km floor
    assert geo.required_buffer_km(40.0) == 20.0                  # big city: half its radius
    assert geo.passes_buffer(20.0, 40.0) and not geo.passes_buffer(19.9, 40.0)


def test_coast_distance_finds_ocean_and_caps_when_none():
    # fake world: ocean everywhere east of longitude -80.0
    is_land = lambda lats, lons: np.asarray(lons) < -80.0
    d = geo.coast_distance_km(35.0, -80.2, is_land, max_km=60, step_km=1)
    assert d == pytest.approx(0.2 * 111.32 * np.cos(np.radians(35)), abs=1.5)
    assert geo.coast_distance_km(35.0, -80.2, lambda a, b: np.ones_like(a, bool), max_km=60) == 60.0


def test_coastal_mismatch_only_when_exactly_one_station_is_near_the_sea():
    assert geo.coastal_mismatch(5, 40) and geo.coastal_mismatch(40, 5)
    assert not geo.coastal_mismatch(5, 10) and not geo.coastal_mismatch(60, 80)


@pytest.mark.parametrize("sid,name,expected", [
    ("USW00012839", "MIAMI INTL AP", True),
    ("USW00014820", "CLEVELAND", True),            # confirmed by coordinates
    ("USW00023062", "DENVER-STAPLETON", False),     # closed airport
    ("USC00317079", "RALEIGH STATE UNIV", False),
    ("USW00023009", "ROSWELL IND AIR PK", True),
])
def test_airport_flags(sid, name, expected):
    assert geo.is_airport(sid, name) is expected


def test_ranking_orders_pairs_and_gives_a_ci_per_pair():
    py = pd.DataFrame({"urban_area": ["A"] * 5 + ["B"] * 5 + ["C"] * 1,
                       "warm_nights": [10, 12, 11, 9, 13, 30, 31, 29, 32, 28, 99]})
    r = stats.rank_pairs(py, "warm_nights", np.random.default_rng(0), n_boot=500)
    assert list(r["urban_area"]) == ["B", "A"]                  # C dropped: one year only
    assert list(r["rank"]) == [1, 2]
    b = r.iloc[0]
    assert b.ci_low <= b.mean_diff <= b.ci_high and b.mean_diff == pytest.approx(30.0)


def test_subset_tests_apply_holm_within_each_subset():
    ps = pd.DataFrame({"warm_nights_diff": np.r_[np.full(10, 5.0), np.full(10, 6.0)] + np.arange(20) * 0.01,
                       "hot_days_diff": np.linspace(-1, 1, 20)})
    masks = {"all": pd.Series(True, index=ps.index), "half": pd.Series([True] * 10 + [False] * 10)}
    t = stats.subset_tests(ps, masks, ["warm_nights", "hot_days"], np.random.default_rng(0), n_boot=300)
    assert set(t["subset"]) == {"all", "half"} and (t["holm_p"] >= t["wilcoxon_p"]).all()
    assert t.set_index(["subset", "index"]).loc[("half", "warm_nights"), "n_pairs"] == 10


def test_interior_west_needs_west_longitude_and_inland_on_both_stations():
    assert geo.is_interior_west(-112.0, 100.0, 100.0)            # Salt Lake City-like
    assert not geo.is_interior_west(-99.0, 100.0, 100.0)         # Kansas: east of 104W
    assert not geo.is_interior_west(-122.0, 30.0, 100.0)         # coastal California
    assert not geo.is_interior_west(-104.0, 100.0, 100.0)        # boundary: strictly west
