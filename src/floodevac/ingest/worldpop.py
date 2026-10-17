"""WorldPop 2020 population (100 m) via Google Earth Engine; used for congestion k(e) and people-exposed KPIs."""

from __future__ import annotations

from pathlib import Path

from floodevac.common.config import Config
from floodevac.ingest import gee


def fetch(cfg: Config) -> Path:
    dest = cfg.paths.raw / "worldpop_2020.tif"
    if dest.exists() and not cfg.force:
        return dest
    ee = gee.init(cfg)
    img = (ee.ImageCollection("WorldPop/GP/100m/pop").filter(ee.Filter.eq("country", "IND"))
           .filter(ee.Filter.eq("year", 2020)).mosaic().select("population").toFloat().rename("pop"))
    return gee.download_image(cfg, img, dest, scale=100, tiles=1)
