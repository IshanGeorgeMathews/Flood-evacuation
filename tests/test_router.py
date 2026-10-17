import math

import numpy as np
import pandas as pd
import pytest
from scipy.sparse.csgraph import dijkstra

from floodevac.routing.cost import Preset
from floodevac.routing.router import Network, Router, astar, haversine_m, path_edges, shelter_tree, walk

V_MAX = 80 / 3.6


def grid_network(n=12, seed=0):
    """Directed n x n grid around Kochi with random one-way removals; t from real distances."""
    rng = np.random.default_rng(seed)
    lon0, lat0, step = 76.25, 9.95, 0.004
    ids = np.arange(n * n).reshape(n, n)
    lon = (lon0 + step * np.tile(np.arange(n), n)).astype(float)
    lat = (lat0 + step * np.repeat(np.arange(n), n)).astype(float)
    src, dst = [], []
    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                a, b = i + di, j + dj
                if 0 <= a < n and 0 <= b < n and rng.random() > 0.08:
                    src.append(ids[i, j])
                    dst.append(ids[a, b])
    src, dst = np.array(src), np.array(dst)
    length = haversine_m(lon[src], lat[src], lon[dst], lat[dst])
    speed = rng.uniform(15, 60, len(src)) / 3.6
    return Network.from_arrays(src, dst, length / speed, length, lon, lat)


def test_astar_matches_dijkstra_on_random_pairs():
    net = grid_network()
    rng = np.random.default_rng(1)
    w = net.t * (1 + rng.uniform(0, 3, len(net.t)))  # risk-weighted cost >= t keeps the heuristic admissible
    m, _ = net.matrix(w)
    dist = dijkstra(m, directed=True)
    for _ in range(40):
        s, t = rng.integers(0, net.n, 2)
        cost, path = astar(m, net.lon, net.lat, int(s), int(t), V_MAX)
        if math.isinf(dist[s, t]):
            assert path == []
        else:
            assert cost == pytest.approx(dist[s, t], rel=1e-9)
            assert path[0] == s and path[-1] == t


def test_shelter_tree_matches_brute_force():
    net = grid_network(seed=3)
    rng = np.random.default_rng(4)
    w = net.t.copy()
    shelters = rng.choice(net.n, 4, replace=False)
    penalty = np.array([0.0, 120.0, 0.0, 600.0])
    tree = shelter_tree(net, w, shelters, penalty)
    m, _ = net.matrix(w)
    to_shelter = np.stack([dijkstra(m, directed=True)[:, s] + pen for s, pen in zip(shelters, penalty)], axis=1)
    best = to_shelter.min(axis=1)
    reach = np.isfinite(best)
    assert np.allclose(tree.dist[reach], best[reach], atol=0.01)  # virtual edges carry a 1e-3 s floor
    for node in np.flatnonzero(reach)[:30]:
        assert to_shelter[node, tree.shelter_of[node]] == pytest.approx(best[node], abs=0.01)
        path = walk(tree, int(node))
        assert path[-1] == shelters[tree.shelter_of[node]]
        cost = w[path_edges(path, tree.lookup)].sum() + penalty[tree.shelter_of[node]]
        assert cost == pytest.approx(best[node], abs=0.01)


def test_router_avoids_blocked_edges_and_reports_fastest_baseline():
    net = grid_network(seed=5)
    shelters = pd.DataFrame({"shelter_id": ["S0"], "name": ["Hall"], "lon": [net.lon[-1]], "lat": [net.lat[-1]],
                             "capacity": [500]})
    preset = Preset("balanced", 4.0, 0.5, 0.5, 0.4)
    router = Router(net, shelters, {"balanced": preset}, {"v_max_kmh": 80, "capacity_penalty": 1.0, "risky_p": 0.5})
    p = np.zeros(len(net.t))
    first = router.update(p, np.zeros(len(net.t)))
    res = router.route(net.lon[0], net.lat[0], "balanced", state=first)
    safest = next(r for r in res["routes"] if r["kind"] == "safest")
    # flood the safest route's middle edge and re-route
    e_mid = None
    tree = first.trees["balanced"]
    origin = int(net.nearest_nodes(net.lon[0], net.lat[0], k=1)[0])
    eids = path_edges(walk(tree, origin), tree.lookup)
    e_mid = eids[len(eids) // 2]
    p2 = p.copy()
    p2[e_mid] = 0.9
    second = router.update(p2, np.zeros(len(net.t)))
    res2 = router.route(net.lon[0], net.lat[0], "balanced", state=second)
    safest2 = next(r for r in res2["routes"] if r["kind"] == "safest")
    assert e_mid not in safest2["edges"]
    assert safest2["max_p"] <= 0.5
    fastest2 = next(r for r in res2["routes"] if r["kind"] == "fastest")
    assert fastest2["eta_s"] <= safest2["eta_s"] + 1e-6
    assert safest["dist_m"] > 0
