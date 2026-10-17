"""Copernicus GLO-30 DEM from the AWS open-data bucket (no key needed) and hydrological terrain derivatives.

FABDEM is deliberately not used: its licence restricts commercial work (see the project review).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject

from floodevac.common.config import Config
from floodevac.common.io import download
from floodevac.common.logging import get_logger

log = get_logger(__name__)

COP_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
STREAM_THRESHOLD_CELLS = 2000  # ~1.8 km² contributing area at 30 m
TERRAIN_BANDS = ["elev", "hand", "slope", "twi", "dist_stream_m", "stream_order", "flow_acc_log"]


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def fetch(cfg: Config) -> Path:
    """Download covering tiles, mosaic, clip to the area bbox and reproject to UTM 43N at 30 m."""
    out = cfg.paths.interim / "dem_utm.tif"
    if out.exists() and not cfg.force:
        return out
    lon0, lat0, lon1, lat1 = cfg.area["bbox"]
    tiles = []
    for lat in range(math.floor(lat0), math.floor(lat1) + 1):
        for lon in range(math.floor(lon0), math.floor(lon1) + 1):
            name = _tile_name(lat, lon)
            tiles.append(download(COP_URL.format(name=name), cfg.paths.raw / "dem" / f"{name}.tif", force=cfg.force))
    srcs = [rasterio.open(t) for t in tiles]
    mosaic, transform = merge(srcs, bounds=(lon0, lat0, lon1, lat1))
    crs = srcs[0].crs
    for s in srcs:
        s.close()
    h, w = mosaic.shape[1:]
    dst_crs = cfg.area["metric_crs"]
    dst_t, dst_w, dst_h = calculate_default_transform(crs, dst_crs, w, h, left=lon0, bottom=lat0, right=lon1, top=lat1,
                                                      resolution=30)
    dst = np.full((dst_h, dst_w), np.nan, dtype="float32")
    reproject(mosaic[0].astype("float32"), dst, src_transform=transform, src_crs=crs, dst_transform=dst_t,
              dst_crs=dst_crs, resampling=Resampling.bilinear, src_nodata=None, dst_nodata=np.nan)
    profile = dict(driver="GTiff", height=dst_h, width=dst_w, count=1, dtype="float32", crs=dst_crs,
                   transform=dst_t, nodata=np.nan, compress="deflate")
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as d:
        d.write(dst, 1)
    log.info("DEM mosaic saved %dx%d", dst_w, dst_h)
    return out


def derive_terrain(cfg: Config) -> Path:
    """HAND, slope, TWI, distance to stream, Strahler order and log flow accumulation (pysheds)."""
    out = cfg.paths.interim / "terrain.tif"
    if out.exists() and not cfg.force:
        return out
    from scipy.ndimage import distance_transform_edt

    if not hasattr(np, "in1d"):  # pysheds still calls np.in1d, removed in NumPy 2.4
        np.in1d = lambda a, b, **kw: np.isin(a, b, **kw).ravel()
    from pysheds.grid import Grid

    dem_path = fetch(cfg)
    with rasterio.open(dem_path) as src:
        profile = src.profile
        elev = src.read(1)
        res = src.res[0]
    # sea / missing cells: set to 0 so flow routes to the coast
    elev = np.where(np.isfinite(elev), elev, 0).astype("float64")
    tmp = cfg.paths.interim / "dem_filled_input.tif"
    with rasterio.open(tmp, "w", **{**profile, "dtype": "float64", "nodata": -9999}) as d:
        d.write(elev, 1)

    grid = Grid.from_raster(str(tmp))
    dem = grid.read_raster(str(tmp))
    log.info("conditioning DEM…")
    inflated = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(dem)))
    dirmap = (64, 128, 1, 2, 4, 8, 16, 32)
    fdir = grid.flowdir(inflated, dirmap=dirmap)
    acc = grid.accumulation(fdir, dirmap=dirmap)
    streams = acc > STREAM_THRESHOLD_CELLS
    log.info("computing HAND and stream order…")
    hand = np.asarray(grid.compute_hand(fdir, dem, streams, dirmap=dirmap), dtype="float32")
    order = np.asarray(grid.stream_order(fdir, streams, dirmap=dirmap), dtype="float32")

    acc_a = np.asarray(acc, dtype="float64")
    dzdy, dzdx = np.gradient(elev, res)
    slope_rad = np.arctan(np.hypot(dzdx, dzdy))
    slope_deg = np.degrees(slope_rad).astype("float32")
    twi = np.log(((acc_a + 1) * res) / np.maximum(np.tan(slope_rad), 0.001)).astype("float32")
    dist = (distance_transform_edt(~np.asarray(streams)) * res).astype("float32")
    hand = np.where(np.isfinite(hand), np.maximum(hand, 0), np.nan).astype("float32")

    stack = [elev.astype("float32"), hand, slope_deg, twi, dist, order, np.log1p(acc_a).astype("float32")]
    with rasterio.open(out, "w", **{**profile, "count": len(stack), "dtype": "float32", "nodata": np.nan}) as d:
        for i, (band, name) in enumerate(zip(stack, TERRAIN_BANDS), start=1):
            d.write(band, i)
            d.set_band_description(i, name)
    tmp.unlink(missing_ok=True)
    log.info("terrain derivatives saved")
    return out
