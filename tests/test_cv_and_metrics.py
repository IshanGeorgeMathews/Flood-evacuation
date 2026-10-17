import numpy as np
import pandas as pd
import pytest

from floodevac.models import cv, evaluate
from floodevac.models.calibrate import Calibrator


def test_block_folds_keep_blocks_whole():
    rng = np.random.default_rng(0)
    lon = rng.uniform(76.15, 76.95, 5000)
    lat = rng.uniform(9.75, 10.35, 5000)
    blocks = cv.spatial_blocks(lon, lat, 10)
    folds = cv.block_folds(blocks, 5, seed=1)
    for tr, te in cv.spatial_splits(folds):
        cv.assert_no_leakage(blocks[tr], blocks[te])
        assert len(te) > 0
    assert len(np.unique(folds)) == 5


def test_leakage_check_raises():
    with pytest.raises(AssertionError):
        cv.assert_no_leakage(np.array([1, 2, 3]), np.array([3, 4]))


def test_event_mask_selects_whole_event():
    d = pd.Series(pd.to_datetime(["2018-07-16", "2018-08-09", "2018-08-21", "2019-08-10"]))
    assert cv.event_mask(d, "2018-08").tolist() == [False, True, True, False]


def test_metrics_on_known_case():
    y = np.array([0] * 90 + [1] * 10)
    perfect = y.astype(float)
    s = evaluate.summary(y, perfect, 0.05)
    assert s["pr_auc"] == pytest.approx(1.0)
    assert s["recall_at_fpr"] == pytest.approx(1.0)
    assert s["brier"] == pytest.approx(0.0)
    rel = evaluate.reliability(y, np.full(100, 0.1))
    assert rel[0]["observed"] == pytest.approx(0.1)


def test_weighted_isotonic_calibration_restores_prevalence():
    rng = np.random.default_rng(2)
    n = 20000
    y = (rng.random(n) < 0.02).astype(int)
    raw = np.clip(0.5 * y + rng.normal(0.3, 0.15, n), 0, 1)
    keep = (y == 1) | (rng.random(n) < 0.1)  # negative sampling as in training
    w = np.where(y[keep] == 1, 1.0, 10.0)
    cal = Calibrator().fit(raw[keep], y[keep], w)
    p = cal.transform(raw)
    assert abs(p.mean() - y.mean()) < 0.01
