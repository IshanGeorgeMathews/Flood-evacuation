import numpy as np
import pandas as pd
import pytest

from floodevac.features import hydro, rainfall


def _rain():
    dates = pd.date_range("2018-08-01", periods=8, freq="D")
    rows = []
    for i, d in enumerate(dates):
        rows.append((d, 10.0, 76.25, float(i + 1)))
        rows.append((d, 10.25, 77.0, 10.0))
    return pd.DataFrame(rows, columns=["date", "lat", "lon", "rain_mm"])


def test_rain_accumulations_are_trailing_sums():
    r = _rain()
    cells = rainfall.cells(r)
    acc = rainfall.accumulations(r, cells)
    cid = cells.loc[(cells.lat == 10.0) & (cells.lon == 76.25), "cell_id"].iloc[0]
    day5 = acc[(acc.cell_id == cid) & (acc.date == "2018-08-05")].iloc[0]
    assert day5.rain_1d == 5 and day5.rain_3d == 3 + 4 + 5 and day5.rain_5d == 15
    assert np.isnan(day5.rain_7d)  # not enough history: stays missing, never silently zero


def test_upstream_uses_only_cells_in_box():
    r = _rain()
    cells = rainfall.cells(r)
    up = rainfall.upstream(r, cells, [76.75, 9.6, 77.35, 10.45])
    assert up.dropna()["rain_up_3d"].eq(30.0).all()


def test_relative_levels_and_nearest_station():
    meta = pd.DataFrame({"station": ["A", "B"], "danger": [10.0, 5.0], "lon": [76.3, 76.6], "lat": [10.1, 9.9]})
    daily = pd.DataFrame({"station": ["A", "A", "A", "B"],
                          "date": pd.to_datetime(["2018-08-14", "2018-08-15", "2018-08-16", "2018-08-16"]),
                          "level": [9.0, 12.0, 11.0, 4.0]})
    rel = hydro.relative_levels(daily, meta)
    a16 = rel[(rel.station == "A") & (rel.date == "2018-08-16")].iloc[0]
    assert a16.rel == pytest.approx(1.0) and a16.rel_3d == pytest.approx(2.0)
    st, dist = hydro.nearest_station(np.array([76.31]), np.array([10.09]), meta)
    assert st[0] == "A" and dist[0] < 2
