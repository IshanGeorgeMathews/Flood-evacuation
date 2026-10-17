"""HTTP endpoints (JSON / GeoJSON) and dashboard pages."""

from __future__ import annotations

import queue

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, stream_with_context

api = Blueprint("api", __name__, url_prefix="/api")
pages = Blueprint("pages", __name__)

MAX_SCENARIO_MM = 400.0


def svc():
    return current_app.extensions["floodevac"]


def _f(name: str, default=None, lo=None, hi=None) -> float | None:
    v = request.args.get(name, default)
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        abort(400, f"'{name}' must be a number")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        abort(400, f"'{name}' out of range")
    return x


def _preset() -> str:
    p = request.args.get("preset", current_app.config["DEFAULT_PRESET"])
    if p not in svc().presets:
        abort(400, f"unknown preset '{p}'")
    return p


def _scenario() -> float:
    return _f("scenario", 0, 0, MAX_SCENARIO_MM) or 0.0


def _sim_date() -> str | None:
    """Optional historical day to simulate (YYYY-MM-DD within the processed data range)."""
    from floodevac.api.services import SIM_RANGE

    d = request.args.get("date")
    if d is None and request.method == "POST":
        d = (request.get_json(silent=True) or {}).get("date")
    if not d:
        return None
    if len(d) != 10 or not d.replace("-", "").isdigit():
        abort(400, "date must be YYYY-MM-DD")
    if not SIM_RANGE[0] <= d <= SIM_RANGE[1]:
        abort(400, f"date must be between {SIM_RANGE[0]} and {SIM_RANGE[1]}")
    return d


def _rank() -> bool:
    return request.args.get("colour") == "rank"


def _bbox() -> list[float] | None:
    raw = request.args.get("bbox")
    if not raw:
        return None
    try:
        parts = [float(x) for x in raw.split(",")]
    except ValueError:
        abort(400, "bbox must be lon0,lat0,lon1,lat1")
    if len(parts) != 4:
        abort(400, "bbox must be lon0,lat0,lon1,lat1")
    return parts


# ------------------------------------------------------------------------------------------------- API

@api.get("/status")
def status():
    return jsonify(svc().status())


@api.get("/risk")
def risk():
    zoom = int(_f("zoom", 11, 0, 22))
    return jsonify(svc().risk(_bbox(), zoom, _scenario(), sim_date=_sim_date(), rank=_rank()))


@api.get("/route")
def route():
    lat, lon = _f("lat", lo=-90, hi=90), _f("lon", lo=-180, hi=180)
    if lat is None or lon is None:
        abort(400, "lat and lon are required")
    return jsonify(svc().route(lat, lon, _preset(), _scenario(), _sim_date()))


@api.get("/shelters")
def shelters():
    return jsonify(svc().shelters(_preset(), _scenario(), _sim_date()))


@api.get("/gauges")
def gauges():
    return jsonify(svc().gauges(_sim_date()))


@api.post("/simulate")
def simulate():
    body = request.get_json(silent=True) or {}
    try:
        mm = float(body.get("rain_mm_3d", 0))
    except (TypeError, ValueError):
        abort(400, "rain_mm_3d must be a number")
    if not 0 <= mm <= MAX_SCENARIO_MM:
        abort(400, "rain_mm_3d out of range")
    preset = body.get("preset", current_app.config["DEFAULT_PRESET"])
    if preset not in svc().presets:
        abort(400, f"unknown preset '{preset}'")
    return jsonify(svc().simulate(mm, preset, _sim_date()))


@api.get("/explain/<int:eid>")
def explain(eid: int):
    return jsonify(svc().explain(eid, _scenario(), _sim_date()))


@api.get("/isochrone")
def isochrone():
    lat, lon = _f("lat", lo=-90, hi=90), _f("lon", lo=-180, hi=180)
    if lat is None or lon is None:
        abort(400, "lat and lon are required")
    minutes = _f("minutes", 15, 1, 60)
    return jsonify(svc().isochrone(lat, lon, minutes, _preset(), _scenario(), _sim_date()))


@api.get("/replay")
def replay_summary():
    return jsonify(svc().replay_summary())


@api.get("/replay/<date>")
def replay_day(date: str):
    if len(date) != 10 or not date.replace("-", "").isdigit():
        abort(400, "date must be YYYY-MM-DD")
    zoom = int(_f("zoom", 11, 0, 22))
    try:
        return jsonify(svc().replay_day(date, _bbox(), zoom, rank=_rank()))
    except FileNotFoundError:
        abort(404, "no replay data for that date")


@api.get("/stats")
def stats():
    return jsonify(svc().stats(_preset(), _scenario(), _sim_date()))


@api.get("/model")
def model():
    return jsonify(svc().model())


@api.get("/rainfall")
def rainfall():
    return jsonify(svc().rainfall(_sim_date()))


@api.get("/dams")
def dams():
    return jsonify(svc().dams())


@api.get("/alerts")
def alerts():
    return jsonify(svc().alerts(_preset()))


@api.get("/responder/taluks")
def taluks():
    return jsonify(svc().taluks(_preset(), _scenario(), _sim_date()))


@api.get("/export/routes")
def export_routes():
    fmt = request.args.get("format", "geojson")
    if fmt not in ("geojson", "csv"):
        abort(400, "format must be geojson or csv")
    body, mime = svc().export_routes(_preset(), fmt)
    ext = "csv" if fmt == "csv" else "geojson"
    return Response(body, mimetype=mime,
                    headers={"Content-Disposition": f"attachment; filename=evacuation_routes.{ext}"})


@api.get("/stream")
def stream():
    bus = svc().bus
    q = bus.subscribe()

    @stream_with_context
    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    yield q.get(timeout=25)
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache",
                                                                  "X-Accel-Buffering": "no"})


@api.errorhandler(400)
@api.errorhandler(404)
def _err(e):
    return jsonify({"error": getattr(e, "description", str(e))}), e.code


# ------------------------------------------------------------------------------------------------- pages

def _page(template: str, page: str):
    cfg = current_app.config
    return render_template(template, page=page, mock=svc().mock, center=cfg["MAP_CENTER"], zoom=cfg["MAP_ZOOM"],
                           presets=svc().presets, default_preset=cfg["DEFAULT_PRESET"],
                           risk_classes=cfg["RISK_CLASSES"], risky_p=cfg["RISKY_P"])


@pages.get("/sw.js")
def service_worker():
    # served from the root so the worker's scope covers every page
    resp = current_app.send_static_file("sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@pages.get("/")
def console():
    return _page("console.html", "console")


@pages.get("/responder")
def responder():
    return _page("responder.html", "responder")


@pages.get("/model")
def model_lab():
    return _page("model.html", "model")
