"""Project-wide logger factory."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        root = logging.getLogger("floodevac")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False  # waitress configures the root logger too; avoid double lines
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("floodevac") else f"floodevac.{name}")
