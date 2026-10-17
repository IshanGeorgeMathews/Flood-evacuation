# Model card — road flood-risk model v2026.10.16

*Generated from `models/v2026.10.16/metrics.json` on 2026-10-16. Do not edit by hand; re-run
`python -m floodevac.pipeline train`.*

## What it predicts

The calibrated probability that a ~100 m road segment in Ernakulam district is under water on a given day,
from terrain, land cover, road attributes, recent IMD rainfall (local and upstream) and CWC river levels.
The probability feeds the evacuation router's edge cost, so calibration matters as much as ranking.

## Labels

segment flooded if >= 30% of its sample points are Sentinel-1 flood pixels. Flood maps were derived from Sentinel-1 VV backscatter in Google Earth Engine (change detection
against a same-orbit dry-season reference plus an Otsu threshold, masking JRC permanent water and slopes > 5°).
Positives are reliable; negatives mean *not observed flooded*.

| Date | Segments observed | Flooded | Use |
|---|---|---|---|
| 2017-06-03 | 172,265 | 0.01% | training |
| 2017-09-19 | 172,265 | 0.04% | training |
| 2017-10-01 | 172,265 | 0.00% | training |
| 2017-10-25 | 172,265 | 0.00% | training |
| 2018-07-16 | 172,265 | 0.01% | training |
| 2018-08-09 | 172,265 | 0.03% | held-out test |
| 2018-08-21 | 172,265 | 0.16% | held-out test |
| 2018-08-27 | 172,265 | 0.02% | held-out test |
| 2019-07-05 | 172,265 | 0.01% | training |
| 2019-08-10 | 172,265 | 0.17% | training |
| 2019-08-22 | 172,265 | 0.01% | training |
| 2019-09-27 | 172,265 | 0.01% | training |
| 2020-07-17 | 172,265 | 0.00% | training |
| 2020-08-10 | 172,265 | 0.08% | training |
| 2020-08-22 | 172,265 | 0.01% | training |
| 2020-09-27 | 172,265 | 0.00% | training |
| 2021-06-18 | 172,265 | 0.02% | training |
| 2021-08-17 | 172,265 | 0.01% | training |
| 2021-09-10 | 172,265 | 0.01% | training |
| 2021-11-21 | 172,265 | 0.01% | training |
| 2022-06-25 | 172,265 | 0.00% | training |
| 2022-09-05 | 172,265 | 0.01% | training |
| 2022-09-17 | 172,265 | 0.00% | training |
| 2022-10-11 | 172,265 | 0.01% | training |
| 2023-07-02 | 172,265 | 0.00% | training |
| 2023-07-26 | 172,265 | 0.00% | training |
| 2023-08-31 | 172,265 | 0.01% | training |
| 2023-10-18 | 172,265 | 0.01% | training |
| 2024-06-26 | 172,265 | 0.01% | training |
| 2024-08-01 | 172,265 | 0.04% | training |
| 2024-08-13 | 172,265 | 0.01% | training |
| 2024-09-06 | 172,265 | 0.01% | training |

## Validation protocol

* **Held-out event:** every Sentinel-1 date of `2018-08` is the test set. It is never used for
  training, tuning, calibration, or the past-flood-frequency feature.
* **Spatial-block cross-validation** on the remaining events: 5 folds of
  10 km blocks (47 blocks), whole blocks per fold.
* Dry rows sampled at 5% for training; calibration weights them back.
* XGBoost tuned with Optuna inside the spatial folds (25 trials).

## Results on the held-out event

Prevalence on the held-out event: 0.07% of observed segment-days.
Recall is reported at a 5% false-alarm rate.

| Model | PR-AUC | ROC-AUC | Recall @ FPR | Brier | Spatial-CV PR-AUC |
|---|---|---|---|---|---|
| Logistic regression (baseline) | 0.138 | 0.995 | 99.2% | 0.0007 | 0.116 |
| Random Forest | 0.173 | 0.996 | 99.7% | 0.0007 | 0.299 |
| XGBoost | 0.235 | 0.997 | 100.0% | 0.0006 | 0.348 |

**Gate PASSED:** XGBoost PR-AUC 0.235 vs baseline
0.138.

### Operating points (held-out model, held-out event)

What each probability threshold would have caught in August 2018. The routing presets block roads at 10%
(cautious), 20% (balanced) and 40% (fast); lower thresholds catch more flooded roads at the cost of more false alarms.

| Threshold | Recall (flooded roads caught) | Precision (flagged roads that flooded) | Segment-days flagged |
|---|---|---|---|
| 1% | 59% | 13% | 1,597 |
| 2% | 25% | 29% | 296 |
| 5% | 19% | 46% | 146 |
| 10% | 14% | 57% | 87 |
| 20% | 10% | 62% | 56 |
| 40% | 5% | 78% | 23 |

**Reading this honestly:** the model ranks roads very well (ROC-AUC above), but 2018 was more extreme than any
event it trained on, so its probabilities for that event are conservative — many roads that flooded received
probabilities of 1–10%. During an extreme event use the *cautious* preset and treat the *Watch* class as a warning.

### Calibration (XGBoost, held-out event)

| Predicted bin | Mean predicted | Observed | n |
|---|---|---|---|
| 0.0-0.1 | 0.000 | 0.001 | 516,708 |
| 0.1-0.2 | 0.142 | 0.484 | 31 |
| 0.3-0.4 | 0.320 | 0.515 | 33 |
| 0.4-0.5 | 0.456 | 0.667 | 9 |
| 0.6-0.7 | 0.659 | 0.818 | 11 |
| 0.9-1.0 | 1.000 | 1.000 | 3 |

## What drives predictions (production model, mean |SHAP|)

1. `elev` — mean |SHAP| 2.561
2. `hand` — mean |SHAP| 2.165
3. `landcover_tree` — mean |SHAP| 1.152
4. `landcover_built` — mean |SHAP| 0.937
5. `landcover_water` — mean |SHAP| 0.575
6. `pop_density` — mean |SHAP| 0.557
7. `past_flood_freq` — mean |SHAP| 0.519
8. `dist_gauge_km` — mean |SHAP| 0.509
9. `rain_7d` — mean |SHAP| 0.337
10. `dist_stream_m` — mean |SHAP| 0.310

## Production model

`xgboost` refitted on all events (276,715 rows,
1,225 flooded), calibrated with spatial out-of-fold predictions. A static-only model
(terrain and road features) is used automatically when the live rainfall feed is unavailable. The August 2018
replay uses the held-out model only.

## Known blind spots

* Sentinel-1 misses water under tree canopy and between buildings; passes can miss the flood peak (there was no
  pass over Ernakulam on 15–17 August 2018).
* IMD gridded rainfall is ~27 km and daily; local cloudbursts and flash floods are not resolved.
* Four CWC gauges serve the district; dam releases are not a direct input (their effect reaches the model
  through the downstream Periyar gauge).
* OpenStreetMap coverage of rural lanes is incomplete; shelter capacities are estimates until DDMA data arrives.

## Intended use

Decision support for evacuation planning and route guidance in Ernakulam district. Official KSDMA and District
Administration orders always take priority.
