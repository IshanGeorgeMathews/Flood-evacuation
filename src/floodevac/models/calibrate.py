"""Isotonic calibration fitted on out-of-fold (spatially blocked) predictions.

Training data keeps every flooded example but only a sample of the dry ones, so raw scores are inflated. Each
calibration example is weighted by the inverse of its sampling rate, which maps scores back to probabilities at
the true flood prevalence — the probabilities that feed the routing cost.
"""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


class Calibrator:
    def __init__(self) -> None:
        self.iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, raw: np.ndarray, y: np.ndarray, weight: np.ndarray | None = None) -> "Calibrator":
        self.iso.fit(raw, y, sample_weight=weight)
        return self

    def transform(self, raw: np.ndarray) -> np.ndarray:
        return self.iso.predict(np.asarray(raw, dtype="float64"))
