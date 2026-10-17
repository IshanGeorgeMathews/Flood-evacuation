"""Directed drive graph as compact arrays (CSR-friendly) with travel times and road attributes.

Outputs data/processed/edges.parquet and nodes.parquet. Edge risk p(e) is the maximum predicted probability over
the edge's ~100 m segments (a route is only as safe as its worst stretch); both directions of a two-way road share it.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import write_gdf, write_table
from floodevac.common.logging import get_logger

log = get_logger(__name__)


def _speed_kmh(highway: pd.Series, maxspeed: pd.Series, speeds: dict) -> np.ndarray:
    base = highway.fillna("").str.replace("_link", "", regex=False).map(speeds).fillna(speeds["default"])
    parsed = maxspeed.fillna("").astype(str).map(lambda s: float(m.group()) if (m := re.search(r"\d+", s)) else np.nan)
    return np.where(np.isfinite(parsed) & (parsed > 5), np.minimum(parsed, base * 1.5), base)


def build(cfg: Config) -> Path:
    out = cfg.paths.processed / "edges.parquet"
    if out.exists() and not cfg.force:
        return out
    from floodevac.ingest import osm

    edges = osm.edges_gdf(cfg)
    edges["ekey"] = osm.edge_key(edges["u"], edges["v"], edges["length"])
    edges["speed_kmh"] = _speed_kmh(edges["highway"], edges["maxspeed"], cfg.routing["speeds_kmh"])
    edges["t_s"] = edges["length"] / (edges["speed_kmh"] / 3.6)
    edges = edges.reset_index(drop=True)
    edges["eid"] = np.arange(len(edges), dtype="int32")
    cols = ["eid", "u", "v", "key", "ekey", "highway", "name", "ref", "length", "speed_kmh", "t_s", "is_bridge",
            "is_causeway", "road_class_rank", "geometry"]
    write_gdf(edges[cols], out)

    G = osm.load_graph(cfg)
    nodes = pd.DataFrame([(n, d["x"], d["y"]) for n, d in G.nodes(data=True)], columns=["node", "lon", "lat"])
    write_table(nodes, cfg.paths.processed / "nodes.parquet")
    log.info("routing graph: %d nodes, %d directed edges", len(nodes), len(edges))
    return out


def edge_risk(edges: pd.DataFrame, seg_ekey: np.ndarray, seg_p: np.ndarray) -> np.ndarray:
    """Max segment probability per edge (via the direction-free edge key). Edges without segments get 0."""
    s = pd.Series(seg_p).groupby(seg_ekey).max()
    return edges["ekey"].map(s).fillna(0.0).to_numpy(dtype="float64")


def congestion(edges: gpd.GeoDataFrame, seg: pd.DataFrame) -> np.ndarray:
    """k(e) in [0,1]: population density along the edge relative to the district's 95th percentile."""
    pop = seg.groupby("ekey")["pop_density"].mean()
    v = edges["ekey"].map(pop).fillna(0.0).to_numpy()
    p95 = np.nanpercentile(v[v > 0], 95) if (v > 0).any() else 1.0
    return np.clip(v / p95, 0, 1)
