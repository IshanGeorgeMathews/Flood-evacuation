"""ESA WorldCover v200 (10 m, 2021) land cover, exported at 30 m via Google Earth Engine (mode resampling)."""

from __future__ import annotations

from pathlib import Path

from floodevac.common.config import Config
from floodevac.ingest import gee

# WorldCover class codes used as features
CLASSES = {"tree": 10, "crop": 40, "built": 50, "water": 80, "wetland": 90}


def fetch(cfg: Config) -> Path:
    dest = cfg.paths.raw / "landcover_worldcover.tif"
    if dest.exists() and not cfg.force:
        return dest
    ee = gee.init(cfg)
    img = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    img = img.reduceResolution(ee.Reducer.mode(), maxPixels=64).reproject(crs=cfg.area["metric_crs"], scale=30)
    return gee.download_image(cfg, img.toByte().rename("landcover"), dest, scale=30, tiles=2)
