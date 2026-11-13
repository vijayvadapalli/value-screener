"""Keeps each run's key figures so a re-run can show the previous figure in brackets (Valuation Playbook)."""
from __future__ import annotations

import json
from pathlib import Path

KEYS = ("price", "v_low", "v_high", "implied_growth", "margin_of_safety", "signal", "zone")


def previous(path: Path, as_of) -> dict:
    """{ticker: figures} from the latest run dated before `as_of`, or {}."""
    if not path.exists():
        return {}
    try:
        runs = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    earlier = sorted(d for d in runs if d < as_of.isoformat())
    return runs[earlier[-1]] | {"_date": earlier[-1]} if earlier else {}


def save(path: Path, as_of, results: dict):
    try:
        runs = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        runs = {}
    runs[as_of.isoformat()] = {t: {k: r.get(k) for k in KEYS if isinstance(r.get(k), (int, float, str, type(None)))}
                               for t, r in results.items()}
    path.write_text(json.dumps(runs, indent=1, sort_keys=True))
