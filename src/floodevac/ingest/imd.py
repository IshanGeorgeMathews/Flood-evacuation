"""IMD gridded daily rainfall (0.25°) via imdlib, with GPM IMERG (GEE) as a fallback source.

Output: data/processed/rain_grid.parquet with columns [date, lat, lon, rain_mm, source].
Historic grids are final; real-time grids for the current year are provisional and can be revised by IMD.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import write_table
from floodevac.common.logging import get_logger

log = get_logger(__name__)

GRID_MARGIN_DEG = 0.25


def _bounds(cfg: Config) -> tuple[float, float, float, float]:
    a, b = cfg.area["bbox"], cfg.area["upstream_bbox"]
    return (min(a[0], b[0]) - GRID_MARGIN_DEG, min(a[1], b[1]) - GRID_MARGIN_DEG,
            max(a[2], b[2]) + GRID_MARGIN_DEG, max(a[3], b[3]) + GRID_MARGIN_DEG)


def _subset(ds, cfg: Config) -> pd.DataFrame:
    lon0, lat0, lon1, lat1 = _bounds(cfg)
    da = ds["rain"] if "rain" in ds else ds[list(ds.data_vars)[0]]
    da = da.sel(lat=slice(lat0, lat1), lon=slice(lon0, lon1))
    df = da.to_dataframe(name="rain_mm").reset_index()
    df = df.rename(columns={"time": "date"})
    df["rain_mm"] = df["rain_mm"].where(df["rain_mm"] >= 0)  # IMD uses -999 for no-data
    return df.dropna(subset=["rain_mm"])[["date", "lat", "lon", "rain_mm"]]


def fetch_year(cfg: Config, year: int, retries: int = 4) -> pd.DataFrame:
    """One year of IMD gridded rainfall; the IMD server drops connections, so retry with backoff."""
    import time

    import imdlib as imd

    out_dir = cfg.paths.raw / "imd"
    out_dir.mkdir(parents=True, exist_ok=True)
    grd = out_dir / "rain" / f"{year}.grd"
    for attempt in range(1, retries + 1):
        try:
            if not grd.exists() or grd.stat().st_size < 1_000_000:
                imd.get_data("rain", year, year, fn_format="yearwise", file_dir=str(out_dir))
            data = imd.open_data("rain", year, year, fn_format="yearwise", file_dir=str(out_dir))
            df = _subset(data.get_xarray(), cfg)
            df["source"] = "IMD"
            log.info("IMD %d loaded", year)
            return df
        except Exception as exc:  # noqa: BLE001
            log.warning("IMD %d attempt %d/%d failed: %s", year, attempt, retries, exc)
            grd.unlink(missing_ok=True)
            time.sleep(15 * attempt)
    raise RuntimeError(f"IMD {year} unavailable")


def fetch_realtime(cfg: Config, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Provisional real-time IMD grids (available with ~1 day lag)."""
    import imdlib as imd

    out_dir = cfg.paths.raw / "imd_rt"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = imd.get_real_data("rain", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), file_dir=str(out_dir))
    df = _subset(data.get_xarray(), cfg)
    df["source"] = "IMD-RT (provisional)"
    return df


def fetch_imerg(cfg: Config, start: str, end: str) -> pd.DataFrame:
    """Daily IMERG V07 totals resampled to the IMD 0.25° cell centres (fallback source)."""
    from floodevac.ingest import gee

    ee = gee.init(cfg)
    lon0, lat0, lon1, lat1 = _bounds(cfg)
    lats = np.arange(np.ceil(lat0 / 0.25) * 0.25, lat1 + 1e-9, 0.25)
    lons = np.arange(np.ceil(lon0 / 0.25) * 0.25, lon1 + 1e-9, 0.25)
    pts = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([float(x), float(y)]), {"lat": float(y), "lon": float(x)})
                                for y in lats for x in lons])
    coll = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").select("precipitation")
    frames = []
    for s, e in pd.date_range(start, end, freq="MS").to_series().pipe(lambda x: zip(x, x.shift(-1).fillna(pd.Timestamp(end)))):
        days = pd.date_range(s, e - pd.Timedelta(days=1) if e > s else s, freq="D")

        def daily(d):
            d = ee.Date(d)
            img = coll.filterDate(d, d.advance(1, "day")).sum().multiply(0.5)  # mm/h × 0.5 h
            return img.reduceRegions(pts, ee.Reducer.mean(), 10000).map(lambda f: f.set("date", d.format("YYYY-MM-dd")))

        fc = ee.FeatureCollection(ee.List([str(d.date()) for d in days]).map(daily)).flatten()
        rows = [f["properties"] for f in fc.getInfo()["features"]]
        frames.append(pd.DataFrame(rows))
    df = pd.concat(frames).rename(columns={"mean": "rain_mm"})
    df["date"] = pd.to_datetime(df["date"])
    df["source"] = "GPM IMERG"
    return df[["date", "lat", "lon", "rain_mm", "source"]]


def fetch(cfg: Config) -> Path:
    out = cfg.paths.processed / "rain_grid.parquet"
    if out.exists() and not cfg.force:
        return out
    frames = []
    for w in cfg.model["sar"]["windows"]:
        year = int(w[0][:4])
        try:
            frames.append(fetch_year(cfg, year))
        except Exception as exc:  # noqa: BLE001 - per-year fallback keeps the other years on IMD
            log.warning("IMD %d failed (%s); using GPM IMERG via GEE for that window", year, exc)
            frames.append(fetch_imerg(cfg, w[0][:7] + "-01", w[1]))
    df = pd.concat(frames)
    df["date"] = pd.to_datetime(df["date"])
    write_table(df.sort_values(["date", "lat", "lon"]), out)
    log.info("rain grid saved: %d rows, %s..%s", len(df), df["date"].min().date(), df["date"].max().date())
    return out
