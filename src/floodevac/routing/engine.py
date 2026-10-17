"""Engine: one object that ties segments, the model, the road network and the router together.

The Flask API, the refresh job, the what-if simulator and the 2018 replay all go through `Engine.evaluate()`, so a
risk picture is computed exactly one way everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.logging import get_logger
from floodevac.features.build_table import FeatureStore
from floodevac.models.predict import Predictor
from floodevac.routing import cost, graph
from floodevac.routing.router import Network, RiskState, Router

log = get_logger(__name__)


@dataclass
class Picture:
    """A complete risk picture for one date/scenario."""
    date: pd.Timestamp
    rain_offset_mm: float
    mode: str
    p_seg: np.ndarray
    state: RiskState
    features: pd.DataFrame


class Engine:
    def __init__(self, cfg: Config, holdout_model: bool = False):
        self.cfg = cfg
        P = cfg.paths.processed
        seg = gpd.read_parquet(P / "segments.parquet")
        self.seg = seg
        self.seg_ekey = seg["ekey"].to_numpy()
        self.seg_pop = seg["pop_density"].fillna(0).to_numpy()
        store = FeatureStore(cfg, seg[["seg_id", "cell_id", "station", *cfg.model["features"]["static"]]].copy())
        self.predictor = Predictor(cfg, store, holdout=holdout_model)
        self.store = store
        edges = gpd.read_parquet(graph.build(cfg))
        nodes = pd.read_parquet(P / "nodes.parquet")
        self.net = Network(edges, nodes)
        self.k_edge = graph.congestion(edges, seg)
        shelters = gpd.read_parquet(P / "shelters_base.parquet")
        shelters = shelters[shelters["capacity"] >= cfg.routing.get("shelter_min_capacity", 0)].reset_index(drop=True)
        shelters["lon"], shelters["lat"] = shelters.geometry.x, shelters.geometry.y
        self.presets = cost.presets(cfg.routing)
        self.router = Router(self.net, pd.DataFrame(shelters.drop(columns="geometry")), self.presets, cfg.routing)
        # node of each segment (its edge's tail) for demand aggregation
        node_index = pd.Series(np.arange(self.net.n), index=nodes["node"].to_numpy())
        self.seg_node = node_index.reindex(seg["u"].to_numpy()).fillna(0).astype(int).to_numpy()
        log.info("engine ready: %d segments, %d nodes, %d shelters", len(seg), self.net.n, len(shelters))

    def evaluate(self, date: pd.Timestamp, rain_offset_mm: float = 0.0) -> Picture:
        scores = self.predictor.score(pd.Timestamp(date), self.seg["seg_id"], rain_offset_mm=rain_offset_mm)
        p_seg = scores.p
        p_edge = graph.edge_risk(self.net.edges, self.seg_ekey, p_seg)
        # people along at-risk roads become shelter demand at the road's nearest node
        at_risk = p_seg > self.cfg.routing["risky_p"]
        demand = np.bincount(self.seg_node[at_risk], weights=self.seg_pop[at_risk], minlength=self.net.n)
        state = self.router.update(p_edge, self.k_edge, demand)
        return Picture(pd.Timestamp(date), rain_offset_mm, scores.mode, p_seg, state, scores.features)

    # --- summaries used by the API and reports
    def kpis(self, pic: Picture, preset: str) -> dict:
        pr = self.presets[preset]
        risky = pic.p_seg > self.cfg.routing["risky_p"]
        seg_len = self.seg["seg_len_m"].to_numpy()
        crossing = ((self.seg["is_bridge"] == 1) | (self.seg["is_causeway"] == 1)).to_numpy()
        blocked = cost.blocked(pic.p_seg, crossing, pr)
        open_ = pic.state.shelter_open[preset]
        demand = pic.state.demand[preset]
        cap = self.router.capacity
        return {
            "roads_at_risk_km": float(seg_len[risky].sum() / 1000),
            "roads_blocked_km": float(seg_len[blocked].sum() / 1000),
            "segments_at_risk": int(risky.sum()),
            "people_exposed": int(self.seg_pop[risky].sum()),
            "shelters_open": int(open_.sum()),
            "shelters_total": int(len(open_)),
            "shelter_capacity": int(cap[open_].sum()),
            "shelter_demand": int(demand.sum()),
            "capacity_used_pct": float(100 * demand.sum() / max(cap[open_].sum(), 1)),
            "network_km": float(seg_len.sum() / 1000),
            "mean_p": float(pic.p_seg.mean()),
        }
