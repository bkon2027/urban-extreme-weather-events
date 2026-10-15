"""The only module that touches the network or the file system.

- Downloads NOAA GHCN-Daily and Census files with verified TLS (certifi), atomically.
- Records every download in data_manifest.csv (source, date, SHA-256) and warns when a fresh
  download differs from the committed manifest (NOAA revises GHCN-Daily over time).
- Reads station CSVs into tidy frames, converting at the boundary (QC-flagged values -> NaN).
"""
from __future__ import annotations

import csv
import hashlib
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

import certifi
import pandas as pd

log = logging.getLogger(__name__)

USER_AGENT = "DATA703-ewu-project"
STATION_URL = ("https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries"
               "&stations={sid}&dataTypes=TMAX,TMIN,PRCP&startDate={start}-01-01&endDate={end}-12-31"
               "&format=csv&units=metric&includeAttributes=true")
REFERENCE_FILES = {
    "ghcnd-stations.txt": ("https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt", 5_000_000),
    "2020_Census_ua_list_all.xlsx": ("https://www2.census.gov/geo/docs/reference/ua/2020_Census_ua_list_all.xlsx", 100_000),
    "tl_2020_us_uac20.zip": ("https://www2.census.gov/geo/tiger/TIGER2020/UAC/tl_2020_us_uac20.zip", 50_000_000),
}
MANIFEST_FIELDS = ["file", "source_url", "retrieved", "sha256"]


class DownloadError(RuntimeError):
    pass


def ssl_context() -> ssl.SSLContext:
    """Verified TLS using certifi's CA bundle, so downloads work on python.org macOS installs too."""
    return ssl.create_default_context(cafile=certifi.where())


def _urlopen(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read()


def download(url: str, dest: Path, validate: Callable[[bytes], None], *, retries: int = 3,
             timeout: int = 300, fetch: Callable[[str, int], bytes] = _urlopen, sleep=time.sleep) -> str:
    """Download url to dest through a temp file (never a half-written dest). Returns SHA-256 hex."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            body = fetch(url, timeout)
            validate(body)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, dest)
            return hashlib.sha256(body).hexdigest()
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            last = err
            log.warning("download attempt %d/%d failed for %s: %s", attempt, retries, dest.name, err)
            if attempt < retries:
                sleep(5 * attempt)
    raise DownloadError(f"{dest.name}: {last}")


def min_size(n: int) -> Callable[[bytes], None]:
    def check(body: bytes) -> None:
        if len(body) < n:
            raise ValueError(f"only {len(body)} bytes; expected at least {n}")
    return check


def station_csv(body: bytes) -> None:
    if not body.startswith(b'"STATION"'):
        raise ValueError(f"unexpected response starting {body[:60]!r}")


def read_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {row["file"]: row for row in csv.DictReader(f)}


def write_manifest(path: Path, rows: dict[str, dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows[k] for k in sorted(rows))
    os.replace(tmp, path)


def fetch_all(stations: Iterable[str], raw_dir: Path, reference_dir: Path, manifest_path: Path,
              start_year: int, end_year: int, *, fetch=_urlopen, sleep=time.sleep) -> list[tuple[str, str]]:
    """Download every missing reference and station file. Returns (file, error) for failures; never raises for one file."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(manifest_path)
    jobs = [(f"reference/{name}", url, reference_dir / name, min_size(n))
            for name, (url, n) in REFERENCE_FILES.items()]
    jobs += [(f"raw/{sid}.csv", STATION_URL.format(sid=sid, start=start_year, end=end_year),
              raw_dir / f"{sid}.csv", station_csv) for sid in sorted(set(stations))]
    failures = []
    for i, (key, url, dest, check) in enumerate(jobs, start=1):
        if dest.exists():
            log.debug("[%d/%d] %s present, skipping", i, len(jobs), key)
            continue
        log.info("[%d/%d] downloading %s", i, len(jobs), key)
        try:
            digest = download(url, dest, check, fetch=fetch, sleep=sleep)
        except DownloadError as err:
            failures.append((key, str(err)))
            continue
        old = manifest.get(key)
        if old and old["sha256"] != digest:
            log.warning("%s differs from the manifest (retrieved %s); NOAA/Census may have revised it",
                        key, old["retrieved"])
        manifest[key] = {"file": key, "source_url": url, "retrieved": date.today().isoformat(), "sha256": digest}
        write_manifest(manifest_path, manifest)
        sleep(1)
    return failures


def split_combined_station_files(paths: Iterable[Path], raw_dir: Path) -> list[str]:
    """Split browser-downloaded multi-station CSVs (stations_partN.csv) into one file per station."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for p in paths:
        df = pd.read_csv(p, dtype=str)
        for sid, part in df.groupby("STATION"):
            dest = raw_dir / f"{sid}.csv"
            if not dest.exists():
                part.to_csv(dest, index=False, quoting=csv.QUOTE_ALL)
                written.append(sid)
    return written


def read_station_csv(path: Path) -> pd.DataFrame:
    """Daily TMAX/TMIN/PRCP as floats; values with a GHCN quality flag (2nd attribute) become NaN."""
    d = pd.read_csv(path, dtype=str)
    out = pd.DataFrame({"date": pd.to_datetime(d["DATE"])})
    for e in ("TMAX", "TMIN", "PRCP"):
        vals = pd.to_numeric(d[e], errors="coerce") if e in d else pd.Series(float("nan"), index=d.index)
        attrs = d[f"{e}_ATTRIBUTES"] if f"{e}_ATTRIBUTES" in d else pd.Series("", index=d.index)
        qflag = attrs.fillna("").str.split(",").str[1].fillna("").str.strip()
        out[e] = vals.where(qflag == "")
    return out


def read_pairs(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    required = {"size_group", "urban_area", "urban_station", "rural_station", "distance_km"}
    missing = required - set(rows[0].keys()) if rows else required
    if missing:
        raise KeyError(f"{path.name}: missing columns {sorted(missing)}")
    for n, r in enumerate(rows, start=2):
        r["distance_km"] = float(r["distance_km"])
        if r["urban_station"] == r["rural_station"]:
            raise ValueError(f"{path.name} line {n}: urban and rural station are the same")
    return rows


def read_urban_area_list(path: Path) -> pd.DataFrame:
    """Census 2020 urban-area list: NAME, POP, POPDEN (people per sq mi)."""
    ua = pd.read_excel(path)
    return ua[["UACE", "NAME", "POP", "POPDEN"]]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write via a temp file and rename, so a crash never leaves a half-written result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)
