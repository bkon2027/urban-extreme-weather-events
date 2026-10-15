# Does Urbanization Change How Often Places Experience Extreme Weather?

DATA 703 final project · Ben Konigsberg · individual project

**Question.** Controlling for regional climate, do urban weather stations record extreme weather
more often than nearby rural stations?
**Audience.** Planners in small and mid-size cities deciding which weather hazards to prepare for.

## Design

- **Paired stations.** 65 urban–rural pairs of NOAA GHCN-Daily stations, 2015–2024. Urban = inside a
  Census 2020 urban area; rural partner = outside every urban area, 20–75 km away, elevation within 100 m.
  The pair list is fixed and committed: [`config/final_pairs.csv`](config/final_pairs.csv).
- **Coverage.** A station-year counts only if both stations have ≥90% valid days for TMAX, TMIN and PRCP;
  a pair is kept with ≥8 usable years. Values carrying a GHCN quality flag are treated as missing.
- **Extreme events.** Thresholds come from each pair's **rural** station and apply to both stations:
  hot days (TMAX > rural 90th pct), warm nights (TMIN > rural 90th pct), heavy-rain days
  (PRCP > rural 95th pct of wet days), cold nights (TMIN < rural 10th pct; a negative control).
  Exceedance is strict: a value equal to the threshold is not an event. Rates are per 365 valid days.
- **Statistics.** Urban-minus-rural difference per pair; Wilcoxon signed-rank test, 95% bootstrap CI
  (seeded), Holm correction across the four indices.

## Setup

Requires Python ≥ 3.10. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Run

```bash
python -m ewu.cli --config config/ewu.json                 # download what's missing, then analyze
python -m ewu.cli --config config/ewu.json --stage fetch   # download only
python -m ewu.cli --config config/ewu.json --stage analyze # analyze already-downloaded data
python -m ewu.cli --help
```

Settings resolve **command line > config file > defaults**. Every run logs the command, effective settings,
Git commit, counts and outputs to the terminal and `results/run.log`, and exits non-zero on failure.
Outputs go to `results/` (`results_overall.csv`, `pair_summary.csv`, `pair_year_differences.csv`).

## Data and reproducibility

- Data is **not** committed. `--stage fetch` downloads it into `data/` (≈100 MB): NOAA station data via the
  [NCEI Access Data Service](https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation),
  the GHCN station list, and the Census 2020 urban-area list and boundaries. Re-running skips finished files.
- [`data_manifest.csv`](data_manifest.csv) records each file's source URL, retrieval date and SHA-256.
  A fresh download that differs from the manifest is logged as a warning: **NOAA revises GHCN-Daily over
  time**, so a later download may not be byte-identical. The exact raw files analyzed are attached to the
  final GitHub release as a snapshot.
- TLS uses `certifi`, so downloads work on python.org macOS installs without extra setup.
- If you downloaded station data in a browser as `stations_part1.csv`…`stations_part3.csv`, place them in
  `data/`; the fetch stage splits them into per-station files.

## Tests

```bash
python -m pytest -q
```

Tests use small synthetic data and a fake downloader: no network, no real data.

## Project layout

```
ewu/core.py    pure rules: coverage, thresholds, event rates, pair differences
ewu/stats.py   pure statistics: bootstrap CI, Holm, paired summary
ewu/io.py      the only module touching network/files: downloads, manifest, readers, atomic writes
ewu/cli.py     argparse, config precedence, logging, exit codes
config/        ewu.json settings and the committed pair list
tests/         pytest suite
```

Dependencies point one way: `cli → io → core/stats`.

## Status and limitations

Preliminary exploratory results (Oct 8) are being rebuilt in this tested pipeline. In progress:
urban-influence check (rural-station distance from the urban edge, size-scaled buffer), coastal matching,
airport flags, and the warm-nights ranking. Known limitations: many urban stations sit at airports;
coastal and mountain-valley pairs can confound comparisons; 10 years is too short to estimate trends.

## AI assistance

Claude Code (Anthropic) was used for scaffolding and drafting code; every change is reviewed, tested and
logged in [`AGENT_LOG.md`](AGENT_LOG.md). Agent-written commits are tagged `[agent]`.
