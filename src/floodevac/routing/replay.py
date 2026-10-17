"""August 2018 replay: the system's strongest evidence.

For every day of the event the *held-out* model (never trained on August 2018) scores the district, the router
recomputes shelter trees, and evacuation routes are drawn from a fixed set of origins. On the days Sentinel-1
observed the flood, each route is checked against the radar: how much of it runs through roads that were actually
under water, for the safest route versus the plain fastest route.

Outputs
  data/processed/replay/summary.json        per-day statistics + the observed-exposure comparison
  data/processed/replay/<date>.json         per-day edge risk (edges with p >= 0.01) for the replay widget
  docs/replay_report.md                     the short report for the client
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import write_json
from floodevac.common.logging import get_logger
from floodevac.routing.engine import Engine

log = get_logger(__name__)

DAYS = pd.date_range("2018-08-06", "2018-08-27", freq="D")
N_ORIGINS = 300
PRESET = "balanced"
# Towns hit hardest in 2018 (Periyar basin), used as named demo origins
TOWNS = {
    "Aluva": (76.3525, 10.1076), "North Paravur": (76.2120, 10.1460), "Angamaly": (76.3860, 10.1960),
    "Perumbavoor": (76.4760, 10.1150), "Kalady": (76.4380, 10.1680), "Chendamangalam": (76.2330, 10.1700),
}


def _origins(eng: Engine, seed: int = 7) -> pd.DataFrame:
    """Evaluation origins: the people who actually had to evacuate. Population-weighted road points between
    200 m and 2 km from any road the radar saw flooded during the event (so a route can choose to cross or avoid
    the flood), plus the named towns. The observed flood only picks *who* is evaluated; the model never sees it."""
    from scipy.spatial import cKDTree

    rng = np.random.default_rng(seed)
    lab = eng.store.labels
    flooded_ids = set(lab.loc[(lab["label"] == 1) & lab["date"].isin(pd.to_datetime(sorted(eng.predictor.exclude))),
                              "seg_id"])
    is_fl = eng.seg["seg_id"].isin(flooded_ids).to_numpy()
    k = np.cos(np.radians(10.0)) * 111_000
    xy = np.column_stack([eng.seg["lon"].to_numpy() * k, eng.seg["lat"].to_numpy() * 111_000])
    if is_fl.any():
        d, _ = cKDTree(xy[is_fl]).query(xy)
        cand = (d >= 200) & (d <= 2000)
    else:
        cand = np.ones(len(xy), dtype=bool)
    w = np.where(cand, eng.seg_pop + 1e-3, 0.0)
    w = w / w.sum()
    pick = rng.choice(len(w), size=min(N_ORIGINS, int((w > 0).sum())), replace=False, p=w)
    o = pd.DataFrame({"name": [f"origin {i}" for i in range(len(pick))],
                      "lon": eng.seg["lon"].to_numpy()[pick], "lat": eng.seg["lat"].to_numpy()[pick]})
    towns = pd.DataFrame([(k, *v) for k, v in TOWNS.items()], columns=["name", "lon", "lat"])
    return pd.concat([towns, o], ignore_index=True)


def _observed_flooded_ekeys(eng: Engine, date: pd.Timestamp) -> tuple[set[str], set[str]] | None:
    lab = eng.store.labels
    if lab is None:
        return None
    day = lab[lab["date"] == date]
    if day.empty:
        return None
    seg = eng.seg.set_index("seg_id")["ekey"]
    flooded = set(seg.reindex(day.loc[day["label"] == 1, "seg_id"]).dropna())
    observed = set(seg.reindex(day["seg_id"]).dropna())
    return flooded, observed


def run(cfg: Config) -> Path:
    out_dir = cfg.paths.processed / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    eng = Engine(cfg, holdout_model=True)
    origins = _origins(eng)
    edge_ekey = eng.net.edges["ekey"].to_numpy()
    edge_len = eng.net.length
    days, comparisons = [], []
    for day in DAYS:
        pic = eng.evaluate(day)
        k = eng.kpis(pic, PRESET)
        f = pic.features
        gauge = float(f["gauge_max_rel"].iloc[0]) if pd.notna(f["gauge_max_rel"].iloc[0]) else None
        rec = {"date": day.strftime("%Y-%m-%d"), "mode": pic.mode, **k,
               "rain_3d_mean": float(f["rain_3d"].mean()), "rain_up_3d": float(f["rain_up_3d"].iloc[0]),
               "gauge_max_rel": gauge}
        p_edge = pic.state.p_edge
        keep = np.flatnonzero(p_edge >= 0.01)
        layer = {"date": rec["date"], "edges": keep.tolist(), "p": np.round(p_edge[keep], 3).tolist()}
        obs = _observed_flooded_ekeys(eng, day)
        if obs is not None:
            flooded, observed = obs
            is_flooded = np.array([e in flooded for e in edge_ekey])
            layer["observed_edges"] = np.flatnonzero(is_flooded).tolist()
            stats = {"safest": [], "fastest": []}
            for o in origins.itertuples():
                res = eng.router.route(o.lon, o.lat, PRESET)
                for r in res["routes"]:
                    if r["kind"] in stats and r["dist_m"] > 0:
                        e = np.asarray(r["edges"], dtype=int)
                        wet = edge_len[e][is_flooded[e]].sum()
                        stats[r["kind"]].append((wet, r["dist_m"], r["eta_s"], wet > 0))
            cmp_ = {"date": rec["date"], "origins": int(len(origins)), "observed_flooded_edges": int(is_flooded.sum())}
            for kind, rows in stats.items():
                a = np.array(rows, dtype="float64") if rows else np.zeros((0, 4))
                cmp_[kind] = {
                    "routes": int(len(a)),
                    "flooded_m_total": float(a[:, 0].sum()),
                    "flooded_share_of_length": float(a[:, 0].sum() / max(a[:, 1].sum(), 1)),
                    "routes_touching_flood": int(a[:, 3].sum()),
                    "mean_eta_min": float(a[:, 2].mean() / 60) if len(a) else 0.0,
                    "mean_dist_km": float(a[:, 1].mean() / 1000) if len(a) else 0.0,
                }
            comparisons.append(cmp_)
            rec["observed"] = True
            log.info("replay %s: safest %.2f%% vs fastest %.2f%% of route length on radar-flooded roads",
                     rec["date"], 100 * cmp_["safest"]["flooded_share_of_length"],
                     100 * cmp_["fastest"]["flooded_share_of_length"])
        write_json(layer, out_dir / f"{rec['date']}.json")
        days.append(rec)
        log.info("replay %s: %.1f km at risk, mode %s", rec["date"], k["roads_at_risk_km"], pic.mode)
    summary = {"preset": PRESET, "model": "held-out (trained without August 2018)", "days": days,
               "comparisons": comparisons, "towns": TOWNS}
    write_json(summary, out_dir / "summary.json")
    _report(cfg, summary)
    return out_dir / "summary.json"


def _report(cfg: Config, s: dict) -> None:
    lines = [
        "# August 2018 replay: safest vs fastest routes",
        "",
        "The **held-out model** (trained without any August 2018 data) scored the Ernakulam road network day by",
        "day from 6 to 27 August 2018, using that day's IMD rainfall and CWC river levels. On each day the",
        "router recomputed evacuation routes from "
        f"{len(TOWNS)} hard-hit towns and {N_ORIGINS} population-weighted origins between 200 m and 2 km from roads",
        "the radar saw flooded (the people who actually had to move) to the best reachable shelter.",
        "",
        "On the days Sentinel-1 observed the flood, every route was checked against the radar flood map:",
        "",
        "| Date | Routes | Safest: share of length on flooded roads | Fastest: share | Safest routes touching flood "
        "| Fastest routes touching flood | Safest mean ETA (min) | Fastest mean ETA (min) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in s["comparisons"]:
        sa, fa = c["safest"], c["fastest"]
        lines.append(f"| {c['date']} | {sa['routes']} | {100 * sa['flooded_share_of_length']:.2f}% | "
                     f"{100 * fa['flooded_share_of_length']:.2f}% | {sa['routes_touching_flood']} | "
                     f"{fa['routes_touching_flood']} | {sa['mean_eta_min']:.1f} | {fa['mean_eta_min']:.1f} |")
    comps = s["comparisons"]
    if comps:
        def total(kind: str, key: str) -> float:
            return sum(c[kind][key] for c in comps)

        n = int(total("safest", "routes"))
        sw, fw = total("safest", "flooded_m_total"), total("fastest", "flooded_m_total")
        if abs(sw - fw) < 1:
            verdict = ("At the balanced preset the held-out model did **not** move evacuation routes away from the roads "
                       "the radar saw flooded: most evacuations reach a nearby camp within a few minutes, and the model "
                       "gave many of the flooded roads probabilities below the 20% block threshold (see the operating "
                       "points in the model card). This is the system's measured limit for an event more extreme than "
                       "anything in its training data; use the cautious preset during extreme events.")
        elif sw < fw:
            verdict = (f"Safest routes ran **{100 * (1 - sw / max(fw, 1)):.0f}% less distance** on radar-flooded roads "
                       "than the fastest routes.")
        else:
            verdict = "Safest routes did not reduce exposure to radar-flooded roads on these days."
        lines += ["", f"**Result.** {n} radar-checked safest routes ran {sw:,.0f} m on flooded roads in total, "
                      f"against {fw:,.0f} m for the fastest routes. {verdict}"]
    lines += [
        "",
        "## Daily risk picture",
        "",
        "| Date | Roads at risk (km) | Roads blocked (km) | Upstream 3-day rain (mm) | Max gauge vs danger (m) |",
        "|---|---|---|---|---|",
    ]
    for d in s["days"]:
        g = "n/a" if d["gauge_max_rel"] is None else f"{d['gauge_max_rel']:+.2f}"
        lines.append(f"| {d['date']} | {d['roads_at_risk_km']:.1f} | {d['roads_blocked_km']:.1f} | "
                     f"{d['rain_up_3d']:.0f} | {g} |")
    lines += [
        "",
        "## Reading this honestly",
        "",
        "* Sentinel-1 passed over Ernakulam only on a few days (no pass at the 15–17 August peak), so the radar",
        "  check covers those days only, and radar misses water under tree canopy and between buildings.",
        "* Routes are vehicle routes on the OpenStreetMap drive network to OSM-derived candidate shelters; real",
        "  camps and capacities from the District Disaster Management Authority should replace them.",
        "* Official KSDMA evacuation orders always take priority over this tool.",
    ]
    path = cfg.paths.docs / "replay_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
