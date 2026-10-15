# Agent log

One entry per significant agent-assisted task (DATA 703 Lecture 08 format).
Agent: Claude Code (Anthropic). Agent-written commits are tagged `[agent]`.

## 2026-10-15 — project skeleton with reproducible data download (branch: main, initial commit)
- **Prompt:** move the data download into the project code so a fresh clone can rebuild the data; follow the
  course project tree (core / io / cli), config precedence, logging, exit codes; fix the macOS certificate
  failure in code; record downloads in a manifest; tests with no network. Non-goal: no new analysis yet.
- **Changed:** `ewu/core.py`, `ewu/stats.py`, `ewu/io.py`, `ewu/cli.py`, `config/ewu.json`,
  `config/final_pairs.csv` (the 65 pairs from the preliminary analysis), `tests/` (30 tests), `pyproject.toml`,
  `README.md`, `.gitignore`.
- **Ran:** `python -m pytest -q` (30 passed), including an end-to-end analyze run on synthetic pairs.
- **Accepted:** _(fill in after your review: what you checked and kept)_
- **Rejected/edited:** _(fill in: anything you changed or removed)_
- **Open:** run `--stage fetch` and `--stage analyze` on the real data and confirm results match the Oct 8
  preliminary numbers; urban-influence check, coastal rule, airport flags and ranking still to add.

## 2026-10-15 — urban-influence check, coastal and airport flags, warm-nights ranking (branch: feat/robustness-ranking)
- **Prompt:** reviewer feedback: large cities may warm their rural partners. Add a size-scaled buffer from the
  Census urban-area edge and a distance check; coastal-mismatch and airport flags; rerun the main test on subsets;
  rank pairs by urban excess of warm nights with per-pair CIs. Non-goal: no forecasting.
- **Changed:** new `ewu/geo.py` (pure geographic rules), `ewu/plots.py`; `ewu/io.py` (station metadata, urban-area
  shapes, figure writer), `ewu/stats.py` (`rank_pairs`, `subset_tests`), `ewu/cli.py` (site flags, robustness,
  ranking), `config/ewu.json` (buffer, coast, ranking settings), `pyproject.toml` (shapely, pyshp, global-land-mask),
  `tests/test_geo.py`, `tests/test_cli.py`.
- **Ran:** `python -m pytest -q` (43 passed); `python -m ewu.cli --config config/ewu.json --stage analyze` on the real
  data: reproduced Oct 8 numbers (65 pairs, 611 pair-years, warm nights +13.4/yr).
- **Accepted:** _(fill in after your review)_
- **Rejected/edited:** _(fill in)_
- **Open:** terrain (valley cold-air pooling) not modelled; strictest subset (n = 22) underpowered.
