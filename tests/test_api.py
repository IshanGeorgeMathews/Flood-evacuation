"""API contract tests against the recorded fixtures (no data pipeline needed)."""

import pytest

from floodevac.api.app import create_app
from floodevac.api.schemas import validate
from floodevac.api.services import FixtureService
from floodevac.common.config import load


@pytest.fixture(scope="module")
def client():
    app = create_app(service=FixtureService(load().paths.fixtures), start_scheduler=False)
    app.testing = True
    return app.test_client()


@pytest.mark.parametrize("path,schema", [
    ("/api/status", "status"),
    ("/api/risk?bbox=76.2,9.9,76.5,10.2&zoom=13", "risk"),
    ("/api/route?lat=10.1076&lon=76.3525&preset=balanced", "route"),
    ("/api/shelters", "shelters"),
    ("/api/gauges", "gauges"),
    ("/api/explain/12", "explain"),
    ("/api/isochrone?lat=10.1&lon=76.35", "isochrone"),
    ("/api/replay", "replay_summary"),
    ("/api/replay/2018-08-16", "replay_day"),
    ("/api/stats", "stats"),
    ("/api/model", "model"),
    ("/api/rainfall", "rainfall"),
    ("/api/dams", "dams"),
    ("/api/alerts", "alerts"),
    ("/api/responder/taluks", "taluks"),
])
def test_endpoint_matches_schema(client, path, schema):
    r = client.get(path)
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert validate(schema, body) == []


def test_route_items_have_contract_fields(client):
    for item in client.get("/api/route?lat=10.1&lon=76.35").get_json()["routes"]:
        assert validate("route_item", item) == []


def test_simulate(client):
    r = client.post("/api/simulate", json={"rain_mm_3d": 100, "preset": "cautious"})
    assert r.status_code == 200
    assert validate("simulate", r.get_json()) == []


@pytest.mark.parametrize("path", [
    "/api/route?lat=abc&lon=76",
    "/api/route?lat=10.1",
    "/api/route?lat=10.1&lon=76.3&preset=reckless",
    "/api/risk?bbox=1,2,3",
    "/api/risk?scenario=9999",
    "/api/replay/2018-8-16",
    "/api/export/routes?format=xml",
    "/api/risk?date=1999-01-01",
    "/api/route?lat=10.1&lon=76.3&date=2018-8-16",
])
def test_bad_input_is_rejected(client, path):
    r = client.get(path)
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_simulate_rejects_out_of_range(client):
    assert client.post("/api/simulate", json={"rain_mm_3d": -5}).status_code == 400
    assert client.post("/api/simulate", json={"rain_mm_3d": "lots"}).status_code == 400


@pytest.mark.parametrize("page", ["/", "/responder", "/model"])
def test_pages_render_with_disclaimer_and_mock_chip(client, page):
    r = client.get(page)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Official evacuation orders" in html
    assert "MOCK DATA" in html


def test_export_csv(client):
    r = client.get("/api/export/routes?format=csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"


@pytest.mark.parametrize("path", ["/api/stats?date=2018-08-16", "/api/gauges?date=2018-08-16",
                                  "/api/risk?date=2018-08-16&colour=rank&zoom=12"])
def test_historical_simulation_day_is_accepted(client, path):
    assert client.get(path).status_code == 200
