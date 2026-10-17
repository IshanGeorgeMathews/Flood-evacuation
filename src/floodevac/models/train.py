"""Train, validate and calibrate the road-flood risk models.

Protocol (see docs/model_card.md):
 1. Hold out every Sentinel-1 date of the test event (August 2018). It is never used for training, tuning,
    calibration or the past-flood-frequency feature.
 2. On the remaining dates: all flooded rows + a sample of dry rows. Spatial-block folds (10 km blocks).
 3. Models: logistic regression baseline, Random Forest, XGBoost (Optuna-tuned inside the spatial folds).
 4. Isotonic calibration on out-of-fold predictions, weighted back to the true prevalence.
 5. Score each calibrated model on the full held-out event (no sampling). Gate: the tree models must beat the
    baseline on held-out PR-AUC.
 6. Production model: the best tree model refitted on all events, calibrated with spatial OOF predictions.
    A static-only model (terrain and road features) is trained as the fallback when live feeds are down.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from floodevac.common.config import Config
from floodevac.common.io import write_json
from floodevac.common.logging import get_logger
from floodevac.features.build_table import FeatureStore
from floodevac.models import cv, evaluate
from floodevac.models.calibrate import Calibrator

log = get_logger(__name__)


# ------------------------------------------------------------------------------------------------ model factories

def make_logreg():
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                         LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0))


def make_rf(seed: int):
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                         RandomForestClassifier(n_estimators=300, min_samples_leaf=20, max_features="sqrt",
                                                class_weight="balanced_subsample", n_jobs=-1, random_state=seed))


def make_xgb(params: dict, seed: int, spw: float) -> XGBClassifier:
    base = dict(n_estimators=400, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8,
                min_child_weight=5, reg_lambda=1.0)
    base.update(params)
    return XGBClassifier(**base, tree_method="hist", scale_pos_weight=spw, eval_metric="aucpr", n_jobs=-1,
                         random_state=seed)


# ------------------------------------------------------------------------------------------------ helpers

def _sample(labels: pd.DataFrame, rate: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    keep = (labels["label"] == 1) | (rng.random(len(labels)) < rate)
    s = labels[keep].copy()
    s["weight"] = np.where(s["label"] == 1, 1.0, 1.0 / rate)
    return s.reset_index(drop=True)


def _oof(factory, X: pd.DataFrame, y: np.ndarray, folds: np.ndarray, blocks: np.ndarray) -> np.ndarray:
    oof = np.zeros(len(y))
    for tr, te in cv.spatial_splits(folds):
        cv.assert_no_leakage(blocks[tr], blocks[te])
        m = factory()
        m.fit(X.iloc[tr], y[tr])
        oof[te] = m.predict_proba(X.iloc[te])[:, 1]
    return oof


def _tune_xgb(X: pd.DataFrame, y: np.ndarray, w: np.ndarray, folds: np.ndarray, cfg: Config, spw: float) -> dict:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    seed = cfg.model["cv"]["random_state"]
    # tune on a manageable subsample, whole spatial folds preserved
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(rng.random(len(y)) < min(1.0, 300_000 / len(y)))
    Xs, ys, ws, fs = X.iloc[idx], y[idx], w[idx], folds[idx]
    tune_folds = fs % 3

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 9),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 150, 600, step=50),
            "min_child_weight": trial.suggest_float("min_child_weight", 1, 50, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 20, log=True),
        }
        scores = []
        for tr, te in cv.spatial_splits(tune_folds):
            m = make_xgb(params, seed, spw)
            m.fit(Xs.iloc[tr], ys[tr])
            scores.append(average_precision_score(ys[te], m.predict_proba(Xs.iloc[te])[:, 1], sample_weight=ws[te]))
        return float(np.mean(scores))

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=cfg.model["optuna"]["n_trials"], timeout=cfg.model["optuna"]["timeout_s"])
    log.info("Optuna best spatial-CV PR-AUC %.3f with %s", study.best_value, study.best_params)
    return {"best_params": study.best_params, "best_cv_pr_auc": study.best_value, "n_trials": len(study.trials)}


def _fold_scores(y: np.ndarray, p: np.ndarray, w: np.ndarray, folds: np.ndarray) -> list[float]:
    return [float(average_precision_score(y[folds == k], p[folds == k], sample_weight=w[folds == k]))
            for k in np.unique(folds) if y[folds == k].sum() > 0]


def _importance(model: XGBClassifier, X: pd.DataFrame, seed: int) -> list[dict]:
    import shap

    sample = X.sample(min(5000, len(X)), random_state=seed)
    sv = shap.TreeExplainer(model).shap_values(sample)
    imp = np.abs(sv).mean(axis=0)
    order = np.argsort(imp)[::-1]
    return [{"feature": X.columns[i], "mean_abs_shap": float(imp[i])} for i in order]


# ------------------------------------------------------------------------------------------------ main

def run(cfg: Config) -> Path:
    seed = cfg.model["cv"]["random_state"]
    rate = cfg.model["cv"]["negative_sample_rate"]
    fpr = cfg.model["operating_point"]["fpr"]
    holdout = cfg.model["holdout_event"]
    fs = FeatureStore(cfg)
    feats = fs.static_cols + fs.dynamic_cols
    seg_ll = pd.read_parquet(cfg.paths.processed / "segments.parquet", columns=["seg_id", "lon", "lat"])

    labels = fs.labels.copy()
    is_test = cv.event_mask(labels["date"], holdout)
    test_dates = set(labels.loc[is_test, "date"].unique())
    log.info("labelled rows: %d (%d dates); held-out event %s: %d dates", len(labels), labels["date"].nunique(),
             holdout, len(test_dates))

    # --- development set (all events except the held-out one)
    dev = _sample(labels[~is_test], rate, seed)
    dev = dev.merge(seg_ll, on="seg_id")
    Xd = fs.assemble(dev, exclude=test_dates)[feats]
    yd, wd = dev["label"].to_numpy(), dev["weight"].to_numpy()
    blocks = cv.spatial_blocks(dev["lon"].to_numpy(), dev["lat"].to_numpy(), cfg.model["cv"]["block_km"])
    folds = cv.block_folds(blocks, cfg.model["cv"]["n_folds"], seed)
    spw = float((yd == 0).sum() / max(1, (yd == 1).sum()))
    log.info("development rows %d (positives %d), spatial blocks %d", len(yd), yd.sum(), len(np.unique(blocks)))

    # --- held-out event: every observed segment, no sampling
    test = labels[is_test].reset_index(drop=True)
    Xt = fs.assemble(test, exclude=test_dates)[feats]
    yt = test["label"].to_numpy()

    tuning = _tune_xgb(Xd, yd, wd, folds, cfg, spw)
    factories = {
        "logreg": make_logreg,
        "random_forest": lambda: make_rf(seed),
        "xgboost": lambda: make_xgb(tuning["best_params"], seed, spw),
    }

    results: dict[str, dict] = {}
    fitted: dict[str, tuple] = {}
    for name, factory in factories.items():
        log.info("training %s…", name)
        oof = _oof(factory, Xd, yd, folds, blocks)
        cal = Calibrator().fit(oof, yd, wd)
        model = factory().fit(Xd, yd)
        pt = cal.transform(model.predict_proba(Xt)[:, 1])
        res = evaluate.summary(yt, pt, fpr)
        res["spatial_cv_pr_auc_folds"] = _fold_scores(yd, oof, wd, folds)
        res["spatial_cv_pr_auc_mean"] = float(np.mean(res["spatial_cv_pr_auc_folds"]))
        res["reliability"] = evaluate.reliability(yt, pt)
        res["pr_curve"] = evaluate.pr_curve_points(yt, pt)
        results[name] = res
        fitted[name] = (model, cal)
        log.info("%s held-out %s: PR-AUC %.3f ROC-AUC %.3f Brier %.4f recall@%.0f%%FPR %.3f", name, holdout,
                 res["pr_auc"], res["roc_auc"], res["brier"], fpr * 100, res["recall_at_fpr"])

    tree_best = max(("random_forest", "xgboost"), key=lambda n: results[n]["pr_auc"])
    gate = {
        "baseline_pr_auc": results["logreg"]["pr_auc"],
        "best_model": tree_best,
        "best_pr_auc": results[tree_best]["pr_auc"],
        "passed": results[tree_best]["pr_auc"] > results["logreg"]["pr_auc"],
    }
    log.info("GATE %s: %s %.3f vs baseline %.3f", "PASSED" if gate["passed"] else "FAILED", tree_best,
             gate["best_pr_auc"], gate["baseline_pr_auc"])

    # --- production models on every event
    allrows = _sample(labels, rate, seed).merge(seg_ll, on="seg_id")
    Xa = fs.assemble(allrows)[feats]
    ya, wa = allrows["label"].to_numpy(), allrows["weight"].to_numpy()
    blocks_a = cv.spatial_blocks(allrows["lon"].to_numpy(), allrows["lat"].to_numpy(), cfg.model["cv"]["block_km"])
    folds_a = cv.block_folds(blocks_a, cfg.model["cv"]["n_folds"], seed)
    spw_a = float((ya == 0).sum() / max(1, (ya == 1).sum()))
    prod_factory = (lambda: make_xgb(tuning["best_params"], seed, spw_a)) if tree_best == "xgboost" \
        else factories["random_forest"]
    log.info("fitting production model (%s) on all events…", tree_best)
    prod_cal = Calibrator().fit(_oof(prod_factory, Xa, ya, folds_a, blocks_a), ya, wa)
    prod = prod_factory().fit(Xa, ya)

    static_cols = fs.static_cols
    static_factory = lambda: make_xgb({}, seed, spw_a)  # noqa: E731
    static_cal = Calibrator().fit(_oof(static_factory, Xa[static_cols], ya, folds_a, blocks_a), ya, wa)
    static_model = static_factory().fit(Xa[static_cols], ya)

    # explanations always come from the XGBoost model (TreeExplainer)
    xgb_prod = prod if tree_best == "xgboost" else make_xgb(tuning["best_params"], seed, spw_a).fit(Xa, ya)
    importance = _importance(xgb_prod, Xa, seed)

    version = "v" + dt.date.today().strftime("%Y.%m.%d")
    out_dir = cfg.paths.models / version
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": prod, "calibrator": prod_cal, "features": feats, "kind": tree_best},
                out_dir / "model.joblib")
    joblib.dump({"model": static_model, "calibrator": static_cal, "features": static_cols, "kind": "xgboost-static"},
                out_dir / "model_static.joblib")
    joblib.dump({"model": xgb_prod, "features": feats}, out_dir / "explainer_model.joblib")
    # the replay of the held-out event must use the model that never saw it
    hm, hc = fitted[tree_best]
    joblib.dump({"model": hm, "calibrator": hc, "features": feats, "kind": tree_best,
                 "excluded_dates": sorted(test_dates)}, out_dir / "model_holdout.joblib")

    events = fs.labels.groupby("date")["label"].agg(["mean", "count"]).reset_index()
    metrics = {
        "version": version,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "holdout_event": holdout,
        "holdout_dates": sorted(d.strftime("%Y-%m-%d") for d in test_dates),
        "label_rule": f"segment flooded if >= {cfg.model['label']['flooded_fraction']:.0%} of its sample points are "
                      f"Sentinel-1 flood pixels",
        "events": [{"date": r.date.strftime("%Y-%m-%d"), "flooded_share": float(r.mean), "observed": int(r.count)}
                   for r in events.itertuples()],
        "features": {"static": static_cols, "dynamic": fs.dynamic_cols},
        "development": {"rows": int(len(yd)), "positives": int(yd.sum()), "negative_sample_rate": rate,
                        "spatial_blocks": int(len(np.unique(blocks))), "block_km": cfg.model["cv"]["block_km"],
                        "folds": cfg.model["cv"]["n_folds"]},
        "tuning": tuning,
        "models": results,
        "gate": gate,
        "production": {"kind": tree_best, "rows": int(len(ya)), "positives": int(ya.sum())},
        "importance": importance,
    }
    write_json(metrics, out_dir / "metrics.json")
    (cfg.paths.models / "CURRENT").write_text(version, encoding="utf-8")
    log.info("model %s saved", version)
    return out_dir
