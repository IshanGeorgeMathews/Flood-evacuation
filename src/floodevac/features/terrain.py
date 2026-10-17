"""Sample raster layers along road segments.

Every segment gets sample points every ~20 m (at least start, middle, end). Rasters are read once into memory and
sampled with vectorised index lookups, which is fast enough for a few hundred thousand segments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import Transformer

from floodevac.common.logging import get_logger

log = get_logger(__name__)


@dataclass
class SamplePoints:
    seg_idx: np.ndarray  # index into the segment frame for every point
    x: np.ndarray        # metric CRS coordinates
    y: np.ndarray


def sample_points(seg_metric: gpd.GeoDataFrame, spacing_m: float) -> SamplePoints:
    """Points every `spacing_m` along each segment (min 3 per segment: start, mid, end)."""
    lengths = seg_metric.geometry.length.to_numpy()
    n = np.maximum(3, np.ceil(lengths / spacing_m).astype(int) + 1)
    seg_idx = np.repeat(np.arange(len(seg_metric)), n)
    # fraction along the line for every point: 0..1 inclusive
    offsets = np.concatenate([np.linspace(0, 1, k) for k in n])
    geoms = np.asarray(seg_metric.geometry.values)[seg_idx]
    pts = shapely.line_interpolate_point(geoms, offsets, normalized=True)
    return SamplePoints(seg_idx, shapely.get_x(pts), shapely.get_y(pts))


def read_raster_at(path: Path, x: np.ndarray, y: np.ndarray, src_crs: str, band: int | None = None,
                   honour_nodata: bool = True) -> np.ndarray:
    """Values of a raster at coordinates (given in src_crs). Outside the raster -> NaN. Returns (bands, n).
    Earth Engine writes nodata=0 into uint8 exports, where 0 is a real value (dry / no class); pass
    honour_nodata=False for those and handle their own missing-value code."""
    with rasterio.open(path) as src:
        if str(src.crs) != src_crs:
            t = Transformer.from_crs(src_crs, src.crs, always_xy=True)
            x, y = t.transform(x, y)
        rows, cols = rasterio.transform.rowcol(src.transform, x, y)
        rows, cols = np.asarray(rows), np.asarray(cols)
        inside = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        bands = [band] if band else list(range(1, src.count + 1))
        out = np.full((len(bands), len(x)), np.nan, dtype="float32")
        for k, b in enumerate(bands):
            arr = src.read(b).astype("float32")
            if honour_nodata and src.nodata is not None and not np.isnan(src.nodata):
                arr[arr == src.nodata] = np.nan
            arr[~np.isfinite(arr)] = np.nan
            out[k, inside] = arr[rows[inside], cols[inside]]
    return out


def aggregate(seg_idx: np.ndarray, values: np.ndarray, n_seg: int, how: str) -> np.ndarray:
    s = pd.Series(values).groupby(seg_idx)
    res = {"mean": s.mean, "min": s.min, "max": s.max}[how]()
    out = np.full(n_seg, np.nan, dtype="float32")
    out[res.index.to_numpy()] = res.to_numpy()
    return out


def terrain_features(seg_metric: gpd.GeoDataFrame, pts: SamplePoints, terrain_tif: Path, crs: str) -> pd.DataFrame:
    from floodevac.ingest.dem import TERRAIN_BANDS

    vals = read_raster_at(terrain_tif, pts.x, pts.y, crs)
    n = len(seg_metric)
    how = {"elev": "mean", "hand": "min", "slope": "mean", "twi": "max", "dist_stream_m": "min",
           "stream_order": "max", "flow_acc_log": "max"}
    return pd.DataFrame({name: aggregate(pts.seg_idx, vals[i], n, how[name]) for i, name in enumerate(TERRAIN_BANDS)})


def landcover_features(seg_metric, pts: SamplePoints, lc_tif: Path, crs: str) -> pd.DataFrame:
    from floodevac.ingest.landcover_gee import CLASSES

    lc = read_raster_at(lc_tif, pts.x, pts.y, crs, honour_nodata=False)[0]
    n = len(seg_metric)
    out = {}
    for name in ("water", "built", "tree", "crop"):
        codes = [CLASSES[name]] + ([CLASSES["wetland"]] if name == "water" else [])
        out[f"landcover_{name}"] = aggregate(pts.seg_idx, np.isin(lc, codes).astype("float32"), n, "mean")
    return pd.DataFrame(out)


def population(seg_metric, pop_tif: Path, crs: str) -> np.ndarray:
    mid = seg_metric.geometry.interpolate(0.5, normalized=True)
    v = read_raster_at(pop_tif, mid.x.to_numpy(), mid.y.to_numpy(), crs)[0]
    return np.nan_to_num(v, nan=0.0)


def flood_fraction(pts: SamplePoints, n_seg: int, mask_tif: Path, crs: str) -> np.ndarray:
    """Share of a segment's sample points inside SAR flood pixels; NaN where the scene does not cover it."""
    v = read_raster_at(mask_tif, pts.x, pts.y, crs, honour_nodata=False)[0]
    valid = np.isfinite(v) & (v != 255)
    flooded = (v == 1) & valid
    nv = np.bincount(pts.seg_idx, weights=valid, minlength=n_seg)
    nf = np.bincount(pts.seg_idx, weights=flooded, minlength=n_seg)
    npts = np.bincount(pts.seg_idx, minlength=n_seg)
    frac = np.where(nv > 0, nf / np.maximum(nv, 1), np.nan)
    frac[nv < 0.5 * npts] = np.nan  # less than half the segment observed -> unknown
    return frac.astype("float32")
