"""Live refresh: pull the latest rainfall and river levels, re-score every road segment, rebuild shelter trees.

Feeds (each is optional; the system degrades instead of failing):
  rainfall  IMD real-time 0.25° daily grids (provisional, ~1 day lag) -> fallback Open-Meteo daily precipitation
            at the same cell centres (model data, labelled as such) -> fallback static-only model
  gauges    CWC hourly levels for the Ernakulam gauges -> missing values are tolerated by the model
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
import requests

from floodevac.common.config import Config
from floodevac.common.io import read_table
from floodevac.common.logging import get_logger
from floodevac.features import hydro, rainfall

log = get_logger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


@dataclass
class Feed:
    name: str
    source: str = ""
    state: str = "down"            # ok | provisional | stale | down
    last_ok: str | None = None     # when we last fetched successfully (ISO)
    data_date: str | None = None   # date the newest data refers to
    detail: str = ""

    def as_dict(self) -> dict:
        age = None
        if self.last_ok:
            age = (dt.datetime.now() - dt.datetime.fromisoformat(self.last_ok)).total_seconds()
        return {"name": self.name, "source": self.source, "state": self.state, "last_ok": self.last_ok,
                "age_s": age, "data_date": self.data_date, "detail": self.detail}


@dataclass
class LiveData:
    rain_cell: pd.DataFrame | None = None
    rain_up: pd.DataFrame | None = None
    gauge_rel: pd.DataFrame | None = None
    gauge_hourly: pd.DataFrame | None = None
    forecast: pd.DataFrame | None = None
    rain_daily_mean: pd.DataFrame | None = None
    feeds: dict[str, Feed] = field(default_factory=dict)
    live_date: pd.Timestamp | None = None


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _rain_imd_realtime(cfg: Config, days: int = 9, deadline_s: int = 45) -> pd.DataFrame:
    """IMD real-time grids, abandoned after `deadline_s` (the IMD server can hang for minutes)."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutTimeout

    from floodevac.ingest import imd

    end = dt.date.today()
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(imd.fetch_realtime, cfg, end - dt.timedelta(days=days), end)
    try:
        return fut.result(timeout=deadline_s)
    except FutTimeout as exc:
        raise RuntimeError(f"IMD real-time did not answer within {deadline_s} s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _rain_open_meteo(cell_tab: pd.DataFrame, past_days: int = 9, timeout: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily precipitation at IMD cell centres: past days (observed-model blend) and next 3 days (forecast)."""
    lats = ",".join(f"{v:.3f}" for v in cell_tab["lat"])
    lons = ",".join(f"{v:.3f}" for v in cell_tab["lon"])
    r = requests.get(OPEN_METEO, params={"latitude": lats, "longitude": lons, "daily": "precipitation_sum",
                                         "past_days": past_days, "forecast_days": 3, "timezone": "Asia/Kolkata"},
                     timeout=timeout)
    r.raise_for_status()
    data = r.json()
    data = data if isinstance(data, list) else [data]
    rows = []
    for (lat, lon), d in zip(cell_tab[["lat", "lon"]].itertuples(index=False), data):
        for day, v in zip(d["daily"]["time"], d["daily"]["precipitation_sum"]):
            rows.append((pd.Timestamp(day), lat, lon, v))
    df = pd.DataFrame(rows, columns=["date", "lat", "lon", "rain_mm"]).dropna()
    today = pd.Timestamp(dt.date.today())
    return df[df["date"] <= today], df[df["date"] > today]


def collect(cfg: Config) -> LiveData:
    """Fetch every live feed with fallbacks; never raises."""
    P = cfg.paths.processed
    cell_tab = read_table(P / "rain_cells.parquet")
    live = LiveData(feeds={"rainfall": Feed("rainfall"), "gauges": Feed("gauges"), "forecast": Feed("forecast")})

    # ---- rainfall
    rain = None
    try:
        rain = _rain_imd_realtime(cfg)
        if rain.empty:
            raise RuntimeError("no IMD real-time grids returned")
        live.feeds["rainfall"] = Feed("rainfall", "IMD real-time gridded rainfall (provisional)", "provisional",
                                      _now(), str(rain["date"].max().date()))
    except Exception as exc:  # noqa: BLE001
        log.warning("IMD real-time unavailable: %s", exc)
    forecast = None
    try:
        past, forecast = _rain_open_meteo(cell_tab, timeout=cfg.refresh["http_timeout_s"])
        live.forecast = forecast
        live.feeds["forecast"] = Feed("forecast", "Open-Meteo 3-day precipitation forecast", "ok", _now(),
                                      str(forecast["date"].max().date()) if len(forecast) else None)
        if rain is None:
            rain = past
            live.feeds["rainfall"] = Feed("rainfall", "Open-Meteo daily precipitation (fallback, model data)",
                                          "provisional", _now(), str(past["date"].max().date()),
                                          "IMD real-time unavailable; using Open-Meteo at IMD cell centres")
    except Exception as exc:  # noqa: BLE001
        log.warning("Open-Meteo unavailable: %s", exc)
        live.feeds["forecast"].detail = str(exc)[:200]
    if rain is not None and len(rain):
        rain = rain.merge(cell_tab, on=["lat", "lon"], how="inner") if "cell_id" not in rain else rain
        rain = rain[["date", "lat", "lon", "rain_mm"]]
        live.rain_cell = rainfall.accumulations(rain, cell_tab)
        live.rain_up = rainfall.upstream(rain, cell_tab, cfg.area["upstream_bbox"]).dropna()
        live.rain_daily_mean = rain.groupby("date")["rain_mm"].mean().reset_index()
        live.live_date = pd.Timestamp(live.rain_cell["date"].max())
        age_days = (pd.Timestamp(dt.date.today()) - live.live_date).days
        if age_days > cfg.refresh["stale_after_s"]["rainfall"] / 86400:
            live.feeds["rainfall"].state = "stale"
    else:
        live.feeds["rainfall"].detail = "no rainfall feed available; static-only model in use"

    # ---- gauges
    try:
        from floodevac.ingest import cwc

        cwc.fetch_live(cfg, days=7, timeout=cfg.refresh["http_timeout_s"])
        hourly = read_table(P / "gauge_live.parquet")
        meta = read_table(P / "gauges.parquet")
        live.gauge_hourly = hourly
        if len(hourly):
            daily = (hourly.assign(date=hourly["time"].dt.normalize()).groupby(["station", "date"])["level"].max()
                     .reset_index())
            live.gauge_rel = hydro.relative_levels(daily, meta)
            newest = hourly["time"].max()
            age = (pd.Timestamp.now() - newest).total_seconds()
            state = "ok" if age < cfg.refresh["stale_after_s"]["gauges"] else "stale"
            live.feeds["gauges"] = Feed("gauges", "CWC flood-forecasting portal (hourly)", state, _now(),
                                        newest.isoformat(), f"{hourly['station'].nunique()} stations")
    except Exception as exc:  # noqa: BLE001
        log.warning("CWC live gauges unavailable: %s", exc)
        live.feeds["gauges"].detail = str(exc)[:200]

    if live.live_date is None:
        live.live_date = pd.Timestamp(dt.date.today())
    return live


def summarise_gauges(cfg: Config, hourly: pd.DataFrame | None, hours: int = 72) -> list[dict]:
    meta = read_table(cfg.paths.processed / "gauges.parquet")
    out = []
    for m in meta.itertuples():
        s = pd.DataFrame(columns=["time", "level"]) if hourly is None else hourly[hourly["station"] == m.station]
        s = s.sort_values("time")
        if len(s):
            s = s[s["time"] >= s["time"].max() - pd.Timedelta(hours=hours)]
        level = float(s["level"].iloc[-1]) if len(s) else None
        status = "no data"
        if level is not None:
            status = "above danger" if level >= m.danger else "above warning" if level >= m.warning else "normal"
        trend = None
        if len(s) >= 4:
            trend = float(s["level"].iloc[-1] - s["level"].iloc[-4])
        out.append({"station": m.station, "name": m.name, "river": m.river, "lat": m.lat, "lon": m.lon,
                    "warning": m.warning, "danger": m.danger, "hfl": m.hfl, "hfl_date": m.hfl_date,
                    "level": level, "status": status, "trend_3h": trend,
                    "updated": None if not len(s) else s["time"].iloc[-1].isoformat(),
                    "series": [{"t": t.isoformat(), "v": float(v)} for t, v in zip(s["time"], s["level"])]})
    return out
