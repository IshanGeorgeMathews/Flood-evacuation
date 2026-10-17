# API reference

Base URL: `http://<host>:8000`. All responses are JSON (GeoJSON where noted). Coordinates are WGS84
(`EPSG:4326`), GeoJSON order `[lon, lat]`. Invalid input returns `400 {"error": "..."}`.

Common query parameters:

| Parameter | Values | Default | Meaning |
|---|---|---|---|
| `preset` | `cautious`, `balanced`, `fast` | `balanced` | Routing caution level (α, τ in `configs/routing.yaml`) |
| `scenario` | 0–400 | 0 | What-if: extra rainfall (mm) over 3 days added to the picture |
| `date` | `YYYY-MM-DD`, 2017-01-08 to 2024-12-31 | live | Simulate a historical day: that day's real IMD rainfall and CWC levels drive everything (risk, route, shelters, stats, gauges, rainfall, explain, isochrone, taluks, simulate) |
| `colour` | `probability`, `rank` | `probability` | `/api/risk` and `/api/replay/<date>` only: colour classes by calibrated probability or by the day's relative ranking (top 5% / 2% / 0.5%) |

## Endpoints

| Method and path | Returns |
|---|---|
| `GET /api/status` | `sim_days` (preset historical days) and `sim_range`; feed list (`name, source, state ∈ ok/provisional/stale/down, last_ok, age_s, data_date`), `model_version`, prediction `mode` (`full` or `static-fallback`), `live_date`, `refreshed_at`, `refresh_minutes`, routing `presets` |
| `GET /api/risk?bbox=lon0,lat0,lon1,lat1&zoom=&scenario=` | GeoJSON roads with `eid`, `p` (calibrated flood probability), `c` (class 0–3: low, watch, high, severe), `b` (bridge/causeway), `r` (road-class rank). Low zooms return the major and risky roads only (max 30 000 features) |
| `GET /api/route?lat=&lon=&preset=&scenario=` | `routes[]` with `kind ∈ safest / alternative / fastest`, `geometry` (LineString), `eta_s`, `dist_m`, `exposure_m` (metres on roads at or above the at-risk probability, 20%), `max_p`, `mean_p`, `shelter`, `blocked_avoided`; `warnings[]`; `data_ts` |
| `GET /api/shelters?preset=&scenario=` | GeoJSON shelters: `id, name, kind, capacity, capacity_source, demand` (projected), `open` (not cut off by flood risk), `p_flood`, `verified`, `facilities` |
| `GET /api/gauges` | CWC gauges with `level, warning, danger, hfl, status, trend_3h` and a 72-hour `series` |
| `POST /api/simulate` body `{"rain_mm_3d": 100, "preset": "balanced"}` | `kpis`, `baseline` (live), `delta`, `segments_newly_at_risk` |
| `GET /api/explain/<eid>?scenario=` | Probability of the riskiest segment of road `eid`, its top SHAP contributions and key input values |
| `GET /api/isochrone?lat=&lon=&minutes=15&preset=` | GeoJSON polygon reachable within N minutes on roads below the block threshold |
| `GET /api/replay` | August 2018 replay summary: per-day statistics and the radar comparison of safest vs fastest routes |
| `GET /api/replay/<YYYY-MM-DD>?bbox=&zoom=` | That day's predicted road risk (held-out model) and, on Sentinel-1 days, the observed flooded roads |
| `GET /api/stats?preset=&scenario=` | KPIs, km of road per probability bin, top-10 risky named roads, at-risk km by road class |
| `GET /api/model` | Full `metrics.json` of the current model |
| `GET /api/rainfall` | Last 10 days district-mean rainfall, 3-day forecast, upstream 3-day total, sources |
| `GET /api/dams` | Upstream dam release events (hand-compiled reference table, with confidence) |
| `GET /api/alerts?preset=` | Generated alerts: gauges above warning/danger, blocked road length, feed problems |
| `GET /api/responder/taluks?preset=&scenario=` | GeoJSON taluks with residents along at-risk roads, km at risk, shelters, capacity and demand |
| `GET /api/export/routes?preset=&format=geojson|csv` | Safest routes from taluk centres and the hardest-hit 2018 towns (download) |
| `GET /api/stream` | Server-sent events: `refresh` (with `newly_blocked` edge count) after every refresh cycle |

## Example

```bash
curl "http://localhost:8000/api/route?lat=10.1076&lon=76.3525&preset=cautious"
```

The response always carries the timestamp of the data used (`data_ts`) and the risk date (`date`).
