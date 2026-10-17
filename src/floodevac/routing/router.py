"""Evacuation routing engine.

* Shelter trees: one reverse multi-source Dijkstra per cost preset after each risk refresh. A virtual source links
  to every open shelter with a capacity penalty, so every node learns its best reachable shelter and next hop;
  a route query is then a pointer walk.
* Fastest baseline: the same search on plain travel time with no risk and no blocking (the "plain shortest path"
  the safest route is compared against).
* Point-to-point and alternatives: A* on the risk-weighted cost with a straight-line / v_max heuristic, which is
  admissible because c(e) >= t(e).
* Isochrone: everything reachable within N minutes of free-flow driving on roads that are not blocked.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from floodevac.routing.cost import Preset, blocked, edge_cost

EARTH_R = 6_371_000.0
COS_LAT = math.cos(math.radians(10.0))


def haversine_m(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------------------------------------------- topology

class Network:
    """Static road topology: nodes, directed edges, geometry, nearest-node index."""

    def __init__(self, edges: pd.DataFrame, nodes: pd.DataFrame):
        self.nodes = nodes.reset_index(drop=True)
        self.n = len(nodes)
        index = pd.Series(np.arange(self.n), index=nodes["node"].to_numpy())
        self.lon = nodes["lon"].to_numpy(dtype="float64")
        self.lat = nodes["lat"].to_numpy(dtype="float64")
        self.edges = edges.reset_index(drop=True)
        self.src = index.reindex(edges["u"].to_numpy()).to_numpy()
        self.dst = index.reindex(edges["v"].to_numpy()).to_numpy()
        self.t = edges["t_s"].to_numpy(dtype="float64")
        self.length = edges["length"].to_numpy(dtype="float64")
        self.crossing = ((edges["is_bridge"] == 1) | (edges["is_causeway"] == 1)).to_numpy()
        self.coords = [np.asarray(g.coords)[:, ::-1].round(6) for g in edges.geometry]  # (lat, lon)
        self._tree = cKDTree(np.column_stack([self.lon * COS_LAT, self.lat]))

    @classmethod
    def from_arrays(cls, src, dst, t, length, lon, lat, crossing=None) -> "Network":
        """Build a network from raw arrays (used by tests and toy graphs)."""
        import geopandas as gpd
        from shapely.geometry import LineString

        nodes = pd.DataFrame({"node": np.arange(len(lon)), "lon": lon, "lat": lat})
        geom = [LineString([(lon[a], lat[a]), (lon[b], lat[b])]) for a, b in zip(src, dst)]
        crossing = np.zeros(len(src), dtype=int) if crossing is None else np.asarray(crossing, dtype=int)
        edges = gpd.GeoDataFrame({"u": src, "v": dst, "t_s": t, "length": length, "is_bridge": crossing,
                                  "is_causeway": 0}, geometry=geom)
        return cls(edges, nodes)

    def nearest_nodes(self, lon: float, lat: float, k: int = 8) -> np.ndarray:
        _, idx = self._tree.query([lon * COS_LAT, lat], k=k)
        return np.atleast_1d(idx)

    def matrix(self, w: np.ndarray, reverse: bool = False, extra: tuple | None = None):
        """CSR adjacency with the cheapest of any parallel edges; infinite-cost edges are dropped.
        Returns (matrix, pair->edge lookup). `extra` = (src, dst, w) rows appended (virtual edges)."""
        ok = np.isfinite(w)
        a, b, ww, eid = self.src[ok], self.dst[ok], np.maximum(w[ok], 1e-3), np.flatnonzero(ok)
        df = pd.DataFrame({"a": a, "b": b, "w": ww, "eid": eid}).sort_values("w").drop_duplicates(["a", "b"])
        lookup = pd.Series(df["eid"].to_numpy(), index=pd.MultiIndex.from_arrays([df["a"], df["b"]]))
        ra, rb, rw = df["a"].to_numpy(), df["b"].to_numpy(), df["w"].to_numpy()
        if reverse:
            ra, rb = rb, ra
        size = self.n
        if extra is not None:
            ea, eb, ew = extra
            ra, rb, rw = np.concatenate([ra, ea]), np.concatenate([rb, eb]), np.concatenate([rw, np.maximum(ew, 1e-3)])
            size = self.n + 1
        return csr_matrix((rw, (ra, rb)), shape=(size, size)), lookup


# ---------------------------------------------------------------------------------------------------- search

def astar(m: csr_matrix, lon: np.ndarray, lat: np.ndarray, source: int, target: int, v_max_mps: float
          ) -> tuple[float, list[int]]:
    """A* on a CSR graph with an admissible straight-line-time heuristic. Returns (cost, node path)."""
    indptr, indices, data = m.indptr, m.indices, m.data
    tl, tb = lon[target], lat[target]

    def h(n: int) -> float:
        return float(haversine_m(lon[n], lat[n], tl, tb)) / v_max_mps

    g = {source: 0.0}
    prev: dict[int, int] = {}
    heap = [(h(source), 0.0, source)]
    closed: set[int] = set()
    while heap:
        _, gc, n = heapq.heappop(heap)
        if n in closed:
            continue
        if n == target:
            path = [n]
            while n in prev:
                n = prev[n]
                path.append(n)
            return gc, path[::-1]
        closed.add(n)
        for j in range(indptr[n], indptr[n + 1]):
            nb = int(indices[j])
            if nb in closed:
                continue
            ng = gc + data[j]
            if ng < g.get(nb, math.inf):
                g[nb] = ng
                prev[nb] = n
                heapq.heappush(heap, (ng + h(nb), ng, nb))
    return math.inf, []


@dataclass
class ShelterTree:
    dist: np.ndarray        # cost from node to its best shelter (incl. capacity penalty)
    next_hop: np.ndarray    # next node towards that shelter (-9999 at the shelter / unreachable)
    shelter_of: np.ndarray  # index into the shelter table, -1 if unreachable
    lookup: pd.Series       # (a, b) -> eid for the weights used


def shelter_tree(net: Network, w: np.ndarray, shelter_nodes: np.ndarray, penalty_s: np.ndarray) -> ShelterTree:
    """Reverse multi-source Dijkstra from all shelters through a virtual source with per-shelter penalties."""
    S = net.n
    extra = (np.full(len(shelter_nodes), S), shelter_nodes, penalty_s)
    m, lookup = net.matrix(w, reverse=True, extra=extra)
    dist, pred = dijkstra(m, directed=True, indices=S, return_predecessors=True)
    dist, pred = dist[: net.n], pred[: net.n]
    # each node: walk back to the node whose predecessor is the virtual source -> that is its shelter node
    shelter_node = np.full(net.n, -1)
    reach = np.isfinite(dist)
    direct = reach & (pred == S)
    shelter_node[direct] = np.flatnonzero(direct)
    order = np.argsort(dist)
    for n in order:
        if not reach[n] or shelter_node[n] >= 0:
            continue
        shelter_node[n] = shelter_node[pred[n]]
    # map shelter node -> best (lowest penalty) shelter index at that node
    best = {}
    for i, (node, pen) in enumerate(zip(shelter_nodes, penalty_s)):
        if node not in best or pen < penalty_s[best[node]]:
            best[node] = i
    shelter_of = np.array([best.get(sn, -1) if sn >= 0 else -1 for sn in shelter_node])
    next_hop = np.where(direct, -9999, pred)
    return ShelterTree(dist, next_hop, shelter_of, lookup)


def walk(tree: ShelterTree, start: int) -> list[int]:
    path = [start]
    n = start
    for _ in range(100_000):
        nh = tree.next_hop[n]
        if nh < 0:
            break
        path.append(int(nh))
        n = int(nh)
    return path


def path_edges(path: list[int], lookup: pd.Series) -> list[int]:
    return [int(lookup.loc[(a, b)]) for a, b in zip(path[:-1], path[1:])]


# ---------------------------------------------------------------------------------------------------- state

@dataclass
class RiskState:
    """Everything that changes when risk is re-scored."""
    p_edge: np.ndarray
    k_edge: np.ndarray
    costs: dict[str, np.ndarray]
    trees: dict[str, ShelterTree]
    fastest: ShelterTree
    shelter_open: dict[str, np.ndarray]
    shelter_p: np.ndarray
    demand: dict[str, np.ndarray] = field(default_factory=dict)


class Router:
    def __init__(self, net: Network, shelters: pd.DataFrame, presets: dict[str, Preset], routing_cfg: dict):
        self.net = net
        self.cfg = routing_cfg
        self.presets = presets
        self.v_max = routing_cfg["v_max_kmh"] / 3.6
        self.shelters = shelters.reset_index(drop=True)
        self.shelter_nodes = np.array([net.nearest_nodes(x, y, k=1)[0] for x, y in
                                       zip(self.shelters["lon"], self.shelters["lat"])])
        self.capacity = self.shelters["capacity"].to_numpy(dtype="float64")
        self.state: RiskState | None = None
        self._fastest: ShelterTree | None = None

    # -- refresh
    def update(self, p_edge: np.ndarray, k_edge: np.ndarray, node_demand: np.ndarray | None = None) -> RiskState:
        net = self.net
        # shelter flood risk: worst probability among roads touching its access node
        incident = pd.Series(p_edge).groupby(net.dst).max()
        shelter_p = incident.reindex(self.shelter_nodes).fillna(0).to_numpy()
        costs, trees, open_, demand = {}, {}, {}, {}
        for name, pr in self.presets.items():
            c = edge_cost(net.t, p_edge, k_edge, net.crossing, pr)
            costs[name] = c
            is_open = shelter_p <= pr.tau
            open_[name] = is_open
            nodes = self.shelter_nodes[is_open]
            idx = np.flatnonzero(is_open)
            penalty = np.zeros(len(nodes))
            tree = None
            load = np.zeros(len(self.shelters))
            for _ in range(2):  # assign, then penalise full shelters and re-assign once
                tree = shelter_tree(net, c, nodes, penalty)
                load = np.zeros(len(self.shelters))
                if node_demand is not None:
                    s = tree.shelter_of
                    ok = s >= 0
                    np.add.at(load, idx[s[ok]], node_demand[ok])
                ratio = load[idx] / np.maximum(self.capacity[idx], 1)
                penalty = self.cfg["capacity_penalty"] * np.clip(ratio, 0, 3) * 600.0
            if len(idx):
                tree.shelter_of = np.where(tree.shelter_of >= 0, idx[np.maximum(tree.shelter_of, 0)], -1)
            trees[name] = tree
            demand[name] = load
        if self._fastest is None:  # plain travel time: independent of risk, so built once
            self._fastest = shelter_tree(net, net.t.copy(), self.shelter_nodes, np.zeros(len(self.shelter_nodes)))
        fastest = self._fastest
        self.state = RiskState(p_edge, k_edge, costs, trees, fastest, open_, shelter_p, demand)
        return self.state

    # -- queries
    def _summary(self, eids: list[int], kind: str, shelter: int, st: RiskState) -> dict:
        net = self.net
        e = np.asarray(eids, dtype=int)
        risky = st.p_edge[e] > self.cfg["risky_p"] if len(e) else np.array([], bool)
        coords: list[list[float]] = []
        for i in e:
            c = net.coords[i].tolist()
            coords.extend(c if not coords else c[1:])
        sh = self.shelters.iloc[shelter] if shelter >= 0 else None
        return {
            "kind": kind,
            "geometry": {"type": "LineString", "coordinates": [[c[1], c[0]] for c in coords]},
            "eta_s": float(net.t[e].sum()) if len(e) else 0.0,
            "dist_m": float(net.length[e].sum()) if len(e) else 0.0,
            "exposure_m": float(net.length[e][risky].sum()) if len(e) else 0.0,
            "max_p": float(st.p_edge[e].max()) if len(e) else 0.0,
            "mean_p": float(np.average(st.p_edge[e], weights=net.length[e])) if len(e) else 0.0,
            "edges": e.tolist(),
            "shelter": None if sh is None else {"id": sh["shelter_id"], "name": sh["name"],
                                                 "lat": float(sh["lat"]), "lon": float(sh["lon"]),
                                                 "capacity": int(sh["capacity"])},
        }

    def _origin(self, lon: float, lat: float, tree: ShelterTree) -> int | None:
        for n in self.net.nearest_nodes(lon, lat, k=12):
            if np.isfinite(tree.dist[n]) and tree.shelter_of[n] >= 0:
                return int(n)
        return None

    def route(self, lon: float, lat: float, preset: str, state: RiskState | None = None) -> dict:
        st = state or self.state
        pr = self.presets[preset]
        tree = st.trees[preset]
        warnings: list[str] = []
        origin = self._origin(lon, lat, tree)
        routes = []
        if origin is None:
            warnings.append("No open shelter is reachable on roads below the flood-risk threshold. Move to the "
                            "nearest high ground and follow official instructions.")
        else:
            path = walk(tree, origin)
            eids = path_edges(path, tree.lookup)
            shelter = int(tree.shelter_of[origin])
            safest = self._summary(eids, "safest", shelter, st)
            routes.append(safest)
            # alternative: penalise the safest route's edges and search again with A*
            alt_cost = st.costs[preset].copy()
            alt_cost[eids] *= 1.6
            m, lookup = self.net.matrix(alt_cost)
            target = int(self.shelter_nodes[shelter])
            cost, apath = astar(m, self.net.lon, self.net.lat, origin, target, self.v_max)
            if apath and len(apath) > 1:
                aeids = path_edges(apath, lookup)
                if set(aeids) != set(eids):
                    routes.append(self._summary(aeids, "alternative", shelter, st))
        # fastest: plain shortest travel time to any shelter, ignoring flood risk (comparison baseline)
        fo = self._origin(lon, lat, st.fastest)
        if fo is not None:
            fpath = walk(st.fastest, fo)
            feids = path_edges(fpath, st.fastest.lookup)
            fastest = self._summary(feids, "fastest", int(st.fastest.shelter_of[fo]), st)
            fb = blocked(st.p_edge[np.asarray(feids, dtype=int)], self.net.crossing[np.asarray(feids, dtype=int)], pr)
            fastest["blocked_on_route"] = int(fb.sum())
            routes.append(fastest)
            if routes and routes[0]["kind"] == "safest":
                routes[0]["blocked_avoided"] = int(fb.sum())
            if fb.any():
                warnings.append(f"The fastest route crosses {int(fb.sum())} road section(s) above the "
                                f"{preset} risk threshold.")
        return {"routes": routes, "warnings": warnings, "preset": preset,
                "origin": {"lat": lat, "lon": lon, "snapped": origin is not None}}

    def isochrone(self, lon: float, lat: float, minutes: float, preset: str, state: RiskState | None = None) -> dict:
        st = state or self.state
        pr = self.presets[preset]
        w = np.where(blocked(st.p_edge, self.net.crossing, pr), np.inf, self.net.t)
        m, _ = self.net.matrix(w)
        origin = int(self.net.nearest_nodes(lon, lat, k=1)[0])
        dist = dijkstra(m, directed=True, indices=origin, limit=minutes * 60)
        reach = np.flatnonzero(np.isfinite(dist))
        if len(reach) < 3:
            return {"type": "Feature", "geometry": None, "properties": {"nodes": int(len(reach))}}
        pts = shapely.multipoints(np.column_stack([self.net.lon[reach], self.net.lat[reach]]))
        hull = shapely.concave_hull(pts, ratio=0.25).buffer(0.002)
        return {"type": "Feature", "geometry": shapely.geometry.mapping(hull),
                "properties": {"minutes": minutes, "nodes": int(len(reach)), "preset": preset}}
