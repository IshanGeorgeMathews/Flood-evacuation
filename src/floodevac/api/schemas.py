"""Response contracts. Each endpoint's payload is checked against a required-key schema in tests and (cheaply) at
runtime in debug mode, so the frontend widgets can rely on the shapes documented in docs/api.md."""

from __future__ import annotations

from typing import Any

SCHEMAS: dict[str, dict[str, Any]] = {
    "status": {"feeds": list, "model_version": str, "mode": str, "live_date": str, "refreshed_at": str,
               "data_source": str, "refresh_minutes": int},
    "risk": {"type": str, "features": list, "meta": dict},
    "route": {"routes": list, "warnings": list, "preset": str, "origin": dict, "data_ts": str},
    "route_item": {"kind": str, "geometry": dict, "eta_s": float, "dist_m": float, "exposure_m": float,
                   "max_p": float, "shelter": (dict, type(None))},
    "shelters": {"type": str, "features": list},
    "gauges": {"gauges": list, "source": str},
    "simulate": {"rain_mm_3d": float, "kpis": dict, "baseline": dict, "delta": dict},
    "explain": {"eid": int, "p": float, "top": list, "road": dict, "base_value_note": str},
    "isochrone": {"type": str, "geometry": (dict, type(None)), "properties": dict},
    "replay_summary": {"days": list, "comparisons": list, "model": str},
    "replay_day": {"date": str, "type": str, "features": list, "stats": dict},
    "stats": {"kpis": dict, "histogram": list, "top_segments": list, "by_class": list},
    "model": {"version": str, "models": dict, "gate": dict, "importance": list},
    "rainfall": {"daily": list, "forecast": list, "upstream_3d": (float, type(None)), "source": str},
    "dams": {"releases": list, "note": str},
    "alerts": {"alerts": list, "generated_at": str},
    "taluks": {"type": str, "features": list},
}


def validate(name: str, payload: dict) -> list[str]:
    """Return a list of problems (empty if the payload satisfies the schema)."""
    problems = []
    for key, typ in SCHEMAS[name].items():
        if key not in payload:
            problems.append(f"{name}: missing '{key}'")
        elif not isinstance(payload[key], typ if isinstance(typ, tuple) else (typ,)) and not (
                typ is float and isinstance(payload[key], int)):
            problems.append(f"{name}: '{key}' is {type(payload[key]).__name__}, expected {typ}")
    return problems
