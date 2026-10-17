"""OpenStreetMap ingestion: district boundary, taluks, drive network and ~100 m road segments."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import ops
from shapely.geometry import LineString

from floodevac.common.config import Config
from floodevac.common.io import write_gdf
from floodevac.common.logging import get_logger

log = get_logger(__name__)

ROAD_CLASS_RANK = {
    "motorway": 1, "motorway_link": 1, "trunk": 2, "trunk_link": 2, "primary": 3, "primary_link": 3,
    "secondary": 4, "secondary_link": 4, "tertiary": 5, "tertiary_link": 5, "unclassified": 6,
    "residential": 7, "living_street": 8, "service": 8, "road": 7,
}


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
    "https://overpass.kumi.systems/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def overpass(fn, *args, rounds: int = 4, **kwargs):
    """Call an osmnx download function, rotating through Overpass mirrors when one is overloaded."""
    import osmnx as ox

    import time

    last: Exception | None = None
    for attempt in range(rounds):
        for url in OVERPASS_MIRRORS:
            ox.settings.overpass_url = url
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                last = exc
                log.warning("Overpass %s failed (%s); trying next mirror", url, str(exc).splitlines()[0][:120])
        if attempt < rounds - 1:
            log.info("all Overpass mirrors busy; retrying in %d s", 60 * (attempt + 1))
            time.sleep(60 * (attempt + 1))
    raise RuntimeError("all Overpass mirrors failed") from last


def _first(v):
    """OSM tags merged during simplification can be lists; take the first value."""
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _setup_osmnx(cfg: Config):
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(cfg.paths.raw / "osm_cache")
    ox.settings.log_console = False
    ox.settings.requests_timeout = 180
    ox.settings.overpass_rate_limit = False  # mirrors report slot status inconsistently; we rotate instead
    extra = ["bridge", "tunnel", "embankment", "layer", "maxspeed", "name", "highway", "ref"]
    ox.settings.useful_tags_way = list(dict.fromkeys(list(ox.settings.useful_tags_way) + extra))
    return ox


def boundary_path(cfg: Config) -> Path:
    return cfg.paths.processed / "boundary.parquet"


def graph_path(cfg: Config) -> Path:
    return cfg.paths.interim / "drive.graphml"


def fetch_boundary(cfg: Config) -> Path:
    out = boundary_path(cfg)
    if out.exists() and not cfg.force:
        return out
    ox = _setup_osmnx(cfg)
    gdf = ox.geocode_to_gdf(cfg.area["place_query"])[["geometry"]]
    gdf["name"] = cfg.area["name"]
    write_gdf(gdf.to_crs(cfg.area["storage_crs"]), out)
    log.info("boundary saved")
    return out


def fetch_taluks(cfg: Config) -> Path:
    """Taluk polygons (OSM admin_level=6 inside the district)."""
    out = cfg.paths.processed / "taluks.parquet"
    if out.exists() and not cfg.force:
        return out
    ox = _setup_osmnx(cfg)
    district = gpd.read_parquet(fetch_boundary(cfg))
    poly = district.geometry.iloc[0]
    feats = overpass(ox.features_from_polygon, poly, tags={"boundary": "administrative", "admin_level": "6"})
    feats = feats[feats.geometry.type.isin(["Polygon", "MultiPolygon"])].reset_index()
    feats = feats[["name", "geometry"]].dropna(subset=["name"])
    # keep taluks mostly inside the district
    metric = cfg.area["metric_crs"]
    dm = district.to_crs(metric).geometry.iloc[0]
    fm = feats.to_crs(metric)
    share = fm.geometry.intersection(dm).area / fm.geometry.area
    feats = feats[share.values > 0.5].copy()
    feats["geometry"] = feats.geometry.intersection(poly)
    feats = feats.dissolve(by="name", as_index=False)
    write_gdf(feats.to_crs(cfg.area["storage_crs"]), out)
    log.info("taluks saved: %s", ", ".join(sorted(feats["name"])))
    return out


def fetch_graph(cfg: Config) -> Path:
    out = graph_path(cfg)
    if out.exists() and not cfg.force:
        return out
    ox = _setup_osmnx(cfg)
    district = gpd.read_parquet(fetch_boundary(cfg))
    metric = cfg.area["metric_crs"]
    poly = district.to_crs(metric).buffer(cfg.area["buffer_m"]).to_crs("EPSG:4326").iloc[0]
    log.info("downloading OSM drive network (this can take several minutes)…")
    G = overpass(ox.graph_from_polygon, poly, network_type="drive", simplify=True, retain_all=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, out)
    log.info("graph saved: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return out


def load_graph(cfg: Config):
    ox = _setup_osmnx(cfg)
    return ox.load_graphml(fetch_graph(cfg))


def edges_gdf(cfg: Config) -> gpd.GeoDataFrame:
    """Graph edges as a tidy GeoDataFrame in storage CRS with cleaned tags."""
    ox = _setup_osmnx(cfg)
    G = load_graph(cfg)
    edges = ox.graph_to_gdfs(G, nodes=False).reset_index()
    for col in ("highway", "bridge", "tunnel", "embankment", "name", "maxspeed", "ref"):
        if col not in edges:
            edges[col] = None
        edges[col] = edges[col].map(_first)
    edges["is_bridge"] = edges["bridge"].isin(["yes", "viaduct", "aqueduct", "boardwalk", "movable", "cantilever"]).astype(int)
    name_l = edges["name"].fillna("").str.lower()
    edges["is_causeway"] = (
        (edges["embankment"] == "yes") | (edges["bridge"] == "causeway") | name_l.str.contains("causeway|bund")
    ).astype(int)
    edges["road_class_rank"] = edges["highway"].map(ROAD_CLASS_RANK).fillna(7).astype(int)
    keep = ["u", "v", "key", "highway", "name", "ref", "maxspeed", "length", "is_bridge", "is_causeway",
            "road_class_rank", "geometry"]
    return edges[keep].set_crs("EPSG:4326", allow_override=True)


def edge_key(u: pd.Series, v: pd.Series, length: pd.Series) -> pd.Series:
    """Direction-free key of a physical road edge, shared by u->v and v->u."""
    a = np.minimum(u.to_numpy(), v.to_numpy())
    b = np.maximum(u.to_numpy(), v.to_numpy())
    return pd.Series([f"{x}_{y}_{int(round(l))}" for x, y, l in zip(a, b, length.to_numpy())], index=u.index)


def split_line(line: LineString, seg_len: float) -> list[LineString]:
    """Split a metric LineString into n roughly equal pieces of about seg_len metres."""
    n = max(1, int(round(line.length / seg_len)))
    if n == 1:
        return [line]
    step = line.length / n
    return [ops.substring(line, i * step, (i + 1) * step) for i in range(n)]


def build_segments(cfg: Config) -> Path:
    """Split every drive edge into ~100 m segments with a stable seg_id = u_v_key_i."""
    out = cfg.paths.processed / "segments_base.parquet"
    if out.exists() and not cfg.force:
        return out
    metric = cfg.area["metric_crs"]
    seg_len = float(cfg.area["segment_length_m"])
    edges = edges_gdf(cfg).to_crs(metric)
    # two-way roads appear as u->v and v->u: keep one physical copy (risk is mapped back to both directions)
    edges["ekey"] = edge_key(edges["u"], edges["v"], edges["length"])
    edges = edges.drop_duplicates("ekey")
    rows = []
    for rec in edges.itertuples(index=False):
        for i, piece in enumerate(split_line(rec.geometry, seg_len)):
            rows.append((f"{rec.u}_{rec.v}_{rec.key}_{i}", rec.u, rec.v, rec.key, i, piece))
    seg = gpd.GeoDataFrame(
        pd.DataFrame(rows, columns=["seg_id", "u", "v", "key", "i", "geometry"]), geometry="geometry", crs=metric
    )
    attrs = edges.drop(columns="geometry")
    seg = seg.merge(attrs[["u", "v", "key", "ekey", "highway", "name", "is_bridge", "is_causeway",
                           "road_class_rank"]], on=["u", "v", "key"], how="left")
    seg["seg_len_m"] = seg.geometry.length
    write_gdf(seg.to_crs(cfg.area["storage_crs"]), out)
    log.info("segments saved: %d segments from %d edges (%.0f km)", len(seg), len(edges), seg["seg_len_m"].sum() / 1000)
    return out


GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_3.json.zip"
# GADM uses older spellings / headquarters names; map them to the current official taluk names
GADM_TALUK_NAMES = {"Alwaye": "Aluva", "Cochin": "Kochi", "Ernakulam": "Kanayannur", "Kotamangalam": "Kothamangalam",
                    "Muvattupula": "Muvattupuzha", "Parur": "North Paravur", "Perumbavur": "Kunnathunad"}


def fetch_taluks_gadm(cfg: Config) -> Path:
    """Fallback taluk polygons from GADM 4.1 level 3 (licence: free for non-commercial use; see docs)."""
    from floodevac.common.io import download

    out = cfg.paths.processed / "taluks.parquet"
    z = download(GADM_URL, cfg.paths.raw / "gadm41_IND_3.json.zip", force=cfg.force)
    g = gpd.read_file(f"zip://{z.as_posix()}")
    g = g[(g["NAME_1"] == "Kerala") & (g["NAME_2"] == cfg.area["name"])]
    g = g.rename(columns={"NAME_3": "name"})[["name", "geometry"]]
    g["name"] = g["name"].replace(GADM_TALUK_NAMES)
    g = g.dissolve(by="name", as_index=False)
    g["source"] = "GADM 4.1"
    write_gdf(g.to_crs(cfg.area["storage_crs"]), out)
    log.info("taluks (GADM fallback): %s", ", ".join(sorted(g["name"])))
    return out


def fetch(cfg: Config) -> Path:
    fetch_boundary(cfg)
    fetch_graph(cfg)
    try:
        fetch_taluks(cfg)
    except Exception as exc:  # noqa: BLE001 - fall back to GADM, then carry on without taluks
        log.warning("OSM taluk boundaries unavailable (%s); trying GADM", str(exc)[:120])
        try:
            fetch_taluks_gadm(cfg)
        except Exception as exc2:  # noqa: BLE001
            log.warning("taluk boundaries unavailable: %s", exc2)
    return build_segments(cfg)
