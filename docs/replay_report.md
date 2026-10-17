# August 2018 replay: safest vs fastest routes

The **held-out model** (trained without any August 2018 data) scored the Ernakulam road network day by
day from 6 to 27 August 2018, using that day's IMD rainfall and CWC river levels. On each day the
router recomputed evacuation routes from 6 hard-hit towns and 300 population-weighted origins between 200 m and 2 km from roads
the radar saw flooded (the people who actually had to move) to the best reachable shelter.

On the days Sentinel-1 observed the flood, every route was checked against the radar flood map:

| Date | Routes | Safest: share of length on flooded roads | Fastest: share | Safest routes touching flood | Fastest routes touching flood | Safest mean ETA (min) | Fastest mean ETA (min) |
|---|---|---|---|---|---|---|---|
| 2018-08-09 | 300 | 0.00% | 0.00% | 0 | 0 | 2.3 | 2.3 |
| 2018-08-21 | 300 | 0.59% | 0.59% | 5 | 5 | 2.3 | 2.3 |
| 2018-08-27 | 300 | 0.00% | 0.00% | 0 | 0 | 2.3 | 2.3 |

**Result.** 900 radar-checked safest routes ran 2,656 m on flooded roads in total, against 2,656 m for the fastest routes. At the balanced preset the held-out model did **not** move evacuation routes away from the roads the radar saw flooded: most evacuations reach a nearby camp within a few minutes, and the model gave many of the flooded roads probabilities below the 20% block threshold (see the operating points in the model card). This is the system's measured limit for an event more extreme than anything in its training data; use the cautious preset during extreme events.

## Daily risk picture

| Date | Roads at risk (km) | Roads blocked (km) | Upstream 3-day rain (mm) | Max gauge vs danger (m) |
|---|---|---|---|---|
| 2018-08-06 | 0.0 | 0.1 | 7 | -3.94 |
| 2018-08-07 | 0.0 | 0.1 | 17 | -3.84 |
| 2018-08-08 | 0.1 | 0.2 | 65 | -1.83 |
| 2018-08-09 | 0.7 | 0.9 | 170 | -1.35 |
| 2018-08-10 | 1.4 | 1.5 | 199 | -1.87 |
| 2018-08-11 | 1.0 | 1.5 | 181 | -2.61 |
| 2018-08-12 | 0.6 | 0.9 | 89 | -3.06 |
| 2018-08-13 | 0.7 | 0.9 | 91 | -2.81 |
| 2018-08-14 | 0.9 | 1.2 | 115 | -1.17 |
| 2018-08-15 | 3.0 | 3.2 | 215 | +2.03 |
| 2018-08-16 | 17.4 | 18.0 | 330 | +3.83 |
| 2018-08-17 | 16.2 | 17.5 | 357 | +2.85 |
| 2018-08-18 | 33.2 | 35.1 | 289 | +1.42 |
| 2018-08-19 | 17.2 | 19.2 | 161 | +0.00 |
| 2018-08-20 | 8.0 | 8.6 | 96 | -1.49 |
| 2018-08-21 | 4.8 | 5.0 | 59 | -2.95 |
| 2018-08-22 | 2.0 | 2.2 | 33 | -3.50 |
| 2018-08-23 | 0.2 | 0.2 | 15 | -3.71 |
| 2018-08-24 | 0.1 | 0.2 | 6 | -3.84 |
| 2018-08-25 | 0.1 | 0.1 | 4 | -3.95 |
| 2018-08-26 | 0.1 | 0.1 | 2 | -4.05 |
| 2018-08-27 | 0.1 | 0.1 | 4 | -4.04 |

## Reading this honestly

* Sentinel-1 passed over Ernakulam only on a few days (no pass at the 15–17 August peak), so the radar
  check covers those days only, and radar misses water under tree canopy and between buildings.
* Routes are vehicle routes on the OpenStreetMap drive network to OSM-derived candidate shelters; real
  camps and capacities from the District Disaster Management Authority should replace them.
* Official KSDMA evacuation orders always take priority over this tool.
