"""Validation splits that respect space and time.

* Spatial blocks: segments are grouped into square blocks (default 10 km) in UTM; whole blocks go to one fold, so
  neighbouring segments of the same flood patch never sit on both sides of a split.
* Leave-one-event-out: every Sentinel-1 date of the held-out event (default August 2018) is the test set; nothing
  from that event is used for training, tuning, calibration or the past-flood-frequency feature.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer


def spatial_blocks(lon: np.ndarray, lat: np.ndarray, block_km: float, crs: str = "EPSG:32643") -> np.ndarray:
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    size = block_km * 1000.0
    bx = np.floor(np.asarray(x) / size).astype("int64")
    by = np.floor(np.asarray(y) / size).astype("int64")
    return bx * 100_000 + by


def block_folds(blocks: np.ndarray, n_folds: int, seed: int = 42) -> np.ndarray:
    """Assign each row a fold id by randomly distributing whole blocks across folds."""
    uniq = np.unique(blocks)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(uniq))
    fold_of_block = dict(zip(uniq[perm], np.arange(len(uniq)) % n_folds))
    return np.array([fold_of_block[b] for b in blocks], dtype="int16")


def spatial_splits(folds: np.ndarray):
    for k in np.unique(folds):
        yield np.flatnonzero(folds != k), np.flatnonzero(folds == k)


def event_mask(dates: pd.Series, holdout: str) -> np.ndarray:
    """True for rows whose date belongs to the held-out event (e.g. '2018-08' -> every date in August 2018)."""
    return dates.dt.strftime("%Y-%m-%d").str.startswith(holdout).to_numpy()


def assert_no_leakage(train_blocks: np.ndarray, test_blocks: np.ndarray) -> None:
    shared = np.intersect1d(np.unique(train_blocks), np.unique(test_blocks))
    if len(shared):
        raise AssertionError(f"{len(shared)} spatial blocks appear in both train and test")
