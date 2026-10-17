"""Snap every source onto the road segment and build the model tables.

Outputs (data/processed/)
  segments.parquet      one row per ~100 m segment: geometry, road attributes, static features, IMD cell, gauge
  labels.parquet        (seg_id, date, flood_frac, label) for every Sentinel-1 date where the segment was observed
  rain_cell.parquet     (cell_id, date, rain_1d..rain_7d)
  rain_cells.parquet    IMD cell centres
  rain_up.parquet       (date, rain_up_3d, rain_up_5d)
  gauge_rel.parquet     (station, date, rel, rel_3d)

`assemble()` joins these into a feature matrix for any set of (segment, date) pairs; training, live prediction,
what-if scenarios and the 2018 replay all use it, so features are computed one way everywhere.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import Config
from floodevac.common.io import read_table, write_gdf, write_table
from floodevac.common.logging import get_logger
from floodevac.features import hydro, rainfall, terrain

log = get_logger(__name__)


def _p(cfg: Config, name: str) -> Path:
    return cfg.paths.processed / name


def build(cfg: Config) -> Path:
    out = _p(cfg, "segments.parquet")
    if out.exists() and not cfg.force:
        return out
    from floodevac.ingest import dem, osm

    crs = cfg.area["metric_crs"]
    seg = gpd.read_parquet(osm.build_segments(cfg))
    seg_m = seg.to_crs(crs)
    log.info("sampling %d segments…", len(seg))
    pts = terrain.sample_points(seg_m, cfg.model["label"]["sample_spacing_m"])

    feats = terrain.terrain_features(seg_m, pts, dem.derive_terrain(cfg), crs)
    feats = feats.join(terrain.landcover_features(seg_m, pts, cfg.paths.raw / "landcover_worldcover.tif", crs))
    # WorldPop people per 100 m cell -> people per hectare
    feats["pop_density"] = terrain.population(seg_m, cfg.paths.raw / "worldpop_2020.tif", crs)

    mid = seg_m.geometry.interpolate(0.5, normalized=True).to_crs(4326)
    lon, lat = mid.x.to_numpy(), mid.y.to_numpy()

    rain = read_table(_p(cfg, "rain_grid.parquet"))
    cell_tab = rainfall.cells(rain)
    feats["cell_id"] = rainfall.nearest_cell(lon, lat, cell_tab)
    meta = read_table(_p(cfg, "gauges.parquet"))
    feats["station"], feats["dist_gauge_km"] = hydro.nearest_station(lon, lat, meta)

    seg = pd.concat([seg.reset_index(drop=True), feats], axis=1)
    seg["lon"], seg["lat"] = lon, lat
    write_gdf(seg, out)
    log.info("static features saved")

    # dynamic tables
    write_table(cell_tab, _p(cfg, "rain_cells.parquet"))
    write_table(rainfall.accumulations(rain, cell_tab), _p(cfg, "rain_cell.parquet"))
    write_table(rainfall.upstream(rain, cell_tab, cfg.area["upstream_bbox"]), _p(cfg, "rain_up.parquet"))
    gd = read_table(_p(cfg, "gauge_daily.parquet"))
    write_table(hydro.relative_levels(gd, meta), _p(cfg, "gauge_rel.parquet"))

    # labels
    events = read_table(_p(cfg, "sar_events.parquet"))
    thr = cfg.model["label"]["flooded_fraction"]
    frames = []
    for rec in events.itertuples():
        frac = terrain.flood_fraction(pts, len(seg), cfg.paths.raw / "sar" / rec.path, crs)
        ok = np.isfinite(frac)
        frames.append(pd.DataFrame({"seg_id": seg["seg_id"].to_numpy()[ok], "date": pd.Timestamp(rec.date),
                                    "flood_frac": frac[ok].astype("float32"),
                                    "label": (frac[ok] >= thr).astype("int8")}))
        log.info("labels %s: %d observed, %.2f%% flooded", rec.date, ok.sum(), 100 * frames[-1]["label"].mean())
    write_table(pd.concat(frames, ignore_index=True), _p(cfg, "labels.parquet"))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Feature assembly


class FeatureStore:
    """In-memory copy of the static and dynamic tables used to assemble feature matrices."""

    def __init__(self, cfg: Config, seg: pd.DataFrame | None = None):
        self.cfg = cfg
        self.static_cols = cfg.model["features"]["static"]
        self.dynamic_cols = cfg.model["features"]["dynamic"]
        self.seg = seg if seg is not None else pd.read_parquet(_p(cfg, "segments.parquet"),
                                                               columns=["seg_id", "cell_id", "station",
                                                                        *self.static_cols])
        self.rain_cell = read_table(_p(cfg, "rain_cell.parquet"))
        self.rain_up = read_table(_p(cfg, "rain_up.parquet"))
        self.gauge_rel = read_table(_p(cfg, "gauge_rel.parquet"))
        self.labels = read_table(_p(cfg, "labels.parquet")) if _p(cfg, "labels.parquet").exists() else None
        self._freq_cache: dict = {}

    def add_live(self, rain_cell: pd.DataFrame | None = None, rain_up: pd.DataFrame | None = None,
                 gauge_rel: pd.DataFrame | None = None) -> None:
        """Append live rows (they replace historic rows for the same keys)."""
        if rain_cell is not None and len(rain_cell):
            self.rain_cell = pd.concat([self.rain_cell, rain_cell]).drop_duplicates(["cell_id", "date"], keep="last")
        if rain_up is not None and len(rain_up):
            self.rain_up = pd.concat([self.rain_up, rain_up]).drop_duplicates(["date"], keep="last")
        if gauge_rel is not None and len(gauge_rel):
            self.gauge_rel = pd.concat([self.gauge_rel, gauge_rel]).drop_duplicates(["station", "date"], keep="last")

    def past_flood_freq(self, dates: pd.Series, seg_ids: pd.Series, exclude: set[pd.Timestamp] | None = None
                        ) -> np.ndarray:
        """Share of earlier observed Sentinel-1 dates on which the segment was flooded (shrunk towards 0).
        Only dates strictly before the prediction date count; `exclude` removes held-out events entirely."""
        if self.labels is None:
            return np.zeros(len(dates), dtype="float32")
        lab = self.labels
        if exclude:
            lab = lab[~lab["date"].isin(exclude)]
        label_dates = np.sort(lab["date"].unique())
        out = np.zeros(len(dates), dtype="float32")
        frame = pd.DataFrame({"seg_id": seg_ids.to_numpy(), "date": dates.to_numpy(), "i": np.arange(len(dates))})
        for d, g in frame.groupby("date"):
            prior_dates = label_dates[label_dates < np.datetime64(d)]
            if not len(prior_dates):
                continue
            # the frequency only changes when a new labelled date becomes "prior": memoise on that
            key = (prior_dates[-1], frozenset(exclude or ()))
            freq = self._freq_cache.get(key)
            if freq is None:
                agg = lab[lab["date"] <= prior_dates[-1]].groupby("seg_id")["label"].agg(["sum", "count"])
                freq = (agg["sum"] / (agg["count"] + 1)).astype("float32")
                self._freq_cache[key] = freq
            out[g["i"].to_numpy()] = freq.reindex(g["seg_id"]).fillna(0).to_numpy()
        return out

    def assemble(self, pairs: pd.DataFrame, exclude: set[pd.Timestamp] | None = None,
                 rain_offset_mm: float = 0.0) -> pd.DataFrame:
        """Feature matrix for (seg_id, date) pairs. `rain_offset_mm` adds a what-if 3-day rainfall amount,
        spread evenly over three days so the 1/5/7-day windows stay consistent."""
        df = pairs[["seg_id", "date"]].merge(self.seg, on="seg_id", how="left")
        df = df.merge(self.rain_cell, on=["cell_id", "date"], how="left")
        df = df.merge(self.rain_up, on="date", how="left")
        g = self.gauge_rel.rename(columns={"rel": "gauge_near_rel", "rel_3d": "gauge_near_rel_3d"})
        df = df.merge(g, on=["station", "date"], how="left")
        df = df.merge(hydro.district_max(self.gauge_rel), on="date", how="left")
        if rain_offset_mm:
            per_day = rain_offset_mm / 3.0
            for col, days in (("rain_1d", 1), ("rain_3d", 3), ("rain_5d", 3), ("rain_7d", 3),
                              ("rain_up_3d", 3), ("rain_up_5d", 3)):
                df[col] = df[col].fillna(0) + per_day * days
        year_onset = pd.to_datetime(df["date"].dt.year.astype(str) + "-06-01")
        df["days_since_onset"] = (df["date"] - year_onset).dt.days.clip(-60, 240)
        df["past_flood_freq"] = self.past_flood_freq(df["date"], df["seg_id"], exclude)
        return df
