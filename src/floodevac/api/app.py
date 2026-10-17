"""Flask application factory.

    flask --app floodevac.api.app run            # development
    python -m floodevac.api.app                  # production server (waitress) on :8000
"""

from __future__ import annotations

import os
import threading

from flask import Flask

from floodevac.common.config import ROOT, load
from floodevac.common.logging import get_logger

log = get_logger(__name__)


def _artefacts_ready(cfg) -> bool:
    P = cfg.paths.processed
    return (cfg.paths.models / "CURRENT").exists() and (P / "segments.parquet").exists() and \
        (P / "edges.parquet").exists()


def create_app(service=None, start_scheduler: bool | None = None) -> Flask:
    cfg = load()
    app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"), static_folder=str(ROOT / "web" / "static"),
                static_url_path="/static")
    app.config.update(MAP_CENTER=cfg.area["map_center"], MAP_ZOOM=cfg.area["map_zoom"],
                      DEFAULT_PRESET=cfg.routing["default_preset"], RISK_CLASSES=cfg.routing["risk_classes"],
                      RISKY_P=cfg.routing["risky_p"], JSON_SORT_KEYS=False)

    if service is None:
        if _artefacts_ready(cfg) and os.environ.get("FLOODEVAC_FIXTURES") != "1":
            from floodevac.api.services import LiveService

            service = LiveService(cfg)
        else:
            from floodevac.api.services import FixtureService

            log.warning("pipeline artefacts not found — serving recorded fixtures (MOCK DATA)")
            service = FixtureService(cfg.paths.fixtures)
    app.extensions["floodevac"] = service

    from floodevac.api.routes import api, pages

    app.register_blueprint(api)
    app.register_blueprint(pages)

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")  # map tile servers require a Referer
        if resp.mimetype == "application/json":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    if start_scheduler is None:
        start_scheduler = not service.mock
    if start_scheduler:
        _start_scheduler(service, cfg.refresh["interval_minutes"])
    return app


def _start_scheduler(service, minutes: int) -> None:
    from apscheduler.schedulers.background import BackgroundScheduler

    def safe_refresh():
        try:
            service.refresh()
        except Exception:  # noqa: BLE001 - keep serving the last good picture
            log.exception("refresh failed; keeping the previous risk picture")

    threading.Thread(target=safe_refresh, daemon=True).start()
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(safe_refresh, "interval", minutes=minutes, id="refresh", max_instances=1, coalesce=True)
    sched.start()
    log.info("refresh scheduled every %d minutes", minutes)


def main() -> None:
    from waitress import serve

    port = int(os.environ.get("PORT", "8000"))
    app = create_app()
    log.info("serving on http://0.0.0.0:%d", port)
    serve(app, host="0.0.0.0", port=port, threads=32, channel_timeout=120)


if __name__ == "__main__":
    main()
