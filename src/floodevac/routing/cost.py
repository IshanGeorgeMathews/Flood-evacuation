"""Risk-weighted edge cost.

    c(e) = t(e) * (1 + alpha * p(e) + beta * k(e)),   c(e) = inf  if p(e) > tau   (tau_bridge on bridges/causeways)

t is free-flow travel time (s), p the calibrated flood probability, k the 0-1 congestion score. Because
c(e) >= t(e), straight-line distance / v_max is an admissible A* heuristic for this cost.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Preset:
    name: str
    alpha: float
    beta: float
    tau: float
    tau_bridge: float


def presets(routing_cfg: dict) -> dict[str, Preset]:
    return {k: Preset(k, **v) for k, v in routing_cfg["presets"].items()}


def blocked(p: np.ndarray, is_crossing: np.ndarray, preset: Preset) -> np.ndarray:
    thr = np.where(is_crossing.astype(bool), preset.tau_bridge, preset.tau)
    return p > thr


def edge_cost(t: np.ndarray, p: np.ndarray, k: np.ndarray, is_crossing: np.ndarray, preset: Preset) -> np.ndarray:
    c = t * (1.0 + preset.alpha * p + preset.beta * k)
    return np.where(blocked(p, is_crossing, preset), np.inf, c)
