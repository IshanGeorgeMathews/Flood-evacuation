"""Command-line entry point for the offline pipeline.

    python -m floodevac.pipeline all            # everything, cached steps are skipped
    python -m floodevac.pipeline osm dem sar    # selected steps
    python -m floodevac.pipeline train --force  # re-run a step ignoring caches
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

from floodevac.common.config import Config, load
from floodevac.common.logging import get_logger

log = get_logger(__name__)


def _osm(cfg: Config):
    from floodevac.ingest import osm
    return osm.fetch(cfg)


def _dem(cfg: Config):
    from floodevac.ingest import dem
    return dem.derive_terrain(cfg)


def _sar(cfg: Config):
    from floodevac.ingest import sar_gee
    return sar_gee.fetch(cfg)


def _rain(cfg: Config):
    from floodevac.ingest import imd
    return imd.fetch(cfg)


def _gauges(cfg: Config):
    from floodevac.ingest import cwc
    return cwc.fetch(cfg)


def _layers(cfg: Config):
    from floodevac.ingest import landcover_gee, worldpop
    landcover_gee.fetch(cfg)
    return worldpop.fetch(cfg)


def _shelters(cfg: Config):
    from floodevac.ingest import shelters
    return shelters.fetch(cfg)


def _features(cfg: Config):
    from floodevac.features import build_table
    return build_table.build(cfg)


def _graph(cfg: Config):
    from floodevac.routing import graph
    return graph.build(cfg)


def _train(cfg: Config):
    from floodevac.models import report, train
    out = train.run(cfg)
    report.write_model_card(cfg)
    return out


def _routing(cfg: Config):
    from floodevac.routing import replay
    return replay.run(cfg)


STEPS: dict[str, Callable[[Config], object]] = {
    "osm": _osm, "dem": _dem, "layers": _layers, "sar": _sar, "rain": _rain, "gauges": _gauges,
    "shelters": _shelters, "features": _features, "graph": _graph, "train": _train, "replay": _routing,
}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("steps", nargs="+", choices=[*STEPS, "all"])
    p.add_argument("--force", action="store_true", help="ignore cached outputs for the selected steps")
    args = p.parse_args(argv)
    cfg = load().with_force(args.force)
    steps = list(STEPS) if "all" in args.steps else args.steps
    for name in steps:
        t0 = time.time()
        log.info("== %s ==", name)
        out = STEPS[name](cfg)
        log.info("== %s done in %.0fs -> %s", name, time.time() - t0, out)


if __name__ == "__main__":
    main()
