"""Google Earth Engine helpers: initialisation and tiled GeoTIFF download of small rasters."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.merge import merge

from floodevac.common.config import Config
from floodevac.common.logging import get_logger

log = get_logger(__name__)
_INIT = False


def init(cfg: Config):
    import ee

    global _INIT
    if not _INIT:
        if not cfg.ee_project:
            raise RuntimeError("EE_PROJECT is not set in .env — run `earthengine authenticate` and set it.")
        ee.Initialize(project=cfg.ee_project)
        _INIT = True
    return ee


def area_geometry(cfg: Config, key: str = "bbox"):
    ee = init(cfg)
    return ee.Geometry.Rectangle(cfg.area[key], proj="EPSG:4326", geodesic=False)


def _fetch_tile(image, rect, scale: int, crs: str, retries: int = 4) -> bytes:
    import time

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            url = image.getDownloadURL({"region": rect, "scale": scale, "crs": crs, "format": "GEO_TIFF"})
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            return r.content
        except Exception as exc:  # noqa: BLE001 - transient SSL / connection drops are common
            last = exc
            log.warning("GEE tile attempt %d/%d failed: %s", attempt, retries, str(exc)[:160])
            time.sleep(5 * attempt)
    raise RuntimeError("GEE tile download failed") from last


def download_image(cfg: Config, image, dest: Path, *, scale: int, region=None, tiles: int = 2,
                   crs: str | None = None) -> Path:
    """Download an ee.Image as a GeoTIFF by splitting the region into tiles x tiles requests and mosaicking."""
    if dest.exists() and not cfg.force:
        return dest
    ee = init(cfg)
    lon0, lat0, lon1, lat1 = cfg.area["bbox"] if region is None else region
    crs = crs or cfg.area["metric_crs"]
    dx, dy = (lon1 - lon0) / tiles, (lat1 - lat0) / tiles
    parts: list[Path] = []
    tmpdir = dest.parent / (dest.stem + "_parts")
    tmpdir.mkdir(parents=True, exist_ok=True)
    for i in range(tiles):
        for j in range(tiles):
            rect = ee.Geometry.Rectangle([lon0 + i * dx, lat0 + j * dy, lon0 + (i + 1) * dx, lat0 + (j + 1) * dy],
                                         proj="EPSG:4326", geodesic=False)
            content = _fetch_tile(image, rect, scale, crs)
            part = tmpdir / f"{i}_{j}.tif"
            if content[:2] == b"PK":  # some endpoints return a zip
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    content = z.read([n for n in z.namelist() if n.endswith(".tif")][0])
            part.write_bytes(content)
            parts.append(part)
    srcs = [rasterio.open(p) for p in parts]
    arr, transform = merge(srcs)
    profile = srcs[0].profile
    descs = srcs[0].descriptions
    for s in srcs:
        s.close()
    profile.update(height=arr.shape[1], width=arr.shape[2], transform=transform, compress="deflate")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dest, "w", **profile) as d:
        d.write(arr)
        for k, desc in enumerate(descs, start=1):
            if desc:
                d.set_band_description(k, desc)
    for p in parts:
        p.unlink(missing_ok=True)
    tmpdir.rmdir()
    log.info("GEE image saved %s (%s)", dest.name, "x".join(map(str, arr.shape)))
    return dest


def otsu(hist_counts: np.ndarray, hist_edges: np.ndarray) -> float:
    """Otsu threshold from a histogram (bucket means given as edges/centres)."""
    counts = np.asarray(hist_counts, dtype="float64")
    centres = np.asarray(hist_edges, dtype="float64")
    total = counts.sum()
    if total == 0:
        return float("nan")
    w0 = np.cumsum(counts)
    w1 = total - w0
    m0 = np.cumsum(counts * centres) / np.maximum(w0, 1e-9)
    mt = (counts * centres).sum()
    m1 = (mt - np.cumsum(counts * centres)) / np.maximum(w1, 1e-9)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centres[int(np.argmax(between))])
