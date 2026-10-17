"""Export the validation layers to a GeoPackage and write a QGIS project that opens them, styled.

    python -m floodevac.jobs.qgis_export

qgis/floodevac.gpkg layers
  roads_risk_live        live predicted flood probability per road (physical edge)
  roads_risk_2018_08_21  held-out model prediction on the Sentinel-1 day 21 Aug 2018
  roads_flooded_2018_08_21  roads the radar observed under water that day
  shelters, gauges, taluks, boundary
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import pandas as pd

from floodevac.common.config import load
from floodevac.common.io import read_json
from floodevac.common.logging import get_logger

log = get_logger(__name__)

RISK_RULES = [(0.0, 0.2, "#8a94a3", 0.3, "Low (< 20%)"), (0.2, 0.35, "#fab219", 0.6, "Watch (20-35%)"),
              (0.35, 0.5, "#ec835a", 0.9, "High (35-50%)"), (0.5, 1.01, "#d03b3b", 1.3, "Severe (>= 50%)")]


def _edges_layer(edges: gpd.GeoDataFrame, p_edge: np.ndarray) -> gpd.GeoDataFrame:
    g = edges[["eid", "ekey", "name", "highway", "is_bridge", "is_causeway", "geometry"]].copy()
    g["p"] = np.round(p_edge, 4)
    return g.sort_values("p", ascending=False).drop_duplicates("ekey")


def _graduated(layer: str, field: str) -> str:
    ranges = "".join(f'<range lower="{lo}" upper="{hi}" symbol="{i}" label="{escape(lbl)}" render="true"/>'
                     for i, (lo, hi, _c, _w, lbl) in enumerate(RISK_RULES))
    symbols = "".join(
        f'<symbol type="line" name="{i}" alpha="1"><layer class="SimpleLine">'
        f'<Option type="Map"><Option name="line_color" type="QString" value="{c}"/>'
        f'<Option name="line_width" type="QString" value="{w}"/><Option name="line_width_unit" type="QString" value="MM"/>'
        f'</Option></layer></symbol>' for i, (_lo, _hi, c, w, _l) in enumerate(RISK_RULES))
    return (f'<renderer-v2 type="graduatedSymbol" attr="{field}" graduatedMethod="GraduatedColor">'
            f"<ranges>{ranges}</ranges><symbols>{symbols}</symbols></renderer-v2>")


def _single(geom: str, color: str, size: float) -> str:
    cls = {"line": "SimpleLine", "point": "SimpleMarker", "fill": "SimpleFill"}[geom]
    key = {"line": "line_color", "point": "color", "fill": "outline_color"}[geom]
    extra = '<Option name="style" type="QString" value="no"/>' if geom == "fill" else ""
    size_key = {"line": "line_width", "point": "size", "fill": "outline_width"}[geom]
    return (f'<renderer-v2 type="singleSymbol"><symbols><symbol type="{geom}" name="0" alpha="1">'
            f'<layer class="{cls}"><Option type="Map"><Option name="{key}" type="QString" value="{color}"/>'
            f'<Option name="{size_key}" type="QString" value="{size}"/>{extra}</Option></layer>'
            f"</symbol></symbols></renderer-v2>")


def _layer_xml(gpkg: str, name: str, geom: str, renderer: str, idx: int) -> tuple[str, str]:
    lid = f"{name}_{idx:03d}"
    gtype = {"line": "Line", "point": "Point", "fill": "Polygon"}[geom]
    maplayer = (f'<maplayer type="vector" geometry="{gtype}"><id>{lid}</id>'
                f"<datasource>./{gpkg}|layername={name}</datasource><layername>{name}</layername>"
                f'<provider encoding="UTF-8">ogr</provider><srs><spatialrefsys><authid>EPSG:4326</authid></spatialrefsys></srs>'
                f"{renderer}</maplayer>")
    tree = f'<layer-tree-layer id="{lid}" name="{name}" source="./{gpkg}|layername={name}" providerKey="ogr" checked="Qt::Checked"/>'
    return maplayer, tree


def run() -> Path:
    from floodevac.api.services import LiveService

    cfg = load()
    out_dir = cfg.paths.root / "qgis"
    out_dir.mkdir(exist_ok=True)
    gpkg = out_dir / "floodevac.gpkg"
    gpkg.unlink(missing_ok=True)
    P = cfg.paths.processed

    svc = LiveService(cfg)
    svc.refresh()
    pic = svc.live_pic
    edges = gpd.read_parquet(P / "edges.parquet")
    layers: list[tuple[str, str, str]] = []

    _edges_layer(edges, pic.state.p_edge).to_file(gpkg, layer="roads_risk_live", driver="GPKG")
    layers.append(("roads_risk_live", "line", _graduated("roads_risk_live", "p")))

    replay = P / "replay"
    summary = read_json(replay / "summary.json") if (replay / "summary.json").exists() else {"comparisons": []}
    for c in summary["comparisons"]:
        day = read_json(replay / f"{c['date']}.json")
        p = np.zeros(len(edges))
        p[day["edges"]] = day["p"]
        tag = c["date"].replace("-", "_")
        _edges_layer(edges, p).to_file(gpkg, layer=f"roads_risk_{tag}", driver="GPKG")
        layers.append((f"roads_risk_{tag}", "line", _graduated(f"roads_risk_{tag}", "p")))
        if day.get("observed_edges"):
            obs = edges.iloc[day["observed_edges"]].drop_duplicates("ekey")[["eid", "name", "highway", "geometry"]]
            obs.to_file(gpkg, layer=f"roads_flooded_{tag}", driver="GPKG")
            layers.append((f"roads_flooded_{tag}", "line", _single("line", "#3987e5", 1.6)))

    sh = svc.shelters("balanced", 0)
    gpd.GeoDataFrame.from_features(sh["features"], crs="EPSG:4326").to_file(gpkg, layer="shelters", driver="GPKG")
    layers.append(("shelters", "point", _single("point", "#0ca30c", 2.2)))
    g = pd.read_parquet(P / "gauges.parquet")
    gpd.GeoDataFrame(g, geometry=gpd.points_from_xy(g["lon"], g["lat"]), crs="EPSG:4326").to_file(
        gpkg, layer="gauges", driver="GPKG")
    layers.append(("gauges", "point", _single("point", "#3987e5", 3.5)))
    for name in ("taluks", "boundary"):
        if (P / f"{name}.parquet").exists():
            gpd.read_parquet(P / f"{name}.parquet").to_file(gpkg, layer=name, driver="GPKG")
            layers.append((name, "fill", _single("fill", "#52514e", 0.4)))

    maplayers, tree = [], []
    for i, (name, geom, renderer) in enumerate(reversed(layers)):
        ml, tl = _layer_xml(gpkg.name, name, geom, renderer, i)
        maplayers.append(ml)
        tree.append(tl)
    qgs = (
        '<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n'
        '<qgis projectname="FloodEvac Ernakulam validation" version="3.34.0">'
        "<title>FloodEvac Ernakulam validation</title>"
        "<projectCrs><spatialrefsys><authid>EPSG:4326</authid></spatialrefsys></projectCrs>"
        f'<layer-tree-group>{"".join(tree)}</layer-tree-group>'
        f'<projectlayers>{"".join(maplayers)}</projectlayers>'
        "</qgis>")
    (out_dir / "floodevac.qgs").write_text(qgs, encoding="utf-8")
    log.info("QGIS project written with %d layers", len(layers))
    return out_dir / "floodevac.qgs"


if __name__ == "__main__":
    run()
