"""Price cases: the value per share at fixed metal prices (config `price_cases:`), for lists that set `price_cases: true`.

Each case re-runs the company's own model (models.value_company) with one metal moved to the case price and every other
metal left at spot. Nothing is forecast: the trailing, reported-period value stays the headline, and a case only shows
what the value would be if that metal price held. Shown on the company page as "assumption, not reported".

  producers and royalties  value at the cautious / fair multiple and at the sell multiple (12x / 15x / 25x), for each
                           metal that is at least MIN_SHARE of the company's metal revenue at spot
  developers               NAV per share from the NPV curve (and any metal held) at the case price
  physical holders         NAV per share at the case price

Pure functions:  cases(c, r, cfg) → list of {metal, kind, rows: [{price, spot, values}]} or []
"""
from __future__ import annotations

from .models import value_company

MIN_SHARE = 0.15     # a by-product below this share of metal revenue at spot gets no table of its own


def metals_for(c: dict, r: dict, cfg: dict) -> list[str]:
    """The metals whose price cases matter for this company, biggest first."""
    known = cfg.get("price_cases") or {}
    if r["model"] == "producer":
        if (r.get("oe") or 0) <= 0:
            return []
        if c.get("price_sensitivity"):      # the company's own realised-price table (models.curve_delta_ps)
            metal = c["price_sensitivity"]["metal"]
            return [metal] if metal in known else []
        terms = [t for t in r.get("terms", []) if t["sens"] > 0]
        total = sum(t["sens"] * t["spot"] for t in terms)
        if not total:
            return []
        terms.sort(key=lambda t: -t["sens"] * t["spot"])
        return [t["metal"] for t in terms if t["metal"] in known and t["sens"] * t["spot"] / total >= MIN_SHARE]
    if r["model"] == "developer":
        metal = c["npv_curve"]["metal"]
    elif r["model"] == "physical":
        metal = c["holdings"]["metal"]
    else:
        return []
    return [metal] if metal in known else []


def cases(c: dict, r: dict, cfg: dict) -> list[dict]:
    out = []
    for metal in metals_for(c, r, cfg):
        spot = cfg["spot"][metal]
        prices = sorted(set(cfg["price_cases"][metal]) | {spot})
        rows = []
        for p in prices:
            v = value_company(c, cfg, {metal: p})
            values = ((v["v_low"], v["v_high"], v["v_sell"]) if r["model"] == "producer" else (v["nav"],))
            rows.append(dict(price=p, spot=p == spot, values=values))
        out.append(dict(metal=metal, kind="multiples" if r["model"] == "producer" else "nav", rows=rows, note=note(c)))
    return out


def note(c: dict) -> str:
    """How the case moves earnings, when it is not ounces / pounds × price."""
    s = c.get("price_sensitivity")
    if not s:
        return ""
    return (f"Realised price from the company's own table of expected realised price at each spot price ({s['year']} row), "
            f"on {s['sales_mlb']:g}m lb a year sold, less {s.get('purchases_mlb', 0):g}m lb bought at spot, after "
            f"{s.get('royalty', 0) * 100:.1f}% royalty and {s.get('tax_rate', 0) * 100:.0f}% tax. The contracts lag the "
            f"spot price and carry floors and ceilings, so the value does not move in step with the metal.")


def attach(results: dict, companies: dict, cfg: dict) -> None:
    """Adds r["price_cases"] to every valued company in `results`."""
    for t, r in results.items():
        r["price_cases"] = cases(companies[t], r, cfg)
