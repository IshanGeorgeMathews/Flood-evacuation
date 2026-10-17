import numpy as np
import pandas as pd
from shapely.geometry import LineString

from floodevac.ingest.osm import edge_key, split_line


def test_split_preserves_length_and_continuity():
    line = LineString([(0, 0), (130, 0), (130, 245), (400, 260)])
    parts = split_line(line, 100.0)
    assert abs(sum(p.length for p in parts) - line.length) < 1e-6
    assert all(60 <= p.length <= 140 for p in parts)
    for a, b in zip(parts[:-1], parts[1:]):
        assert np.allclose(a.coords[-1], b.coords[0])


def test_short_line_is_one_segment():
    line = LineString([(0, 0), (40, 0)])
    assert split_line(line, 100.0) == [line]


def test_edge_key_is_direction_free():
    u = pd.Series([1, 2])
    v = pd.Series([2, 1])
    length = pd.Series([123.4, 123.4])
    k = edge_key(u, v, length)
    assert k.iloc[0] == k.iloc[1]
