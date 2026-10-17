"""Rainfall features from the IMD 0.25° grid: per-cell accumulations and upstream-catchment accumulations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

WINDOWS = {"rain_1d": 1, "rain_3d": 3, "rain_5d": 5, "rain_7d": 7}
UP_WINDOWS = {"rain_up_3d": 3, "rain_up_5d": 5}


def cells(rain: pd.DataFrame) -> pd.DataFrame:
    c = rain[["lat", "lon"]].drop_duplicates().sort_values(["lat", "lon"]).reset_index(drop=True)
    c["cell_id"] = np.arange(len(c), dtype="int32")
    return c


def _daily_matrix(rain: pd.DataFrame, cell_tab: pd.DataFrame) -> pd.DataFrame:
    r = rain.merge(cell_tab, on=["lat", "lon"])
    m = r.pivot_table(index="date", columns="cell_id", values="rain_mm", aggfunc="mean")
    full = pd.date_range(m.index.min(), m.index.max(), freq="D")
    return m.reindex(full)


def accumulations(rain: pd.DataFrame, cell_tab: pd.DataFrame) -> pd.DataFrame:
    """Rolling sums ending on each day, per cell. Missing days stay missing (no silent zero-fill)."""
    m = _daily_matrix(rain, cell_tab)
    out = []
    for name, w in WINDOWS.items():
        s = m.rolling(w, min_periods=w).sum().stack(future_stack=True).rename(name)
        out.append(s)
    df = pd.concat(out, axis=1).reset_index()
    df.columns = ["date", "cell_id", *WINDOWS]
    return df.dropna(subset=["rain_1d"])


def upstream(rain: pd.DataFrame, cell_tab: pd.DataFrame, bbox: list[float]) -> pd.DataFrame:
    """Mean accumulated rainfall over the upstream catchment box (Idukki/Idamalayar highlands)."""
    lon0, lat0, lon1, lat1 = bbox
    sel = cell_tab[(cell_tab.lon >= lon0) & (cell_tab.lon <= lon1) & (cell_tab.lat >= lat0) & (cell_tab.lat <= lat1)]
    m = _daily_matrix(rain, cell_tab)[sel["cell_id"]].mean(axis=1)
    df = pd.DataFrame({name: m.rolling(w, min_periods=w).sum() for name, w in UP_WINDOWS.items()})
    return df.rename_axis("date").reset_index()


def nearest_cell(lon: np.ndarray, lat: np.ndarray, cell_tab: pd.DataFrame) -> np.ndarray:
    tree = cKDTree(cell_tab[["lon", "lat"]].to_numpy())
    _, idx = tree.query(np.column_stack([lon, lat]))
    return cell_tab["cell_id"].to_numpy()[idx]
