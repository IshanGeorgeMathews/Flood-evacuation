import numpy as np

from floodevac.common.config import load
from floodevac.routing.cost import Preset, blocked, edge_cost, presets

P = Preset("test", alpha=4.0, beta=0.5, tau=0.5, tau_bridge=0.4)


def test_blocks_above_tau_and_stricter_on_bridges():
    p = np.array([0.49, 0.51, 0.39, 0.41])
    crossing = np.array([0, 0, 1, 1])
    c = edge_cost(np.full(4, 10.0), p, np.zeros(4), crossing, P)
    assert np.isfinite(c[0]) and np.isinf(c[1])
    assert np.isfinite(c[2]) and np.isinf(c[3])
    assert blocked(p, crossing, P).tolist() == [False, True, False, True]


def test_cost_monotonic_in_probability_and_never_below_travel_time():
    p = np.linspace(0, 0.5, 51)
    t = np.full_like(p, 30.0)
    c = edge_cost(t, p, np.full_like(p, 0.2), np.zeros_like(p), P)
    assert np.all(np.diff(c) > 0)
    assert np.all(c >= t)  # keeps the A* straight-line heuristic admissible


def test_configured_presets_are_ordered_from_cautious_to_fast():
    pr = presets(load().routing)
    assert pr["cautious"].tau < pr["balanced"].tau < pr["fast"].tau
    assert pr["cautious"].alpha > pr["balanced"].alpha > pr["fast"].alpha
    assert all(p.tau_bridge <= p.tau for p in pr.values())
