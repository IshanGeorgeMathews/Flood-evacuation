# Data dictionary

All tables live in `data/processed/` (GeoParquet / Parquet, WGS84). The unit of analysis is the **road
segment**: OpenStreetMap drive-network edges split into ~100 m pieces, one physical copy per two-way road.

## segments.parquet — one row per segment

| Column | Type | Description | Source |
|---|---|---|---|
| `seg_id` | str | Stable id `{u}_{v}_{key}_{i}` (OSM edge + piece index) | OSM |
| `u`, `v`, `key` | int | OSM edge endpoints and key | OSM |
| `ekey` | str | Direction-free edge key shared by both directions of a road | derived |
| `highway`, `name` | str | OSM road class and name | OSM |
| `is_bridge`, `is_causeway` | 0/1 | Bridge; causeway, embankment or bund | OSM tags |
| `road_class_rank` | int | 1 motorway … 8 service | derived |
| `seg_len_m` | float | Segment length (m) | derived |
| `elev` | float | Mean elevation (m) along the segment | Copernicus GLO-30 |
| `hand` | float | Minimum height above nearest drainage (m) | pysheds on GLO-30 |
| `slope` | float | Mean slope (°) | GLO-30 |
| `twi` | float | Max topographic wetness index | GLO-30 |
| `dist_stream_m` | float | Minimum distance to a mapped stream (m) | GLO-30 drainage network |
| `stream_order` | float | Max Strahler order touched | GLO-30 drainage network |
| `flow_acc_log` | float | log(1 + upslope cells), max | GLO-30 |
| `landcover_water/built/tree/crop` | float | Share of sample points in each ESA WorldCover class | ESA WorldCover 2021 |
| `pop_density` | float | People in the 100 m cell at the segment midpoint | WorldPop 2020 |
| `cell_id` | int | Nearest IMD 0.25° rainfall cell | IMD |
| `station`, `dist_gauge_km` | str, float | Nearest CWC gauge and distance | CWC |
| `lon`, `lat` | float | Segment midpoint | derived |

## labels.parquet — one row per (segment, Sentinel-1 date) where the segment was observed

| Column | Description |
|---|---|
| `seg_id`, `date` | Keys |
| `flood_frac` | Share of the segment's 20 m sample points inside SAR flood pixels |
| `label` | 1 if `flood_frac ≥ 0.30` (configurable in `configs/model.yaml`) |

## Dynamic tables

| File | Keys | Columns |
|---|---|---|
| `rain_grid.parquet` | date, lat, lon | `rain_mm`, `source` (IMD gridded daily rainfall) |
| `rain_cells.parquet` | cell_id | IMD cell centres |
| `rain_cell.parquet` | cell_id, date | `rain_1d, rain_3d, rain_5d, rain_7d` (trailing sums, mm) |
| `rain_up.parquet` | date | `rain_up_3d, rain_up_5d`: mean over the upstream catchment box |
| `gauges.parquet` | station | CWC metadata: name, river, lat/lon, warning, danger, HFL, chosen level series |
| `gauge_daily.parquet` | station, date | Daily max water level (m) |
| `gauge_rel.parquet` | station, date | `rel` = level − danger level, `rel_3d` = 3-day running max |
| `gauge_live.parquet` | station, time | Last 7 days of hourly readings |
| `sar_events.parquet` | date | Sentinel-1 dates used, orbit, screening flood fraction and coverage |

## Routing and other layers

| File | Description |
|---|---|
| `edges.parquet` | Directed drive edges with travel time `t_s`, speed, length, road attributes and `ekey` |
| `nodes.parquet` | Graph junctions (OSM node id, lon, lat) |
| `shelters_base.parquet` | Candidate shelters (OSM schools, colleges, halls — via Overpass or the Geofabrik extract) with estimated capacity, `verified = False` |
| `taluks.parquet` | Taluk polygons: OSM admin level 6 when Overpass is reachable, otherwise GADM 4.1 level 3 (names mapped to current official taluk names; GADM licence is non-commercial — re-fetch from OSM or obtain permission for paid use) |
| `boundary.parquet` | Ernakulam district boundary |
| `replay/` | August 2018 replay: `summary.json` and one layer file per day |

## Reference data (tracked in git)

| File | Description |
|---|---|
| `data/reference/dams.csv` | Upstream dam release events from widely reported news coverage — **not yet verified against official KSEB/KSDMA notices**; each row carries a confidence flag |
