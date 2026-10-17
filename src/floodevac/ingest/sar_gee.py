"""Sentinel-1 flood masks from Google Earth Engine (change detection + Otsu), one GeoTIFF per acquisition date.

Method (after Tiwari et al., 2020, Kerala 2018 flood, ~94% overall accuracy):
  * Sentinel-1 GRD, IW mode, VV polarisation, same relative orbit for reference and event image.
  * Reference: median of the dry season (Jan–Mar) of the same year and orbit.
  * Event image: mosaic of that date's scenes, 50 m focal-median speckle filter.
  * Flood = VV_event < Otsu threshold (clamped to [-20, -16] dB) AND VV_event - VV_ref < diff_db.
  * Masks: JRC permanent water (occurrence >= 80%) and slopes > 5° (Copernicus GLO-30).
Output pixel values: 1 flooded, 0 not observed flooded, 255 no coverage.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import read_json, write_json
from floodevac.common.logging import get_logger
from floodevac.ingest import gee

log = get_logger(__name__)

SCREEN_THRESHOLD_DB = -18.0


def _collection(ee, region, start: str, end: str):
    return (ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(region)
            .filterDate(start, end)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select("VV"))


def _static_masks(ee, cfg: Config):
    perm = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gte(
        cfg.model["sar"]["permanent_water_occurrence"]).unmask(0)
    dem = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM").mosaic().setDefaultProjection("EPSG:4326", None, 30)
    slope = ee.Terrain.slope(dem)
    return perm, slope.gt(cfg.model["sar"]["max_slope_deg"])


def _event_and_reference(ee, cfg: Config, region, date: str, orbit: int):
    d = ee.Date(date)
    months = cfg.model["sar"]["reference_months"]
    coll = _collection(ee, region, "2014-10-01", "2030-01-01").filter(ee.Filter.eq("relativeOrbitNumber_start", orbit))
    # dry-season scenes of the same orbit within a year either side of the event (some orbits skip some winters)
    ref = (coll.filterDate(d.advance(-12, "month"), d.advance(12, "month"))
           .filter(ee.Filter.calendarRange(months[0], months[-1], "month"))
           .median().focalMedian(50, "circle", "meters"))
    event = coll.filterDate(d, d.advance(1, "day")).mosaic().focalMedian(50, "circle", "meters")
    return event, ref


def list_acquisitions(cfg: Config) -> pd.DataFrame:
    """All candidate (date, orbit) acquisitions in the monsoon windows, with a quick flood-fraction screen."""
    cache = cfg.paths.interim / "sar_acquisitions.json"
    if cache.exists() and not cfg.force:
        return pd.DataFrame(read_json(cache))
    ee = gee.init(cfg)
    region = gee.area_geometry(cfg)
    perm, steep = _static_masks(ee, cfg)
    rows: list[dict] = []
    for start, end in cfg.model["sar"]["windows"]:
        coll = _collection(ee, region, start, end)
        info = coll.aggregate_array("system:time_start").getInfo()
        orbits = coll.aggregate_array("relativeOrbitNumber_start").getInfo()
        pairs = sorted({(pd.Timestamp(t, unit="ms").strftime("%Y-%m-%d"), int(o)) for t, o in zip(info, orbits)})
        feats = []
        for date, orbit in pairs:
            event, ref = _event_and_reference(ee, cfg, region, date, orbit)
            flood = (event.lt(SCREEN_THRESHOLD_DB).And(event.subtract(ref).lt(cfg.model["sar"]["diff_db"]))
                     .And(perm.Not()).And(steep.Not()))
            stats = ee.Image.cat(flood.rename("flood"), event.mask().rename("cov")).reduceRegion(
                ee.Reducer.mean(), region, scale=200, maxPixels=1e9, bestEffort=True)
            stats = ee.Algorithms.If(ref.bandNames().size().gt(0), stats, ee.Dictionary({"flood": 0, "cov": 0}))
            feats.append(ee.Feature(None, stats).set({"date": date, "orbit": orbit}))
        if not feats:
            continue
        res = ee.FeatureCollection(feats).getInfo()["features"]
        for f in res:
            p = f["properties"]
            rows.append({"date": p["date"], "orbit": p["orbit"], "flood_frac": p.get("flood") or 0.0,
                         "coverage": p.get("cov") or 0.0})
        log.info("window %s..%s: %d acquisitions screened", start, end, len(res))
    write_json(rows, cache)
    return pd.DataFrame(rows)


def select_dates(cfg: Config, acq: pd.DataFrame) -> pd.DataFrame:
    """Per monsoon window keep the most flooded acquisitions plus the least flooded one (clear negatives),
    always including the key event dates. Requires reasonable coverage of the district."""
    sar = cfg.model["sar"]
    acq = acq[acq["coverage"] >= 0.5].copy()
    acq["year"] = acq["date"].str[:4]
    keep = []
    for _, g in acq.groupby("year"):
        g = g.sort_values("flood_frac", ascending=False)
        keep.append(g.head(sar["max_dates_per_window"] - 1))
        keep.append(g.tail(1))
    must = acq[acq["date"].isin(sar["must_include"])]
    sel = pd.concat(keep + [must]).drop_duplicates(["date", "orbit"]).sort_values("date")
    # one orbit per date (the one with the best coverage)
    sel = sel.sort_values("coverage", ascending=False).drop_duplicates("date").sort_values("date")
    return sel.reset_index(drop=True)


def flood_mask_path(cfg: Config, date: str) -> Path:
    return cfg.paths.raw / "sar" / f"flood_{date}.tif"


def export_mask(cfg: Config, date: str, orbit: int) -> Path:
    dest = flood_mask_path(cfg, date)
    if dest.exists() and not cfg.force:
        return dest
    ee = gee.init(cfg)
    region = gee.area_geometry(cfg)
    perm, steep = _static_masks(ee, cfg)
    event, ref = _event_and_reference(ee, cfg, region, date, orbit)
    hist = event.reduceRegion(ee.Reducer.histogram(255, 0.1), region, scale=100, maxPixels=1e9,
                              bestEffort=True).get("VV").getInfo()
    thr = SCREEN_THRESHOLD_DB
    if hist:
        thr = gee.otsu(hist["histogram"], hist["bucketMeans"])
        thr = float(min(max(thr, -20.0), -16.0))
    flood = (event.lt(thr).And(event.subtract(ref).lt(cfg.model["sar"]["diff_db"]))
             .And(perm.Not()).And(steep.Not()))
    out = flood.unmask(255).where(event.mask().Not(), 255).toByte().rename("flood")
    gee.download_image(cfg, out, dest, scale=cfg.model["sar"]["scale_m"], tiles=2)
    meta_path = cfg.paths.raw / "sar" / "thresholds.json"
    meta = read_json(meta_path) if meta_path.exists() else {}
    meta[date] = {"orbit": orbit, "otsu_db": thr}
    write_json(meta, meta_path)
    log.info("flood mask %s exported (orbit %s, threshold %.1f dB)", date, orbit, thr)
    return dest


def fetch(cfg: Config) -> Path:
    acq = list_acquisitions(cfg)
    sel = select_dates(cfg, acq)
    out = cfg.paths.processed / "sar_events.parquet"
    for rec in sel.itertuples():
        try:
            export_mask(cfg, rec.date, int(rec.orbit))
        except Exception as exc:  # noqa: BLE001 - one bad date should not stop the run
            log.warning("flood mask %s failed: %s", rec.date, exc)
    sel["path"] = [str(flood_mask_path(cfg, d)) for d in sel["date"]]
    sel = sel[[Path(p).exists() for p in sel["path"]]]
    sel["path"] = [Path(p).name for p in sel["path"]]
    sel.to_parquet(out, index=False)
    log.info("SAR events: %d dates", len(sel))
    return out
