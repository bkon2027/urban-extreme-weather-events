import numpy as np
import pytest

from ewu import stats


def test_holm_matches_textbook_example():
    # p sorted: 0.01*4=0.04, 0.02*3=0.06, 0.03*2=0.06 (monotone), 0.04*1 -> 0.06
    adj = stats.holm([0.01, 0.04, 0.03, 0.02])
    assert adj == pytest.approx([0.04, 0.06, 0.06, 0.06])


def test_holm_caps_at_one():
    assert stats.holm([0.5, 0.9]).max() == 1.0


def test_constant_shift_is_detected_and_ci_contains_it():
    rng = np.random.default_rng(0)
    diffs = 2.0 + rng.normal(0, 0.5, 60)
    r = stats.paired_summary(diffs, np.random.default_rng(1), n_boot=2000)
    assert r["ci_low"] < 2.0 < r["ci_high"]
    assert r["wilcoxon_p"] < 0.001 and r["share_urban_higher"] > 0.9


def test_no_difference_is_not_significant():
    r = stats.paired_summary(np.zeros(20), np.random.default_rng(0), n_boot=500)
    assert r["wilcoxon_p"] == 1.0 and r["mean_diff"] == 0.0


def test_bootstrap_is_reproducible_with_a_seed():
    x = np.arange(30, dtype=float)
    a = stats.bootstrap_ci(x, np.random.default_rng(703), 1000)
    b = stats.bootstrap_ci(x, np.random.default_rng(703), 1000)
    assert a == b


def test_too_few_pairs_raises():
    with pytest.raises(ValueError):
        stats.paired_summary([1.0], np.random.default_rng(0))
