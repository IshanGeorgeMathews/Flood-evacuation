"""River-gauge features: level relative to the CWC danger level, nearest gauge and district maximum."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

GAUGE_FEATURES = ["gauge_near_rel", "gauge_near_rel_3d", "gauge_max_rel"]


def relative_levels(daily: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Daily max level minus danger level (metres; > 0 means above danger), plus its 3-day running max."""
    d = daily.merge(meta[["station", "danger"]], on="station")
    d["rel"] = d["level"] - d["danger"]
    d = d.sort_values(["station", "date"])
    frames = []
    for st, g in d.groupby("station"):
        g = g.set_index("date")["rel"].asfreq("D")
        frames.append(pd.DataFrame({"station": st, "rel": g, "rel_3d": g.rolling(3, min_periods=1).max()}))
    return pd.concat(frames).rename_axis("date").reset_index().dropna(subset=["rel_3d"])


def district_max(rel: pd.DataFrame) -> pd.DataFrame:
    return rel.groupby("date")["rel"].max().rename("gauge_max_rel").reset_index()


def nearest_station(lon: np.ndarray, lat: np.ndarray, meta: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Nearest gauge code and distance (km, equirectangular) for each point."""
    k = np.cos(np.radians(10.0))
    tree = cKDTree(np.column_stack([meta["lon"].to_numpy() * k, meta["lat"].to_numpy()]))
    dist, idx = tree.query(np.column_stack([lon * k, lat]))
    return meta["station"].to_numpy()[idx], dist * 111.0
