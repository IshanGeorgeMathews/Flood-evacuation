"""Upstream dam releases (Idukki/Cheruthoni, Idamalayar) from a hand-compiled reference table.

There is no machine-readable release feed. data/reference/dams.csv records opening dates as widely reported in the
news; they have NOT been verified against official KSEB / KSDMA notices. Every row carries a confidence flag.
Releases are shown on the Responder dashboard timeline. They are not a model feature: the downstream Periyar gauge
(Neeleeswaram) already measures their effect, and dates this coarse would add noise.
"""

from __future__ import annotations

import pandas as pd

from floodevac.common.config import Config


def load(cfg: Config) -> pd.DataFrame:
    df = pd.read_csv(cfg.paths.root / "data" / "reference" / "dams.csv", parse_dates=["start_date", "end_date"])
    return df


def active_on(cfg: Config, date: pd.Timestamp) -> pd.DataFrame:
    df = load(cfg)
    end = df["end_date"].fillna(df["start_date"] + pd.Timedelta(days=7))
    return df[(df["start_date"] <= date) & (end >= date)]
