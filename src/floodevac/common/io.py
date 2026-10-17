"""Uniform I/O helpers: GeoParquet for vectors, Parquet for tables, GeoTIFF for rasters, JSON for small artefacts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from floodevac.common.logging import get_logger

log = get_logger(__name__)


def read_gdf(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_parquet(path)


def write_gdf(gdf: gpd.GeoDataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(path, index=False)
    return path


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write_table(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        return super().default(o)


def write_json(obj: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, cls=_Encoder, indent=1)
    return path


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def download(url: str, dest: Path, *, timeout: int = 120, retries: int = 3, force: bool = False) -> Path:
    """Stream a URL to disk with retries; skip when cached."""
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            log.info("downloaded %s", dest.name)
            return dest
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            last = exc
            log.warning("download failed (%s/%s) %s: %s", attempt, retries, url, exc)
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed: {url}") from last
