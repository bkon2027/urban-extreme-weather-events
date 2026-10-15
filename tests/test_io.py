import csv

import pytest

from ewu import io

GOOD_CSV = (b'"STATION","DATE","PRCP","PRCP_ATTRIBUTES","TMAX","TMAX_ATTRIBUTES","TMIN","TMIN_ATTRIBUTES"\n'
            b'"USW00000001","2015-01-01","1.0",",,W","10.0",",,W","1.0",",,W"\n'
            b'"USW00000001","2015-01-02","0.0",",,W","99.0",",X,W","2.0",",,W"\n')


def no_sleep(_):
    pass


def test_download_writes_file_and_returns_checksum(tmp_path):
    dest = tmp_path / "s.csv"
    digest = io.download("u", dest, io.station_csv, fetch=lambda url, t: GOOD_CSV, sleep=no_sleep)
    assert dest.read_bytes() == GOOD_CSV and len(digest) == 64
    assert not (tmp_path / "s.csv.tmp").exists()


def test_bad_response_retries_then_fails_without_leaving_a_file(tmp_path):
    calls = []
    def fetch(url, t):
        calls.append(url)
        return b"<html>error</html>"
    dest = tmp_path / "s.csv"
    with pytest.raises(io.DownloadError):
        io.download("u", dest, io.station_csv, retries=3, fetch=fetch, sleep=no_sleep)
    assert len(calls) == 3 and not dest.exists()


def test_fetch_all_skips_existing_and_records_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "REFERENCE_FILES", {"ref.txt": ("https://example/ref.txt", 1)})
    raw, ref, manifest = tmp_path / "raw", tmp_path / "ref", tmp_path / "data_manifest.csv"
    raw.mkdir()
    (raw / "USW00000002.csv").write_bytes(GOOD_CSV)          # already present: must not be fetched
    fetched = []
    def fetch(url, t):
        fetched.append(url)
        return b"reference" if url.endswith("ref.txt") else GOOD_CSV
    failures = io.fetch_all(["USW00000001", "USW00000002"], raw, ref, manifest, 2015, 2024, fetch=fetch, sleep=no_sleep)
    assert failures == []
    assert len(fetched) == 2 and not any("USW00000002" in u for u in fetched)
    rows = {r["file"] for r in csv.DictReader(manifest.open())}
    assert rows == {"reference/ref.txt", "raw/USW00000001.csv"}


def test_one_failed_station_is_reported_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "REFERENCE_FILES", {})
    def fetch(url, t):
        return b"oops" if "USW00000009" in url else GOOD_CSV
    failures = io.fetch_all(["USW00000001", "USW00000009"], tmp_path / "raw", tmp_path / "ref",
                            tmp_path / "m.csv", 2015, 2024, fetch=fetch, sleep=no_sleep)
    assert [f[0] for f in failures] == ["raw/USW00000009.csv"]
    assert (tmp_path / "raw" / "USW00000001.csv").exists()


def test_quality_flagged_values_become_missing(tmp_path):
    p = tmp_path / "s.csv"
    p.write_bytes(GOOD_CSV)
    df = io.read_station_csv(p)
    assert df.loc[0, "TMAX"] == 10.0
    assert df["TMAX"].isna().iloc[1]           # QFLAG "X" -> NaN
    assert df.loc[1, "TMIN"] == 2.0            # other elements unaffected


def test_split_combined_browser_download(tmp_path):
    combined = tmp_path / "stations_part1.csv"
    combined.write_bytes(GOOD_CSV + b'"USC00000003","2015-01-01","0.0",",,7","5.0",",,7","0.0",",,7"\n')
    written = io.split_combined_station_files([combined], tmp_path / "raw")
    assert sorted(written) == ["USC00000003", "USW00000001"]
    assert len(io.read_station_csv(tmp_path / "raw" / "USW00000001.csv")) == 2


def test_pairs_file_with_same_station_twice_is_rejected(tmp_path):
    p = tmp_path / "pairs.csv"
    p.write_text("size_group,urban_area,urban_station,rural_station,distance_km\n<50k,X,USW1,USW1,30\n")
    with pytest.raises(ValueError, match="same"):
        io.read_pairs(p)


def test_ssl_context_verifies_certificates():
    import ssl
    ctx = io.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
