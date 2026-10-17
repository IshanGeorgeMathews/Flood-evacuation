"""Configuration loading: YAML files in configs/ plus environment variables from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(os.environ.get("FLOODEVAC_ROOT", Path(__file__).resolve().parents[3]))


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    configs: Path = ROOT / "configs"
    raw: Path = ROOT / "data" / "raw"
    interim: Path = ROOT / "data" / "interim"
    processed: Path = ROOT / "data" / "processed"
    models: Path = ROOT / "models"
    docs: Path = ROOT / "docs"
    fixtures: Path = ROOT / "tests" / "fixtures"

    def ensure(self) -> "Paths":
        for p in (self.raw, self.interim, self.processed, self.models):
            p.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class Config:
    area: dict[str, Any]
    model: dict[str, Any]
    routing: dict[str, Any]
    refresh: dict[str, Any]
    paths: Paths = field(default_factory=Paths)
    ee_project: str | None = None
    force: bool = False

    def with_force(self, force: bool) -> "Config":
        return Config(self.area, self.model, self.routing, self.refresh, self.paths, self.ee_project, force)


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load() -> Config:
    """Load all configs once per process."""
    load_dotenv(ROOT / ".env")
    paths = Paths().ensure()
    refresh = _read_yaml(paths.configs / "refresh.yaml")
    if os.environ.get("REFRESH_MINUTES"):
        refresh["interval_minutes"] = int(os.environ["REFRESH_MINUTES"])
    return Config(
        area=_read_yaml(paths.configs / "area.yaml"),
        model=_read_yaml(paths.configs / "model.yaml"),
        routing=_read_yaml(paths.configs / "routing.yaml"),
        refresh=refresh,
        paths=paths,
        ee_project=os.environ.get("EE_PROJECT") or None,
    )
