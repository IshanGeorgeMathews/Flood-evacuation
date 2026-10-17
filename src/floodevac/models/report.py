"""Write docs/model_card.md from models/<version>/metrics.json, so every number in it is the measured one."""

from __future__ import annotations

from pathlib import Path

from floodevac.common.config import Config
from floodevac.common.io import read_json
from floodevac.models.predict import current_version

NAMES = {"logreg": "Logistic regression (baseline)", "random_forest": "Random Forest", "xgboost": "XGBoost"}
THRESHOLDS = [0.01, 0.02, 0.05, 0.10, 0.20, 0.40]


def operating_points(cfg: Config) -> list[dict]:
    """Recall / precision of the held-out model on the held-out event at fixed probability thresholds
    (the thresholds the routing presets use). Measured on the test event, never used to choose them."""
    import pandas as pd

    from floodevac.models.predict import Predictor

    pr = Predictor(cfg, holdout=True)
    lab = pr.store.labels
    test = lab[lab["date"].isin(pd.to_datetime(sorted(pr.exclude)))]
    p_all, y_all = [], []
    for d, g in test.groupby("date"):
        s = pr.score(d, g["seg_id"])
        p_all.append(s.p)
        y_all.append(g["label"].to_numpy())
    import numpy as np

    p, y = np.concatenate(p_all), np.concatenate(y_all)
    rows = []
    for t in THRESHOLDS:
        flag = p >= t
        rows.append({"threshold": t, "recall": float(flag[y == 1].mean()) if (y == 1).any() else 0.0,
                     "precision": float(y[flag].mean()) if flag.any() else 0.0, "flagged": int(flag.sum())})
    return rows


def write_model_card(cfg: Config) -> Path:
    from floodevac.common.io import write_json

    v = current_version(cfg)
    mpath = cfg.paths.models / v / "metrics.json"
    m = read_json(mpath)
    if "operating_points" not in m:
        m["operating_points"] = operating_points(cfg)
        write_json(m, mpath)
    ops = "\n".join(f"| {o['threshold']:.0%} | {o['recall']:.0%} | {o['precision']:.0%} | {o['flagged']:,} |"
                    for o in m["operating_points"])
    g = m["gate"]
    rows = "\n".join(
        f"| {NAMES[k]} | {r['pr_auc']:.3f} | {r['roc_auc']:.3f} | {r['recall_at_fpr']:.1%} | {r['brier']:.4f} | "
        f"{r['spatial_cv_pr_auc_mean']:.3f} |" for k, r in m["models"].items())
    best = m["models"][g["best_model"]]
    ev = "\n".join(f"| {e['date']} | {e['observed']:,} | {e['flooded_share']:.2%} | "
                   f"{'held-out test' if e['date'] in m['holdout_dates'] else 'training'} |" for e in m["events"])
    imp = "\n".join(f"{i + 1}. `{f['feature']}` — mean |SHAP| {f['mean_abs_shap']:.3f}"
                    for i, f in enumerate(m["importance"][:10]))
    rel = "\n".join(f"| {b['bin']} | {b['mean_pred']:.3f} | {b['observed']:.3f} | {b['n']:,} |"
                    for b in best["reliability"])
    text = f"""# Model card — road flood-risk model {v}

*Generated from `models/{v}/metrics.json` on {m['trained_at'][:10]}. Do not edit by hand; re-run
`python -m floodevac.pipeline train`.*

## What it predicts

The calibrated probability that a ~100 m road segment in Ernakulam district is under water on a given day,
from terrain, land cover, road attributes, recent IMD rainfall (local and upstream) and CWC river levels.
The probability feeds the evacuation router's edge cost, so calibration matters as much as ranking.

## Labels

{m['label_rule']}. Flood maps were derived from Sentinel-1 VV backscatter in Google Earth Engine (change detection
against a same-orbit dry-season reference plus an Otsu threshold, masking JRC permanent water and slopes > 5°).
Positives are reliable; negatives mean *not observed flooded*.

| Date | Segments observed | Flooded | Use |
|---|---|---|---|
{ev}

## Validation protocol

* **Held-out event:** every Sentinel-1 date of `{m['holdout_event']}` is the test set. It is never used for
  training, tuning, calibration, or the past-flood-frequency feature.
* **Spatial-block cross-validation** on the remaining events: {m['development']['folds']} folds of
  {m['development']['block_km']} km blocks ({m['development']['spatial_blocks']} blocks), whole blocks per fold.
* Dry rows sampled at {m['development']['negative_sample_rate']:.0%} for training; calibration weights them back.
* XGBoost tuned with Optuna inside the spatial folds ({m['tuning']['n_trials']} trials).

## Results on the held-out event

Prevalence on the held-out event: {best['prevalence']:.2%} of observed segment-days.
Recall is reported at a {best['fpr_target']:.0%} false-alarm rate.

| Model | PR-AUC | ROC-AUC | Recall @ FPR | Brier | Spatial-CV PR-AUC |
|---|---|---|---|---|---|
{rows}

**Gate {'PASSED' if g['passed'] else 'FAILED'}:** {NAMES[g['best_model']]} PR-AUC {g['best_pr_auc']:.3f} vs baseline
{g['baseline_pr_auc']:.3f}.

### Operating points (held-out model, held-out event)

What each probability threshold would have caught in August 2018. The routing presets block roads at 10%
(cautious), 20% (balanced) and 40% (fast); lower thresholds catch more flooded roads at the cost of more false alarms.

| Threshold | Recall (flooded roads caught) | Precision (flagged roads that flooded) | Segment-days flagged |
|---|---|---|---|
{ops}

**Reading this honestly:** the model ranks roads very well (ROC-AUC above), but 2018 was more extreme than any
event it trained on, so its probabilities for that event are conservative — many roads that flooded received
probabilities of 1–10%. During an extreme event use the *cautious* preset and treat the *Watch* class as a warning.

### Calibration ({NAMES[g['best_model']]}, held-out event)

| Predicted bin | Mean predicted | Observed | n |
|---|---|---|---|
{rel}

## What drives predictions (production model, mean |SHAP|)

{imp}

## Production model

`{m['production']['kind']}` refitted on all events ({m['production']['rows']:,} rows,
{m['production']['positives']:,} flooded), calibrated with spatial out-of-fold predictions. A static-only model
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
"""
    out = cfg.paths.docs / "model_card.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
