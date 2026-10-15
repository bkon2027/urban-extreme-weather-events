import argparse
import json

import pytest

from ewu import cli


def args(**kw):
    base = {"coverage_threshold": None, "min_good_years": None, "seed": None}
    base.update(kw)
    return argparse.Namespace(**base)


def test_precedence_cli_beats_file_beats_default():
    assert cli.resolve(args(), {})["coverage_threshold"] == 0.90
    assert cli.resolve(args(), {"coverage_threshold": 0.85})["coverage_threshold"] == 0.85
    assert cli.resolve(args(coverage_threshold=0.95), {"coverage_threshold": 0.85})["coverage_threshold"] == 0.95


def test_relative_paths_resolve_from_project_root():
    s = cli.resolve(args(), {})
    assert s["pairs"].endswith("config/final_pairs.csv") and s["pairs"].startswith(str(cli.ROOT))


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0 and "--stage" in capsys.readouterr().out


def test_bad_setting_fails_with_message_and_writes_no_results(tmp_path, capsys):
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps({"coverage_threshold": 1.5, "results_dir": str(tmp_path / "results")}))
    status = cli.main(["--config", str(cfg), "--stage", "analyze"])
    assert status == 1
    assert "coverage_threshold" in capsys.readouterr().err
    assert not (tmp_path / "results" / "results_overall.csv").exists()


def test_unknown_setting_is_rejected(tmp_path, capsys):
    cfg = tmp_path / "typo.json"
    cfg.write_text(json.dumps({"coverage_treshold": 0.9}))
    assert cli.main(["--config", str(cfg)]) == 1
    assert "unknown setting" in capsys.readouterr().err


def test_missing_station_data_tells_you_to_fetch(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"raw_dir": str(tmp_path / "raw"), "results_dir": str(tmp_path / "results")}))
    assert cli.main(["--config", str(cfg), "--stage", "analyze"]) == 1
    assert "--stage fetch" in capsys.readouterr().err


def _write_station(path, sid, tmin_shift, seed):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", "2016-12-31", freq="D")
    tmin = rng.normal(10, 3, len(dates)) + tmin_shift
    prcp = np.where(rng.random(len(dates)) < 0.3, rng.gamma(2, 4, len(dates)), 0.0)
    df = pd.DataFrame({"STATION": sid, "DATE": dates.strftime("%Y-%m-%d"),
                       "PRCP": prcp.round(1), "PRCP_ATTRIBUTES": ",,W",
                       "TMAX": (tmin + 12).round(1), "TMAX_ATTRIBUTES": ",,W",
                       "TMIN": tmin.round(1), "TMIN_ATTRIBUTES": ",,W"})
    df.to_csv(path / f"{sid}.csv", index=False)


def _write_reference_geography(ref):
    """Tiny GHCN station list and Census urban-area zip: three inland Kansas towns, rural partners 30 km north."""
    import zipfile
    import shapefile
    lines, base = [], ref / "tl_2020_us_uac20"
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON) as w:
        for f in ("UACE20", "NAME20"):
            w.field(f, "C", 60)
        w.field("ALAND20", "N", 18, 0)
        w.field("INTPTLAT20", "C", 12)
        w.field("INTPTLON20", "C", 12)
        for i in range(3):
            lat, lon = 38.0, -99.0 + i
            lines.append(f"USW0000000{i} {lat:8.4f} {lon:9.4f} {600.0:6.1f}    TOWN {i} AP")
            lines.append(f"USC0000000{i} {lat + 0.27:8.4f} {lon:9.4f} {610.0:6.1f}    RURAL {i}")
            d = 0.03
            w.poly([[(lon - d, lat - d), (lon - d, lat + d), (lon + d, lat + d), (lon + d, lat - d), (lon - d, lat - d)]])
            w.record(str(i), f"Town {i}", 30_000_000, f"{lat:+.7f}", f"{lon:+.7f}")
    (ref / "ghcnd-stations.txt").write_text("\n".join(l.ljust(85) for l in lines) + "\n")
    with zipfile.ZipFile(ref / "tl_2020_us_uac20.zip", "w") as z:
        for ext in (".shp", ".shx", ".dbf"):
            z.write(base.with_suffix(ext), base.with_suffix(ext).name)


def test_analyze_end_to_end_on_synthetic_pairs(tmp_path, capsys):
    import pandas as pd
    raw, ref = tmp_path / "raw", tmp_path / "ref"
    raw.mkdir(); ref.mkdir()
    rows = []
    for i in range(3):
        u, r = f"USW0000000{i}", f"USC0000000{i}"
        _write_station(raw, u, tmin_shift=2.0, seed=i)       # urban nights warmer
        _write_station(raw, r, tmin_shift=0.0, seed=100 + i)
        rows.append(f"<50k,Town {i},{u},{r},30")
    (tmp_path / "pairs.csv").write_text("size_group,urban_area,urban_station,rural_station,distance_km\n" + "\n".join(rows) + "\n")
    pd.DataFrame({"UACE": [1, 2, 3], "NAME": ["Town 0", "Town 1", "Town 2"], "POP": [10_000, 20_000, 30_000],
                  "POPDEN": [1000.0, 2000.0, 3000.0]}).to_excel(ref / "2020_Census_ua_list_all.xlsx", index=False)
    _write_reference_geography(ref)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"start_year": 2015, "end_year": 2016, "min_good_years": 2, "n_boot": 500, "top_n": 3,
                               "pairs": str(tmp_path / "pairs.csv"), "raw_dir": str(raw), "reference_dir": str(ref),
                               "results_dir": str(tmp_path / "results"), "docs_dir": str(tmp_path / "docs")}))
    assert cli.main(["--config", str(cfg), "--stage", "analyze"]) == 0
    overall = pd.read_csv(tmp_path / "results" / "results_overall.csv").set_index("index")
    assert overall.loc["warm_nights", "mean_diff"] > 0
    assert overall.loc["cold_nights", "mean_diff"] < 0
    summary = pd.read_csv(tmp_path / "results" / "pair_summary.csv")
    assert len(summary) == 3 and summary["popden"].tolist() == [1000.0, 2000.0, 3000.0]
    assert (tmp_path / "results" / "run.log").exists()
    assert summary["passes_buffer"].all() and not summary["coastal_mismatch"].any()
    assert summary["urban_airport"].all() and not summary["rural_airport"].any()
    assert not summary["interior_west"].any()
    assert (tmp_path / "results" / "ranking_warm_nights_excl_interior_west.csv").exists()
    ranking = pd.read_csv(tmp_path / "results" / "ranking_warm_nights.csv")
    assert len(ranking) == 3 and list(ranking["rank"]) == [1, 2, 3]
    assert cli.main(["--config", str(cfg), "--stage", "report"]) == 0
    page = (tmp_path / "docs" / "RESULTS.md").read_text()
    assert "## Key findings" in page and "Town" in page
    for name in ("effects_by_index", "map_warm_nights", "urban_influence_check", "robustness_warm_nights", "ranking_warm_nights"):
        assert (tmp_path / "docs" / "figures" / f"{name}.png").exists()


def test_report_without_results_tells_you_to_analyze(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"results_dir": str(tmp_path / "none"), "docs_dir": str(tmp_path / "docs")}))
    assert cli.main(["--config", str(cfg), "--stage", "report"]) == 1
    assert "--stage analyze" in capsys.readouterr().err
