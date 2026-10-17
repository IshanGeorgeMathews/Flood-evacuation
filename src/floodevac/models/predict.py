"""Load the current model version and score segments for a date (live, what-if or replay)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import read_json
from floodevac.features.build_table import FeatureStore

RAIN_COLS = ["rain_1d", "rain_3d", "rain_5d", "rain_7d"]


def current_version(cfg: Config) -> str:
    return (cfg.paths.models / "CURRENT").read_text(encoding="utf-8").strip()


@dataclass
class Scores:
    p: np.ndarray
    mode: str            # "full" | "static-fallback"
    features: pd.DataFrame


class Predictor:
    def __init__(self, cfg: Config, store: FeatureStore | None = None, holdout: bool = False):
        """holdout=True loads the model trained without the held-out event (used for the 2018 replay)."""
        self.cfg = cfg
        self.version = current_version(cfg)
        d: Path = cfg.paths.models / self.version
        self.full = joblib.load(d / ("model_holdout.joblib" if holdout else "model.joblib"))
        self.exclude = set(self.full.get("excluded_dates", []))
        self.static = joblib.load(d / "model_static.joblib")
        self.metrics = read_json(d / "metrics.json")
        self._explainer_path = d / "explainer_model.joblib"
        self._explainer = None
        self.store = store or FeatureStore(cfg)

    def score(self, date: pd.Timestamp, seg_ids: pd.Series | None = None, rain_offset_mm: float = 0.0) -> Scores:
        seg_ids = self.store.seg["seg_id"] if seg_ids is None else seg_ids
        pairs = pd.DataFrame({"seg_id": seg_ids.to_numpy(), "date": pd.Timestamp(date)})
        X = self.store.assemble(pairs, exclude=self.exclude, rain_offset_mm=rain_offset_mm)
        rain_missing = X[RAIN_COLS].isna().all(axis=1).mean() > 0.5
        if rain_missing and not rain_offset_mm:
            m = self.static
            raw = m["model"].predict_proba(X[m["features"]])[:, 1]
            return Scores(m["calibrator"].transform(raw), "static-fallback", X)
        m = self.full
        raw = m["model"].predict_proba(X[m["features"]])[:, 1]
        return Scores(m["calibrator"].transform(raw), "full", X)

    def explain(self, row: pd.DataFrame, top: int = 6) -> list[dict]:
        """Top SHAP contributions (log-odds) for one assembled feature row."""
        import shap

        if self._explainer is None:
            em = joblib.load(self._explainer_path)
            self._explainer = (shap.TreeExplainer(em["model"]), em["features"])
        explainer, feats = self._explainer
        x = row[feats]
        sv = np.asarray(explainer.shap_values(x))[0]
        order = np.argsort(np.abs(sv))[::-1][:top]
        return [{"feature": feats[i], "value": None if pd.isna(x.iloc[0, i]) else float(x.iloc[0, i]),
                 "shap": float(sv[i])} for i in order]
