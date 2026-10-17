# User guide

FloodEvac turns a flood alert into a specific instruction: the safest drivable route from where you are to a
reachable shelter, updated as rain and river levels change.

> Official evacuation orders from KSDMA and the District Administration always take priority.
> Emergency 112 · Disaster helpline 1077.

## Evacuation console (`/`)

**Get a route**
1. Tap your location on the map, press **Use my location**, pick a town, or type `lat, lon`.
2. The **safest route** is drawn in blue with a white casing and ends at the best reachable shelter. A dotted blue
   line is an alternative; the grey line is the plain fastest route, shown for comparison only.
3. **Safest vs fastest** compares minutes, distance, metres on risky roads (≥ 20% flood probability) and the worst
   stretch. Share the route on WhatsApp or SMS, or copy a link that reopens it.

**Caution level.** *Cautious* blocks roads at or above 10% flood probability (7% on bridges and causeways);
*Balanced* (default) at 20% (15%); *Fast* only at 40% (30%), for responders. Probabilities are calibrated against
satellite-observed flooding, where flooded roads are rare (under 0.2% of road segments even on the worst observed days, 21 Aug 2018 and
10 Aug 2019; about 0.02% across all 32 monsoon dates), so 20% is already
several hundred times the normal risk.

**Basemap.** Switch between **Satellite** (default, real imagery with road and place names), **Streets** and **Topographic** in the box under the zoom buttons. The app remembers your choice.

**Read the map.** Roads are coloured by flood-risk state (Low, Watch, High, Severe) and get thicker as risk rises;
the thickest lines are blocked for routing at the current caution level. Green dots are reachable shelters, red
dots are shelters that are themselves at flood risk. Round markers are CWC river gauges.

**Tap a road** to see its flood probability and why: the model's top reasons (for example low height above
drainage, high upstream rain, river above danger level).

**Simulation lab: test it on a real flood.** Choose **Historical day** or press **▶ Run the 2018 flood demo**.
The console then runs entirely on that day's measured inputs: IMD rainfall and CWC river levels. This covers the risk map,
routes, shelters, KPIs, gauges and rainfall. The demo loads 16 August 2018, the peak of the Kerala flood, and routes
from Aluva. The orange badge on the map says which day, and which what-if, you are looking at. Press **Live today** to
return.

**Colour by relative risk** (layers card) highlights the top 5%, 2% and 0.5% of roads for the selected day. It is
useful in an extreme event, when the calibrated probabilities are conservative. Routes still use the probabilities.

**What-if rainfall.** Add +50 to +300 mm over three days. Every road is re-scored, routes are redrawn, the KPI strip
shows the change against live conditions, and the orange badge marks the map as a scenario. Press **Live** to return.

**2018 replay.** Press **▶ 2018 replay** and scrub from 6 to 27 August 2018. The map shows what the model, trained
without any 2018 data, would have predicted each day. On Sentinel-1 days the radar-observed flooding is drawn
underneath in translucent blue.

**15-min safe reach.** Turn on the layer to shade everywhere reachable within 15 minutes on roads that are not
blocked.

**Data feeds.** The top bar and the *Data feeds & model* panel show the age and state of every input. *Provisional*
means IMD real-time grids (revisable) or the Open-Meteo fallback. When live rainfall is unavailable, the system
falls back to a terrain-only model and says so.

## Responder ops (`/responder`)

One filter row (caution level and rainfall scenario) scopes every panel:
* **Day selector:** live, or any preset flood day (same simulation as the console).
* **Taluk map** of residents along at-risk roads (WorldPop estimate), with a table view.
* **Shelter load by taluk:** projected demand against estimated capacity.
* **Road network by flood probability** and **at-risk roads by class.**
* **Upstream dam releases** (reference table, with confidence flags).
* **Highest-risk named roads.**
* **Field-team export:** safest routes from every taluk centre and the hardest-hit towns as GeoJSON or CSV.
* **2018 replay proof:** share of route length on radar-flooded roads, safest versus fastest.

## Model lab (`/model`)

The held-out test of the flood model: PR-AUC versus the logistic-regression baseline, calibration, the drivers of
the prediction, spatial cross-validation folds and the Sentinel-1 dates used. Every number comes from the model's
`metrics.json`; see also `docs/model_card.md`.

## Install as an app

On Android Chrome, open the menu and choose **Add to Home screen**. The last risk map, route and shelter list stay
available when the signal drops; their timestamps show how old they are.
