"""Metrics for rare-event, probability-feeding models: PR-AUC, recall at a fixed false-alarm rate, Brier score,
reliability curve and ROC-AUC."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score, roc_curve


def recall_at_fpr(y: np.ndarray, p: np.ndarray, fpr_target: float) -> tuple[float, float]:
    """Recall achievable while keeping the false-alarm rate at or below fpr_target, and the threshold used."""
    fpr, tpr, thr = roc_curve(y, p)
    ok = np.flatnonzero(fpr <= fpr_target)
    i = ok[-1]
    return float(tpr[i]), float(min(thr[i], 1.0))


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "mean_pred": float(p[m].mean()),
                    "observed": float(y[m].mean()), "n": int(m.sum())})
    return out


def pr_curve_points(y: np.ndarray, p: np.ndarray, n: int = 60) -> list[dict]:
    prec, rec, _ = precision_recall_curve(y, p)
    take = np.unique(np.linspace(0, len(prec) - 1, n).astype(int))
    return [{"recall": float(rec[i]), "precision": float(prec[i])} for i in take]


def summary(y: np.ndarray, p: np.ndarray, fpr_target: float) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype="float64")
    rec, thr = recall_at_fpr(y, p, fpr_target)
    return {
        "n": int(len(y)),
        "prevalence": float(y.mean()),
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "recall_at_fpr": rec,
        "fpr_target": fpr_target,
        "threshold_at_fpr": thr,
    }
