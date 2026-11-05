"""Runs the models and rules over a set of companies."""
from __future__ import annotations

from .models import value_company, etf_lookthrough
from .rules import stale_check, zone


def run(companies: dict, tickers: list[str], cfg: dict) -> dict:
    results = {}
    for t in tickers:
        c = companies[t]
        r = value_company(c, cfg)
        r.update(stale_check(c, cfg))
        r.update(zone(r, c, cfg))
        r["assumptions"], r["notes"], r["sources"] = c.get("assumptions", []), c.get("notes", []), c.get("sources", [])
        results[t] = r
    return results


def ranked(results: dict) -> tuple[list[dict], list[dict]]:
    """Metals/energy ranked by cautious coverage (value ÷ price, high first); growth by implied growth (low first)."""
    vals = [r for r in results.values() if r["model"] != "growth"]
    grow = [r for r in results.values() if r["model"] == "growth"]
    vals.sort(key=lambda r: -r["coverage_lo"])
    grow.sort(key=lambda r: (r["implied_growth"] is None, r["implied_growth"] if r["implied_growth"] is not None else 0))
    for i, r in enumerate(vals): r["rank"] = i + 1
    for i, r in enumerate(grow): r["rank"] = i + 1
    return vals, grow


__all__ = ["run", "ranked", "etf_lookthrough"]
