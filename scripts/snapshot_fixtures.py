"""Record trimmed real API responses into tests/fixtures/ (used by the test-suite and the no-data fallback).

    python scripts/snapshot_fixtures.py

Requires the pipeline artefacts. Fixtures are snapshots of the real system, trimmed for size — never invented.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodevac.api.app import create_app  # noqa: E402
from floodevac.common.config import load  # noqa: E402

ALUVA = (10.1076, 76.3525)


def main() -> None:
    os.environ.pop("FLOODEVAC_FIXTURES", None)
    from floodevac.api.services import LiveService

    cfg = load()
    svc = LiveService(cfg)
    svc.refresh()
    app = create_app(service=svc, start_scheduler=False)
    c = app.test_client()
    out = cfg.paths.fixtures
    out.mkdir(parents=True, exist_ok=True)

    def get(path: str):
        r = c.get(path)
        assert r.status_code == 200, (path, r.data[:300])
        return r.get_json()

    lat, lon = ALUVA
    risk = get("/api/risk?bbox=76.30,10.05,76.42,10.16&zoom=14")
    risk["features"] = sorted(risk["features"], key=lambda f: -f["properties"]["p"])[:300]
    route = get(f"/api/route?lat={lat}&lon={lon}")
    replay_summary = get("/api/replay")
    day = replay_summary["comparisons"][0]["date"] if replay_summary["comparisons"] else replay_summary["days"][0]["date"]
    replay_day = get(f"/api/replay/{day}?bbox=76.15,10.05,76.45,10.25&zoom=13")
    replay_day["features"] = replay_day["features"][:300]
    replay_day["observed"]["features"] = replay_day["observed"]["features"][:300]
    shelters = get("/api/shelters")
    shelters["features"] = shelters["features"][:200]
    eid = risk["features"][0]["properties"]["eid"] if risk["features"] else 0
    sim = c.post("/api/simulate", json={"rain_mm_3d": 100}).get_json()
    fixtures = {
        "status": get("/api/status"), "risk": risk, "route": route, "shelters": shelters,
        "gauges": get("/api/gauges"), "simulate": sim, "explain": get(f"/api/explain/{eid}"),
        "isochrone": get(f"/api/isochrone?lat={lat}&lon={lon}"), "replay_summary": replay_summary,
        "replay_day": replay_day, "stats": get("/api/stats"), "model": get("/api/model"),
        "rainfall": get("/api/rainfall"), "dams": get("/api/dams"), "alerts": get("/api/alerts"),
        "taluks": get("/api/responder/taluks"),
    }
    for name, payload in fixtures.items():
        if isinstance(payload, dict):
            payload["_fixture_note"] = "Trimmed snapshot of a real API response, recorded by scripts/snapshot_fixtures.py"
        (out / f"{name}.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(fixtures)} fixtures to {out}")


if __name__ == "__main__":
    main()
