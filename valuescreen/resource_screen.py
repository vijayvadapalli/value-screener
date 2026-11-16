"""The resource version of the growth-at-a-value-price screen, for lists with `screen: resource` (core, oil, miners).
A miner's profit follows the metal price, so a plain P/E and EPS-growth screen would mostly measure gold. Instead
(thresholds in config.yaml, resource_screen):

  value     price ≤ fair value – 15x owner earnings at today's spot (13x cash flow for oil): the miner's P/E-15
  stress    price ≤ that fair value with the metal 20% lower (when the model knows its sensitivity to the metal)
  growth    volume growth ≥ 5% a year: revenue growth over about 3 years with the metal-price change taken out
            (approximate – revenue is in the company's currency, and acquisitions count as growth)
  5 years   return a year with earnings flat at today's spot, sold at fair value after 5 years ≥ 10%
  guards    positive owner earnings, AISC ≤ 60% of spot where known, current results

Developers and physical holders keep their NAV rules: shortlist at the buy level, near miss up to 1.0× NAV.
Pure functions; the metal-price growth comes in as a function (cli.py reads it from the price history).

    evaluate(r, profit, metal_growth, cfg) → one row          rows(results, profits, metal_growth, cfg) → rows, best first
"""
from __future__ import annotations

TIERS = ("shortlist", "near miss", "")
NAV_MODELS = ("developer", "physical", "leases")


def metal_of(r: dict) -> str | None:
    return "oil" if r["model"] == "cashflow" else r.get("primary_metal")


def volume_growth(profit: dict | None, metal_growth) -> tuple:
    """(revenue growth, metal-price growth, volume growth = (1 + revenue) ÷ (1 + metal) − 1, years) – None where unknown."""
    rec = profit or {}
    years, then, now = rec.get("years"), rec.get("sales_then"), rec.get("sales_now")
    if not years or not then or not now or then <= 0 or now <= 0:
        return None, None, None, years
    sales = (now / then) ** (1 / years) - 1
    metal = metal_growth(years)
    return sales, metal, (None if metal is None else (1 + sales) / (1 + metal) - 1), years


def evaluate(r: dict, profit: dict | None, metal_growth, cfg: dict) -> dict:
    """One company: `r` its valuation result, `profit` its profit-vs-price figures (revenue then and now),
    `metal_growth(years)` the yearly change of its metal's price over that many years (None if unknown)."""
    s = cfg["resource_screen"]
    row = {"ticker": r["ticker"], "name": r["name"], "model": r["model"], "signal": r["signal"], "action": r["action"],
           "price": r["price"], "price_ccy": r["price_ccy"], "metal": metal_of(r), "guards": [], "flags": [], "missed": [],
           "fair": None, "stress_value": None, "sales_growth": None, "metal_growth": None, "volume_growth": None,
           "expected_return": None, "pnav": r.get("pnav"), "tier": ""}
    if r["model"] in NAV_MODELS:
        z = r.get("zone", "")
        row["tier"] = "shortlist" if r.get("band") == "BUY" else "near miss" if r.get("band") == "WATCH" else ""
        row["fair"] = r.get("nav") or r.get("v_low")
        if r.get("stale"):
            row["guards"].append("stale results")
            row["tier"] = ""
        row["flags"].append(f"valued on NAV ({z})")
        return row
    if r["model"] not in ("producer", "cashflow"):
        return dict(row, guards=["not valued"])
    oe, nc, hi = r.get("oe") or 0.0, r.get("nc") or 0.0, r.get("mult_hi") or s["fair_multiple"]
    fair = r.get("v_high")
    row["fair"] = fair
    if oe <= 0:
        row["guards"].append("no positive owner earnings")
    if r.get("cost_ratio") is not None and r["cost_ratio"] > s["max_cost_ratio"]:
        row["guards"].append(f"AISC {r['cost_ratio']*100:.0f}% of spot")
    if r.get("stale"):
        row["guards"].append("stale results")
    exp = r.get("exp") or 0.0
    stress = (oe - s["metal_drop"] * exp) * hi + nc if exp and oe > 0 else None
    row["stress_value"] = stress
    if stress is None:
        row["flags"].append("metal stress not tested (no sensitivity in the model)")
    sales, metal, volume, years = volume_growth(profit, metal_growth)
    row.update(sales_growth=sales, metal_growth=metal, volume_growth=volume, growth_years=years)
    future = oe * hi + nc
    ret = (future / r["price"]) ** (1 / s["years"]) - 1 if oe > 0 and future > 0 and r["price"] > 0 else None
    row["expected_return"] = ret
    checks = {"value": fair is not None and r["price"] <= fair,
              "stress": stress is None or r["price"] <= stress,
              "growth": volume is not None and volume >= s["min_volume_growth"],
              "return": ret is not None and ret >= s["min_return"]}
    row["checks"] = checks
    row["missed"] = [k for k, ok in checks.items() if not ok]
    if not row["guards"]:
        if not row["missed"]:
            row["tier"] = "shortlist"
        elif checks["value"] and len(row["missed"]) == 1:
            row["tier"] = "near miss"
    if r.get("tier"):
        row["flags"].append(f"tier {r['tier']}")
    return row


def sort_key(row):
    ret = row.get("expected_return")
    return (TIERS.index(row["tier"]), -(ret if ret is not None else -9))


def rows(results: dict, profits: dict, metal_growth_for, cfg: dict) -> list[dict]:
    """Rows for every valued company in the list; `metal_growth_for(metal)` gives that metal's metal_growth function."""
    out = []
    for t, r in results.items():
        if r["model"] == "liquid":
            continue
        metal = metal_of(r)
        out.append(evaluate(r, profits.get(t), metal_growth_for(metal) if metal else (lambda years: None), cfg))
    return sorted(out, key=sort_key)
