"""Service layer behind the API.

`LiveService` runs the real system: engine, live feeds, refresh cycle, scenario cache and the SSE event bus.
`FixtureService` serves recorded JSON responses from tests/fixtures (used by the test-suite and whenever the data
pipeline has not been run); every response it serves is flagged as mock data so the UI shows a MOCK DATA chip.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import queue
import threading
from collections import OrderedDict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import read_json
from floodevac.common.logging import get_logger

log = get_logger(__name__)

# Historical days offered in the simulator: the system runs on that day's real IMD rainfall and CWC river levels
SIM_DAYS = [
    {"date": "2018-08-09", "label": "9 Aug 2018: Idukki and Idamalayar dams open"},
    {"date": "2018-08-15", "label": "15 Aug 2018: Periyar rising fast"},
    {"date": "2018-08-16", "label": "16 Aug 2018: peak of the Kerala flood"},
    {"date": "2018-08-17", "label": "17 Aug 2018: Aluva and Paravur cut off"},
    {"date": "2018-08-21", "label": "21 Aug 2018: receding (Sentinel-1 pass)"},
    {"date": "2019-08-09", "label": "9 Aug 2019: second flood"},
    {"date": "2019-08-10", "label": "10 Aug 2019: Sentinel-1 pass"},
    {"date": "2024-07-30", "label": "30 Jul 2024: extreme rain (Wayanad day)"},
]
# Days with IMD rainfall in the processed data (river levels exist for June-November from 2018)
SIM_RANGE = ["2017-01-08", "2024-12-31"]

# "Relative risk" map view: class boundaries at the day's 95th, 98th and 99.5th percentile of road probability
RANK_QUANTILES = [0.95, 0.98, 0.995]

RISK_BINS = [0, 0.02, 0.05, 0.10, 0.20, 0.40, 1.0001]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def risk_class(p: np.ndarray, bounds: list[float]) -> np.ndarray:
    """0 Low, 1 Watch, 2 High, 3 Severe (boundaries from configs/routing.yaml: risk_classes)."""
    return np.digitize(p, bounds)


class EventBus:
    """Fan-out of server-sent events to every connected browser."""

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=50)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: str, data: dict) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            for q in list(self._subs):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


# ------------------------------------------------------------------------------------------------------- live

class LiveService:
    mock = False

    def __init__(self, cfg: Config):
        from floodevac.routing.engine import Engine

        self.cfg = cfg
        self.bus = EventBus()
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.engine = Engine(cfg)
        self.presets = list(self.engine.presets)
        self._prepare_display()
        self._prepare_taluks()
        self.live = None
        self.live_pic = None
        self.prev_blocked: set[int] = set()
        self.refreshed_at: str | None = None
        self.scenarios: OrderedDict[tuple, object] = OrderedDict()

    # ---- setup
    def _prepare_display(self) -> None:
        """One display line per physical road (both directions share one), with compact coordinates."""
        net = self.engine.net
        e = net.edges
        first = ~e["ekey"].duplicated()
        self.disp_eid = np.flatnonzero(first.to_numpy())
        self.disp_coords = [np.round(net.coords[i][:, ::-1], 5).tolist() for i in self.disp_eid]
        mids = np.array([net.coords[i][len(net.coords[i]) // 2] for i in self.disp_eid])
        self.disp_lat, self.disp_lon = mids[:, 0], mids[:, 1]
        self.disp_rank = e["road_class_rank"].to_numpy()[self.disp_eid]
        self.disp_name = e["name"].fillna("").to_numpy()[self.disp_eid]
        self.disp_bridge = net.crossing[self.disp_eid]
        # segments per edge key, for explanations
        self.seg_by_ekey = pd.Series(np.arange(len(self.engine.seg))).groupby(self.engine.seg_ekey).apply(list)

    def _prepare_taluks(self) -> None:
        path = self.cfg.paths.processed / "taluks.parquet"
        self.taluk_gdf = gpd.read_parquet(path) if path.exists() else None
        self.seg_taluk = None
        if self.taluk_gdf is not None and len(self.taluk_gdf):
            pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(self.engine.seg["lon"], self.engine.seg["lat"]),
                                   crs="EPSG:4326")
            j = gpd.sjoin(pts, self.taluk_gdf[["name", "geometry"]], how="left", predicate="within")
            j = j[~j.index.duplicated()]
            self.seg_taluk = j["name"].reindex(range(len(pts))).to_numpy()
            sh = self.engine.router.shelters
            spts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(sh["lon"], sh["lat"]), crs="EPSG:4326")
            js = gpd.sjoin(spts, self.taluk_gdf[["name", "geometry"]], how="left", predicate="within")
            self.shelter_taluk = js[~js.index.duplicated()]["name"].reindex(range(len(sh))).to_numpy()

    # ---- refresh
    def refresh(self) -> None:
        with self.refresh_lock:
            self._refresh()

    def _refresh(self) -> None:
        from floodevac.jobs.refresh import collect

        live = collect(self.cfg)
        with self.lock:
            st = self.engine.store
            st.add_live(live.rain_cell, live.rain_up, live.gauge_rel)
            pic = self.engine.evaluate(live.live_date)
            self.live, self.live_pic = live, pic
            self.scenarios.clear()
            self.refreshed_at = _now()
            pr = self.engine.presets["balanced"]
            from floodevac.routing.cost import blocked

            now_blocked = set(np.flatnonzero(blocked(pic.state.p_edge, self.engine.net.crossing, pr)).tolist())
            newly = now_blocked - self.prev_blocked if self.prev_blocked else set()
            self.prev_blocked = now_blocked
        log.info("refresh done: live date %s, mode %s, %d edges blocked (balanced)", live.live_date.date(), pic.mode,
                 len(now_blocked))
        self.bus.publish("refresh", {"refreshed_at": self.refreshed_at, "live_date": str(live.live_date.date()),
                                     "mode": pic.mode, "newly_blocked": len(newly),
                                     "newly_blocked_edges": sorted(newly)[:500]})

    def picture(self, scenario: float = 0.0, sim_date: str | None = None):
        """Risk picture for live conditions, or for a historical day (`sim_date`), plus optional what-if rain."""
        if self.live_pic is None:
            with self.refresh_lock:  # wait for the start-up refresh instead of starting a second one
                if self.live_pic is None:
                    self._refresh()
        scenario = float(round(scenario or 0.0))
        if scenario == 0 and not sim_date:
            return self.live_pic
        key = (sim_date, scenario)
        with self.lock:
            if key in self.scenarios:
                self.scenarios.move_to_end(key)
                return self.scenarios[key]
            day = pd.Timestamp(sim_date) if sim_date else self.live.live_date
            pic = self.engine.evaluate(day, rain_offset_mm=scenario)
            # evaluating a scenario must not change the live routing state
            self.engine.router.state = self.live_pic.state
            self.scenarios[key] = pic
            while len(self.scenarios) > 10:
                self.scenarios.popitem(last=False)
            return pic

    # ---- endpoints
    def status(self) -> dict:
        pic = self.picture()
        feeds = [f.as_dict() for f in self.live.feeds.values()]
        model_dir = self.cfg.paths.models / self.engine.predictor.version
        trained = read_json(model_dir / "metrics.json").get("trained_at", "")
        feeds.append({"name": "model", "source": f"flood-risk model {self.engine.predictor.version}", "state": "ok",
                      "last_ok": trained, "age_s": None, "data_date": trained[:10], "detail": ""})
        osm_file = self.cfg.paths.interim / "drive.graphml"
        osm_time = dt.datetime.fromtimestamp(osm_file.stat().st_mtime).isoformat(timespec="seconds") \
            if osm_file.exists() else None
        feeds.append({"name": "roads", "source": "OpenStreetMap drive network", "state": "ok", "last_ok": osm_time,
                      "age_s": None, "data_date": (osm_time or "")[:10], "detail": f"{self.engine.net.n} junctions"})
        return {"feeds": feeds, "model_version": self.engine.predictor.version, "mode": pic.mode,
                "live_date": str(self.live.live_date.date()), "refreshed_at": self.refreshed_at,
                "data_source": "live", "refresh_minutes": int(self.cfg.refresh["interval_minutes"]), "mock": False,
                "presets": self.cfg.routing["presets"], "risky_p": self.cfg.routing["risky_p"],
                "risk_classes": self.cfg.routing["risk_classes"], "sim_days": SIM_DAYS,
                "sim_range": SIM_RANGE}

    def risk(self, bbox: list[float] | None, zoom: int, scenario: float, min_p: float = 0.0,
             replay_layer: dict | None = None, sim_date: str | None = None, rank: bool = False) -> dict:
        """Road risk layer. rank=True colours by the day's relative ranking (top 5% / 2% / 0.5% of roads) instead of
        absolute calibrated probability; routing always uses the calibrated probability."""
        pic = self.picture(scenario, sim_date) if replay_layer is None else None
        p_all = pic.state.p_edge[self.disp_eid] if pic is not None else replay_layer["p_disp"]
        sel = np.ones(len(self.disp_eid), dtype=bool)
        if bbox:
            x0, y0, x1, y1 = bbox
            sel &= (self.disp_lon >= x0) & (self.disp_lon <= x1) & (self.disp_lat >= y0) & (self.disp_lat <= y1)
        bounds = self.cfg.routing["risk_classes"]
        rank_bounds = [float(v) for v in np.quantile(p_all, RANK_QUANTILES)]
        if rank:
            bounds = [max(b, 1e-6) for b in rank_bounds]
        watch = bounds[0]
        if zoom < 12:
            sel &= (p_all >= watch) | (self.disp_rank <= 3)
        elif zoom < 14:
            sel &= (p_all >= watch / 2) | (self.disp_rank <= 6)
        sel &= p_all >= min_p
        idx = np.flatnonzero(sel)
        cap = 30000
        if len(idx) > cap:
            idx = idx[np.argsort(-p_all[idx])[:cap]]
        cls = risk_class(p_all[idx], bounds)
        feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": self.disp_coords[i]},
                  "properties": {"eid": int(self.disp_eid[i]), "p": round(float(p_all[i]), 3), "c": int(c),
                                 "b": int(self.disp_bridge[i]), "r": int(self.disp_rank[i])}}
                 for i, c in zip(idx, cls)]
        meta = {"count": len(feats), "zoom": zoom, "scenario_mm": scenario,
                "date": str(pic.date.date()) if pic is not None else replay_layer["date"],
                "mode": pic.mode if pic is not None else "replay", "bins": RISK_BINS[:-1],
                "colour": "rank" if rank else "probability", "class_bounds": bounds,
                "rank_bounds": rank_bounds}
        return {"type": "FeatureCollection", "features": feats, "meta": meta}

    def route(self, lat: float, lon: float, preset: str, scenario: float, sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        res = self.engine.router.route(lon, lat, preset, state=pic.state)
        for r in res["routes"]:
            r.pop("edges", None)
        res["data_ts"] = self.refreshed_at or _now()
        res["date"] = str(pic.date.date())
        res["scenario_mm"] = scenario
        return res

    def shelters(self, preset: str, scenario: float, sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        sh = self.engine.router.shelters
        open_ = pic.state.shelter_open[preset]
        demand = pic.state.demand[preset]
        feats = []
        for i, r in enumerate(sh.itertuples()):
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r.lon, 5),
                                                                                         round(r.lat, 5)]},
                          "properties": {"id": r.shelter_id, "name": r.name, "kind": r.kind,
                                         "capacity": int(r.capacity), "capacity_source": r.capacity_source,
                                         "demand": int(round(demand[i])), "open": bool(open_[i]),
                                         "p_flood": round(float(pic.state.shelter_p[i]), 3),
                                         "verified": bool(r.verified), "facilities": r.facilities}})
        return {"type": "FeatureCollection", "features": feats}

    def gauges(self, sim_date: str | None = None) -> dict:
        from floodevac.jobs.refresh import summarise_gauges

        self.picture()
        if not sim_date:
            return {"gauges": summarise_gauges(self.cfg, self.live.gauge_hourly),
                    "source": "CWC flood forecasting portal"}
        # historical day: daily maximum levels for the 10 days up to the simulated date
        day = pd.Timestamp(sim_date)
        daily = pd.read_parquet(self.cfg.paths.processed / "gauge_daily.parquet")
        daily = daily[(daily["date"] > day - pd.Timedelta(days=10)) & (daily["date"] <= day)]
        hourly = daily.rename(columns={"date": "time"})[["station", "time", "level"]]
        return {"gauges": summarise_gauges(self.cfg, hourly, hours=24 * 10),
                "source": f"CWC daily maximum levels, 10 days to {sim_date} (historical)"}

    def simulate(self, rain_mm_3d: float, preset: str, sim_date: str | None = None) -> dict:
        base_pic = self.picture(0, sim_date)
        base = self.engine.kpis(base_pic, preset)
        pic = self.picture(rain_mm_3d, sim_date)
        k = self.engine.kpis(pic, preset)
        delta = {key: k[key] - base[key] for key in k if isinstance(k[key], (int, float))}
        newly = int(((pic.p_seg > self.cfg.routing["risky_p"]) &
                     (base_pic.p_seg <= self.cfg.routing["risky_p"])).sum())
        return {"rain_mm_3d": float(rain_mm_3d), "kpis": k, "baseline": base, "delta": delta,
                "segments_newly_at_risk": newly, "preset": preset, "date": str(pic.date.date()),
                "sim_date": sim_date}

    def explain(self, eid: int, scenario: float, sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        e = self.engine.net.edges.iloc[eid]
        segs = self.seg_by_ekey.get(e["ekey"], [])
        if not len(segs):
            return {"eid": eid, "p": 0.0, "top": [], "road": {}, "base_value_note": "no model segment"}
        segs = np.asarray(segs)
        worst = int(segs[np.argmax(pic.p_seg[segs])])
        row = pic.features.iloc[[worst]]
        top = self.engine.predictor.explain(row)
        seg = self.engine.seg.iloc[worst]
        fv = {c: (None if pd.isna(row[c].iloc[0]) else float(row[c].iloc[0]))
              for c in ["elev", "hand", "dist_stream_m", "slope", "rain_3d", "rain_up_3d", "gauge_near_rel",
                        "past_flood_freq", "landcover_water", "landcover_built"]}
        return {"eid": int(eid), "p": float(pic.p_seg[worst]), "top": top,
                "road": {"name": seg["name"] if isinstance(seg["name"], str) else "", "highway": seg["highway"],
                         "length_m": float(e["length"]), "bridge": bool(seg["is_bridge"]),
                         "causeway": bool(seg["is_causeway"]), "segment": seg["seg_id"],
                         "nearest_gauge": seg["station"], "values": fv},
                "base_value_note": "SHAP values are contributions to the model's log-odds before calibration",
                "date": str(pic.date.date()), "scenario_mm": scenario}

    def isochrone(self, lat: float, lon: float, minutes: float, preset: str, scenario: float,
                  sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        return self.engine.router.isochrone(lon, lat, minutes, preset, state=pic.state)

    def replay_summary(self) -> dict:
        return read_json(self.cfg.paths.processed / "replay" / "summary.json")

    def replay_day(self, date: str, bbox, zoom, rank: bool = False) -> dict:
        layer = read_json(self.cfg.paths.processed / "replay" / f"{date}.json")
        p_edge = np.zeros(len(self.engine.net.edges))
        p_edge[layer["edges"]] = layer["p"]
        payload = self.risk(bbox, zoom, 0, min_p=0.0 if rank else 0.01, rank=rank,
                            replay_layer={"p_disp": p_edge[self.disp_eid], "date": date})
        observed = []
        if "observed_edges" in layer:
            obs = np.zeros(len(self.engine.net.edges), dtype=bool)
            obs[layer["observed_edges"]] = True
            idx = np.flatnonzero(obs[self.disp_eid])
            observed = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": self.disp_coords[i]},
                         "properties": {"eid": int(self.disp_eid[i])}} for i in idx]
        summary = self.replay_summary()
        stats = next((d for d in summary["days"] if d["date"] == date), {})
        cmp_ = next((c for c in summary["comparisons"] if c["date"] == date), None)
        return {"date": date, "type": "FeatureCollection", "features": payload["features"], "meta": payload["meta"],
                "observed": {"type": "FeatureCollection", "features": observed}, "stats": stats, "comparison": cmp_}

    def stats(self, preset: str, scenario: float, sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        seg = self.engine.seg
        L = seg["seg_len_m"].to_numpy()
        hist, _ = np.histogram(pic.p_seg, bins=RISK_BINS, weights=L / 1000)
        bins = [{"from": RISK_BINS[i], "to": min(RISK_BINS[i + 1], 1.0), "km": float(hist[i])} for i in range(len(hist))]
        named = seg["name"].fillna("").astype(str)
        df = pd.DataFrame({"name": named, "p": pic.p_seg, "len": L, "lat": seg["lat"], "lon": seg["lon"],
                           "highway": seg["highway"].fillna("road").astype(str)})
        top = (df[df["name"] != ""].sort_values("p", ascending=False).drop_duplicates("name").head(10))
        risky = df[df["p"] > self.cfg.routing["risky_p"]]
        by_class = (risky.groupby("highway")["len"].sum().sort_values(ascending=False).head(8) / 1000)
        return {"kpis": self.engine.kpis(pic, preset), "histogram": bins,
                "top_segments": [{"name": r.name, "p": round(float(r.p), 3), "lat": float(r.lat), "lon": float(r.lon),
                                  "highway": r.highway} for r in top.itertuples()],
                "by_class": [{"highway": k, "km": float(v)} for k, v in by_class.items()],
                "date": str(pic.date.date()), "scenario_mm": scenario, "mode": pic.mode}

    def model(self) -> dict:
        m = read_json(self.cfg.paths.models / self.engine.predictor.version / "metrics.json")
        return m

    def rainfall(self, sim_date: str | None = None) -> dict:
        self.picture()
        if sim_date:
            day = pd.Timestamp(sim_date)
            grid = pd.read_parquet(self.cfg.paths.processed / "rain_grid.parquet")
            g = grid[(grid["date"] > day - pd.Timedelta(days=10)) & (grid["date"] <= day)]
            d = g.groupby("date")["rain_mm"].mean().reset_index()
            up = self.engine.store.rain_up
            u = up.loc[up["date"] == day, "rain_up_3d"]
            return {"daily": [{"date": str(r.date.date()), "mm": round(float(r.rain_mm), 1)} for r in d.itertuples()],
                    "forecast": [], "upstream_3d": float(u.iloc[0]) if len(u) and pd.notna(u.iloc[0]) else None,
                    "source": f"IMD gridded rainfall, 10 days to {sim_date} (historical)", "forecast_source": ""}
        live = self.live
        daily, forecast, up = [], [], None
        if live.rain_daily_mean is not None:
            d = live.rain_daily_mean.sort_values("date").tail(10)
            daily = [{"date": str(r.date.date()), "mm": round(float(r.rain_mm), 1)} for r in d.itertuples()]
        if live.forecast is not None and len(live.forecast):
            f = live.forecast.groupby("date")["rain_mm"].mean().reset_index()
            forecast = [{"date": str(r.date.date()), "mm": round(float(r.rain_mm), 1)} for r in f.itertuples()]
        if live.rain_up is not None and len(live.rain_up):
            up = float(live.rain_up.sort_values("date")["rain_up_3d"].iloc[-1])
        return {"daily": daily, "forecast": forecast, "upstream_3d": up,
                "source": live.feeds["rainfall"].source or "unavailable",
                "forecast_source": live.feeds["forecast"].source}

    def dams(self) -> dict:
        from floodevac.ingest import dams

        df = dams.load(self.cfg)
        rel = [{"dam": r.dam, "river": r.river, "lat": r.lat, "lon": r.lon, "event": r.event,
                "start": str(r.start_date.date()), "end": None if pd.isna(r.end_date) else str(r.end_date.date()),
                "confidence": r.confidence, "note": r.note} for r in df.itertuples()]
        return {"releases": rel, "note": "Dates as widely reported in the news, not yet verified against official KSEB/KSDMA notices. Context only — not a model input."}

    def alerts(self, preset: str) -> dict:
        from floodevac.jobs.refresh import summarise_gauges

        pic = self.picture()
        out = []
        for g in summarise_gauges(self.cfg, self.live.gauge_hourly, hours=6):
            if g["status"] in ("above danger", "above warning"):
                out.append({"level": "danger" if g["status"] == "above danger" else "warning",
                            "title": f"{g['name']} ({g['river']}) {g['status']}",
                            "detail": f"{g['level']:.2f} m vs danger {g['danger']:.2f} m", "time": g["updated"]})
        k = self.engine.kpis(pic, preset)
        if k["roads_blocked_km"] > 0.5:
            out.append({"level": "warning", "title": f"{k['roads_blocked_km']:.1f} km of road above the {preset} "
                        "risk threshold", "detail": "Routes avoid these sections.", "time": self.refreshed_at})
        for f in self.live.feeds.values():
            if f.state in ("stale", "down"):
                out.append({"level": "info", "title": f"{f.name} feed {f.state}",
                            "detail": f.detail or f.source, "time": f.last_ok})
            elif f.state == "provisional":
                out.append({"level": "info", "title": f"{f.name}: provisional data", "detail": f.source,
                            "time": f.last_ok})
        if pic.mode == "static-fallback":
            out.append({"level": "warning", "title": "Live rainfall unavailable",
                        "detail": "Showing terrain-based susceptibility (static model).", "time": self.refreshed_at})
        if not any(a["level"] in ("danger", "warning") for a in out):
            out.insert(0, {"level": "ok", "title": "No river gauge above warning level",
                           "detail": f"{k['roads_at_risk_km']:.1f} km of road above {self.cfg.routing['risky_p']:.0%} "
                                     "flood probability", "time": self.refreshed_at})
        return {"alerts": out, "generated_at": _now()}

    def taluks(self, preset: str, scenario: float, sim_date: str | None = None) -> dict:
        pic = self.picture(scenario, sim_date)
        if self.taluk_gdf is None or self.seg_taluk is None:
            return {"type": "FeatureCollection", "features": []}
        seg = self.engine.seg
        risky = pic.p_seg > self.cfg.routing["risky_p"]
        df = pd.DataFrame({"taluk": self.seg_taluk, "len": seg["seg_len_m"].to_numpy(), "risky": risky,
                           "pop": self.engine.seg_pop})
        g = df.groupby("taluk").apply(lambda x: pd.Series({
            "km_total": x["len"].sum() / 1000, "km_at_risk": x.loc[x["risky"], "len"].sum() / 1000,
            "people_exposed": x.loc[x["risky"], "pop"].sum()}), include_groups=False)
        sh = pd.DataFrame({"taluk": self.shelter_taluk, "cap": self.engine.router.capacity,
                           "open": pic.state.shelter_open[preset], "demand": pic.state.demand[preset]})
        shg = sh.groupby("taluk").agg(shelters=("cap", "size"), open=("open", "sum"), capacity=("cap", "sum"),
                                      demand=("demand", "sum"))
        feats = []
        for r in self.taluk_gdf.itertuples():
            a = g.loc[r.name] if r.name in g.index else None
            s = shg.loc[r.name] if r.name in shg.index else None
            props = {"name": r.name,
                     "km_total": float(a["km_total"]) if a is not None else 0.0,
                     "km_at_risk": float(a["km_at_risk"]) if a is not None else 0.0,
                     "people_exposed": int(a["people_exposed"]) if a is not None else 0,
                     "shelters": int(s["shelters"]) if s is not None else 0,
                     "shelters_open": int(s["open"]) if s is not None else 0,
                     "capacity": int(s["capacity"]) if s is not None else 0,
                     "demand": int(s["demand"]) if s is not None else 0}
            props["share_at_risk"] = props["km_at_risk"] / max(props["km_total"], 1e-9)
            geom = r.geometry.simplify(0.002)
            feats.append({"type": "Feature", "geometry": geom.__geo_interface__, "properties": props})
        return {"type": "FeatureCollection", "features": feats}

    def export_routes(self, preset: str, fmt: str) -> tuple[str, str]:
        from floodevac.routing.replay import TOWNS

        pic = self.picture()
        rows, feats = [], []
        origins = dict(TOWNS)
        if self.taluk_gdf is not None:
            for r in self.taluk_gdf.itertuples():
                c = r.geometry.representative_point()
                origins[f"{r.name} (taluk centre)"] = (c.x, c.y)
        for name, (lon, lat) in origins.items():
            res = self.engine.router.route(lon, lat, preset, state=pic.state)
            safest = next((r for r in res["routes"] if r["kind"] == "safest"), None)
            if safest is None:
                rows.append({"origin": name, "lat": lat, "lon": lon, "shelter": "", "eta_min": "", "dist_km": "",
                             "risky_m": "", "warnings": " | ".join(res["warnings"])})
                continue
            rows.append({"origin": name, "lat": lat, "lon": lon, "shelter": safest["shelter"]["name"],
                         "eta_min": round(safest["eta_s"] / 60, 1), "dist_km": round(safest["dist_m"] / 1000, 2),
                         "risky_m": round(safest["exposure_m"]), "warnings": " | ".join(res["warnings"])})
            feats.append({"type": "Feature", "geometry": safest["geometry"],
                          "properties": {k: v for k, v in rows[-1].items() if k not in ("lat", "lon")}})
        if fmt == "csv":
            buf = io.StringIO()
            pd.DataFrame(rows).to_csv(buf, index=False)
            return buf.getvalue(), "text/csv"
        return json.dumps({"type": "FeatureCollection", "features": feats,
                           "properties": {"preset": preset, "date": str(pic.date.date()),
                                          "generated_at": _now()}}), "application/geo+json"


# ------------------------------------------------------------------------------------------------------- fixtures

class FixtureService:
    """Serves recorded responses. Used by tests and when the pipeline has not produced real artefacts."""

    mock = True

    def __init__(self, fixtures_dir: Path):
        self.dir = fixtures_dir
        self.bus = EventBus()
        self.presets = ["cautious", "balanced", "fast"]

    def _load(self, name: str) -> dict:
        data = read_json(self.dir / f"{name}.json")
        if isinstance(data, dict):
            data["mock"] = True
        return data

    def refresh(self) -> None:
        self.bus.publish("refresh", {"refreshed_at": _now(), "mock": True, "newly_blocked": 0})

    def status(self):
        d = self._load("status")
        d["data_source"] = "fixtures"
        return d

    def risk(self, bbox, zoom, scenario, min_p=0.0, replay_layer=None, sim_date=None, rank=False):
        return self._load("risk")

    def route(self, lat, lon, preset, scenario, sim_date=None):
        return self._load("route")

    def shelters(self, preset, scenario, sim_date=None):
        return self._load("shelters")

    def gauges(self, sim_date=None):
        return self._load("gauges")

    def simulate(self, rain_mm_3d, preset, sim_date=None):
        d = self._load("simulate")
        d["rain_mm_3d"] = float(rain_mm_3d)
        return d

    def explain(self, eid, scenario, sim_date=None):
        return self._load("explain")

    def isochrone(self, lat, lon, minutes, preset, scenario, sim_date=None):
        return self._load("isochrone")

    def replay_summary(self):
        return self._load("replay_summary")

    def replay_day(self, date, bbox, zoom, rank=False):
        return self._load("replay_day")

    def stats(self, preset, scenario, sim_date=None):
        return self._load("stats")

    def model(self):
        return self._load("model")

    def rainfall(self, sim_date=None):
        return self._load("rainfall")

    def dams(self):
        return self._load("dams")

    def alerts(self, preset):
        return self._load("alerts")

    def taluks(self, preset, scenario, sim_date=None):
        return self._load("taluks")

    def export_routes(self, preset, fmt):
        if fmt == "csv":
            return "origin,shelter,eta_min,dist_km,risky_m,warnings\n", "text/csv"
        return json.dumps(self._load("route")), "application/geo+json"
