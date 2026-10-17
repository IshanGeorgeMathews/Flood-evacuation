"""Candidate evacuation shelters from OpenStreetMap.

No official shelter list has been supplied yet, so candidates are large public buildings (schools, colleges,
community halls, town halls, auditoriums) — the building types Kerala uses as relief camps. Every OSM candidate is
marked `verified = False` until the District Disaster Management Authority list replaces or confirms it.

Capacity estimate: footprint area x floors x 0.6 usable share / 3.5 m² per person (Sphere minimum covered
living space), clipped to [50, 2000]. Points without a footprint get a conservative default of 100.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import write_gdf
from floodevac.common.logging import get_logger
from floodevac.ingest.osm import _setup_osmnx, fetch_boundary, overpass

log = get_logger(__name__)

TAGS = {
    "amenity": ["school", "college", "university", "community_centre", "townhall", "social_centre", "events_venue"],
    "building": ["school", "college", "university"],
}
M2_PER_PERSON = 3.5
USABLE_SHARE = 0.6
DEFAULT_CAPACITY = 100
MIN_CAPACITY = 50

FACILITIES = {
    "school": ["classrooms", "toilets", "drinking water"],
    "college": ["halls", "toilets", "drinking water"],
    "university": ["halls", "toilets", "drinking water"],
    "community_centre": ["hall", "kitchen"],
    "townhall": ["hall", "kitchen", "toilets"],
}


def _kind(row) -> str:
    for col in ("amenity", "building"):
        v = row.get(col)
        if isinstance(v, str) and v in FACILITIES:
            return v
    return "community_centre"


PBF_URL = "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"


def _from_pbf(cfg: Config, district) -> gpd.GeoDataFrame:
    """Read candidate shelters from a local Geofabrik extract (used when every Overpass mirror is down)."""
    import osmium
    from shapely import wkb

    from floodevac.common.io import download

    pbf = download(PBF_URL, cfg.paths.raw / "geofabrik" / "southern-zone.osm.pbf", timeout=1800)
    lon0, lat0, lon1, lat1 = cfg.area["bbox"]
    wanted = {k: set(v) for k, v in TAGS.items()}
    factory = osmium.geom.WKBFactory()
    rows: list[dict] = []

    def match(tags) -> dict | None:
        hit = {k: tags.get(k) for k in ("amenity", "building") if tags.get(k) in wanted.get(k, ())}
        if not hit:
            return None
        return {"amenity": tags.get("amenity"), "building": tags.get("building"), "name": tags.get("name"),
                "building:levels": tags.get("building:levels")}

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if lon0 <= n.location.lon <= lon1 and lat0 <= n.location.lat <= lat1:
                m = match(n.tags)
                if m:
                    rows.append({**m, "geometry": wkb.loads(factory.create_point(n), hex=True)})

        def area(self, a):
            m = match(a.tags)
            if not m:
                return
            try:
                g = wkb.loads(factory.create_multipolygon(a), hex=True)
            except Exception:  # noqa: BLE001 - broken multipolygons are skipped
                return
            c = g.representative_point()
            if lon0 <= c.x <= lon1 and lat0 <= c.y <= lat1:
                rows.append({**m, "geometry": g})

    log.info("reading shelters from the local OSM extract (a few minutes)…")
    Handler().apply_file(str(pbf), locations=True, idx="flex_mem")
    feats = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return feats[feats.intersects(district.geometry.iloc[0])].reset_index(drop=True)


def fetch(cfg: Config) -> Path:
    out = cfg.paths.processed / "shelters_base.parquet"
    if out.exists() and not cfg.force:
        return out
    ox = _setup_osmnx(cfg)
    district = gpd.read_parquet(fetch_boundary(cfg))
    try:
        feats = overpass(ox.features_from_polygon, district.geometry.iloc[0], tags=TAGS, rounds=2).reset_index()
    except Exception as exc:  # noqa: BLE001
        log.warning("Overpass unavailable for shelters (%s); using the Geofabrik extract", str(exc)[:100])
        feats = _from_pbf(cfg, district)
    metric = cfg.area["metric_crs"]
    feats = feats.to_crs(metric)
    is_area = feats.geometry.type.isin(["Polygon", "MultiPolygon"])
    levels = pd.to_numeric(feats.get("building:levels", pd.Series(index=feats.index, dtype=float)), errors="coerce")
    levels = levels.fillna(1).clip(1, 6)
    cap = np.where(is_area, feats.geometry.area * levels * USABLE_SHARE / M2_PER_PERSON, DEFAULT_CAPACITY)
    feats["capacity"] = np.clip(np.round(cap, -1), MIN_CAPACITY, 2000).astype(int)
    feats["capacity_source"] = np.where(is_area, "footprint estimate", "default estimate")
    feats["kind"] = feats.apply(_kind, axis=1)
    feats["name"] = feats.get("name", pd.Series(index=feats.index, dtype=object)).fillna(
        feats["kind"].str.replace("_", " ").str.title() + " (unnamed)")
    feats["geometry"] = feats.geometry.representative_point()
    feats = feats[feats["capacity"] >= MIN_CAPACITY]
    # de-duplicate: a school mapped as both node and polygon -> keep the larger capacity within 60 m
    feats = feats.sort_values("capacity", ascending=False)
    keep, taken = [], []
    for idx, pt in zip(feats.index, feats.geometry):
        if any(pt.distance(t) < 60 for t in taken[-400:]):
            continue
        keep.append(idx)
        taken.append(pt)
    feats = feats.loc[keep]
    feats["shelter_id"] = [f"S{i:04d}" for i in range(len(feats))]
    feats["verified"] = False
    feats["facilities"] = feats["kind"].map(lambda k: ", ".join(FACILITIES.get(k, ["hall"])))
    gdf = feats[["shelter_id", "name", "kind", "capacity", "capacity_source", "verified", "facilities", "geometry"]]
    write_gdf(gdf.to_crs(cfg.area["storage_crs"]), out)
    log.info("shelters: %d candidates, total estimated capacity %d", len(gdf), gdf["capacity"].sum())
    return out
