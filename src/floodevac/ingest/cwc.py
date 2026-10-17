"""Central Water Commission river gauges (ffs.india-water.gov.in).

The public flood-forecasting portal is backed by an undocumented JSON API (`/iam/api/...`, Spring "specification"
queries with a `class-name` header). It serves hourly water levels for Kerala stations back to 2018 and live
values today. Two level series exist per station (`HHS`, `HZS`) with a station-specific datum offset; the one whose
peak matches the station's published highest flood level (HFL) is the one on the warning/danger scale.

Outputs
  data/processed/gauges.parquet         station metadata (warning, danger, HFL, lat/lon, chosen series)
  data/processed/gauge_daily.parquet    daily max level per station (historic windows)
  data/processed/gauge_live.parquet     last 7 days of hourly levels (refreshed by the live job)
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import requests

from floodevac.common.config import Config
from floodevac.common.io import write_table
from floodevac.common.logging import get_logger

log = get_logger(__name__)

BASE = "https://ffs.india-water.gov.in/iam/api"
# Ernakulam-area gauges (Kochi division): Periyar, Muvattupuzha and Chalakudy rivers
STATIONS = {
    "012-SWRDKOCHI": {"name": "Neeleeswaram", "river": "Periyar"},
    "013-SWRDKOCHI": {"name": "Kalampur", "river": "Muvattupuzha"},
    "014-SWRDKOCHI": {"name": "Ramamangalam", "river": "Muvattupuzha"},
    "011-SWRDKOCHI": {"name": "Arangali", "river": "Chalakudy"},
}
LEVEL_TYPES = ("HHS", "HZS")


def _expr(field: str, op: str, value: str) -> dict:
    return {"expression": {"valueIsRelationField": False, "fieldName": field, "operator": op, "value": value}}


def _and(*parts: dict) -> dict:
    spec = parts[0]
    for p in parts[1:]:
        spec = {"where": spec, "and": p}
    return spec if "where" in spec else {"where": spec}


def _get(path: str, class_name: str, spec: dict | None = None, timeout: int = 120, **params) -> list[dict]:
    if spec is not None:
        params["specification"] = json.dumps(spec)
    r = requests.get(f"{BASE}/{path}", params=params, headers={"class-name": class_name}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_station_meta() -> pd.DataFrame:
    rows = []
    for code, info in STATIONS.items():
        geo = _get("layer-station-geo/specification/", "LayerStationGeoDto", _and(_expr("stationCode", "eq", code)))
        stat = _get("flood-forecast-static/specification/", "FloodForecastStaticDto",
                    _and(_expr("stationCode", "eq", code)))
        g = geo[0] if geo else {}
        s = stat[0] if stat else {}
        rows.append({"station": code, **info, "lat": g.get("lat"), "lon": g.get("lon"),
                     "warning": s.get("warningLevel"), "danger": s.get("dangerLevel"),
                     "hfl": s.get("highestFlowLevel"), "hfl_date": s.get("highestFlowLevelDate")})
    return pd.DataFrame(rows)


def fetch_series(code: str, start: str, end: str, dtypes: tuple[str, ...] = LEVEL_TYPES,
                 timeout: int = 120) -> pd.DataFrame:
    """Hourly level readings between start and end (ISO timestamps, exclusive)."""
    frames = []
    for dtype in dtypes:
        spec = _and(_expr("id.stationCode", "eq", code), _expr("id.datatypeCode", "eq", dtype),
                    _expr("id.dataTime", "gt", start), _expr("id.dataTime", "lt", end))
        data = _get("new-entry-data/specification/", "NewEntryDataDto", spec, timeout=timeout)
        if data:
            frames.append(pd.DataFrame({"station": code, "dtype": dtype,
                                        "time": pd.to_datetime([d["id"]["dataTime"] for d in data]),
                                        "level": [d["dataValue"] for d in data]}))
    if not frames:
        return pd.DataFrame(columns=["station", "dtype", "time", "level"])
    return pd.concat(frames).dropna(subset=["level"])


def choose_series(meta: pd.DataFrame) -> pd.DataFrame:
    """Pick, per station, the series whose peak around the HFL date best matches the published HFL."""
    chosen = []
    for rec in meta.itertuples():
        best = "HHS"
        if rec.hfl and rec.hfl_date:
            d = pd.Timestamp(rec.hfl_date)
            s = fetch_series(rec.station, (d - pd.Timedelta(days=2)).isoformat(), (d + pd.Timedelta(days=2)).isoformat())
            if not s.empty:
                peaks = s.groupby("dtype")["level"].max()
                best = (peaks - rec.hfl).abs().idxmin()
        chosen.append(best)
    meta = meta.copy()
    meta["series"] = chosen
    return meta


def fetch_meta(cfg: Config) -> Path:
    out = cfg.paths.processed / "gauges.parquet"
    if out.exists() and not cfg.force:
        return out
    meta = choose_series(fetch_station_meta())
    write_table(meta, out)
    log.info("gauge metadata: %s", meta[["name", "danger", "hfl", "series"]].to_dict("records"))
    return out


def _monthly_ranges(windows: list[list[str]]):
    for start, end in windows:
        months = pd.date_range(start, end, freq="MS")
        for m in months:
            yield m, min(m + pd.offsets.MonthBegin(1), pd.Timestamp(end) + pd.Timedelta(days=1))


def fetch_historic(cfg: Config) -> Path:
    """Daily max level for every monsoon window in configs/model.yaml (2018 onwards: portal history starts 2018)."""
    out = cfg.paths.processed / "gauge_daily.parquet"
    if out.exists() and not cfg.force:
        return out
    meta = pd.read_parquet(fetch_meta(cfg))
    windows = [w for w in cfg.model["sar"]["windows"] if int(w[0][:4]) >= 2018]
    frames = []
    for rec in meta.itertuples():
        for m0, m1 in _monthly_ranges(windows):
            try:
                s = fetch_series(rec.station, m0.isoformat(), m1.isoformat(), (rec.series,))
            except Exception as exc:  # noqa: BLE001 - gaps are expected; the model tolerates missing gauges
                log.warning("gauge %s %s failed: %s", rec.name, m0.date(), exc)
                continue
            if not s.empty:
                frames.append(s)
        log.info("gauge %s history fetched", rec.name)
    hourly = pd.concat(frames)
    daily = (hourly.assign(date=hourly["time"].dt.normalize()).groupby(["station", "date"])["level"].max()
             .reset_index())
    write_table(daily, out)
    log.info("gauge daily history: %d station-days", len(daily))
    return out


def fetch_live(cfg: Config, days: int = 7, timeout: int = 60) -> Path:
    """Recent hourly levels for the live dashboard (always re-fetched)."""
    out = cfg.paths.processed / "gauge_live.parquet"
    meta = pd.read_parquet(fetch_meta(cfg))
    now = dt.datetime.now()
    start = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (now + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    frames = [fetch_series(r.station, start, end, (r.series,), timeout=timeout) for r in meta.itertuples()]
    live = pd.concat(frames) if frames else pd.DataFrame()
    write_table(live, out)
    log.info("gauge live: %d readings", len(live))
    return out


def fetch(cfg: Config) -> Path:
    fetch_meta(cfg)
    fetch_historic(cfg)
    try:
        fetch_live(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("live gauge fetch failed: %s", exc)
    return cfg.paths.processed / "gauge_daily.parquet"
