"""The growth-at-a-value-price screen, for lists with `screen: growth` (the Nifty Midcap 150). On top of the usual
valuation and signal, a company is judged on four things (thresholds in config.yaml, growth_screen):

  P/E           price minus net cash, ÷ the EPS the valuation uses (one-offs removed, cyclicals averaged) ≤ 15
  growth        EPS growth ≥ 20% a year over BOTH 5 and 3 years, EPS positive in every one of those years
                (both, because a 5-year window that starts in a bad year – 2021 – flatters the rate)
  5-year hold   expected return a year if growth runs at half the past rate (at most 15%) and the shares are
                sold at 15x after 5 years ≥ 12% (the Indian discount rate)
  guards        cash conversion ≥ 70%, no demerger / one-off history, no bad-loan warning signs, current results

Shortlist = passes everything. Near miss = the guards pass and one thing is short: a P/E of 15–20 (growth met),
growth of 15–20% (P/E met), or P/E and growth met but the return below the bar. The return is not held against a
P/E near miss: bought above 15x and sold at 15x, it falls short almost by definition. Promoter holding below 60%, or falling, is a flag – pledged shares are not in
the data yet (not on Screener's public page). State-owned companies are flagged (their promoter is the government).
Pure functions: no files, no network.

    evaluate(r, c, cfg, extra=None) → one screen row        rows(results, companies, cfg, extras) → rows, best first
"""
from __future__ import annotations

TIERS = ("shortlist", "near miss", "")


def cagr(then, now, years):
    """Yearly growth from `then` to `now`; None unless both are positive."""
    if then is None or now is None or then <= 0 or now <= 0:
        return None
    return (now / then) ** (1 / years) - 1


def eps_growth(eps_annual, years=5):
    """(5-year CAGR, 3-year CAGR, every year positive) from the yearly EPS, oldest first."""
    eps = [x for x in (eps_annual or []) if x is not None]
    if len(eps) < years + 1:
        return None, None, False
    window = eps[-(years + 1):]
    return cagr(window[0], window[-1], years), cagr(eps[-4], eps[-1], 3), all(x > 0 for x in window)


def expected_return(eps, nc, price, growth, s):
    """The return a year over the hold: EPS growing at half the past rate (capped), sold at the exit multiple."""
    if eps is None or eps <= 0 or growth is None or not price:
        return None, None
    assumed = min(max(growth, 0.0) * s["growth_haircut"], s["max_assumed_growth"])
    future = eps * (1 + assumed) ** s["years"] * s["exit_multiple"] + (nc or 0.0)
    return ((future / price) ** (1 / s["years"]) - 1 if future > 0 else None), assumed


def promoter_flags(shareholding, s):
    """Flags from the shareholding pattern: no promoter group, holding below the floor, holding falling over a year."""
    sh = shareholding or {}
    p = [x for x in (sh.get("promoters") or []) if x is not None]
    if not sh:
        return None, ["no shareholding data"]
    if not p:
        return None, ["no promoter group"]
    flags = []
    if p[-1] < s["min_promoter"]:
        flags.append(f"promoters {p[-1]*100:.0f}% (< {s['min_promoter']*100:.0f}%)")
    if len(p) >= 5 and p[-5] - p[-1] > s["promoter_drop"]:
        flags.append(f"promoters down {(p[-5] - p[-1])*100:.1f} pts in a year")
    return p[-1], flags


def evaluate(r: dict, c: dict, cfg: dict, extra: str | None = None) -> dict:
    s = cfg["growth_screen"]
    v = c.get("v2") or {}
    c5, c3, positive = eps_growth(v.get("eps_annual"), s["years"])
    growth = min(c5, c3) if c5 is not None and c3 is not None else None
    price, quarters = r["price"], [x for x in (v.get("eps_quarters") or [])[-4:] if x is not None]
    ttm = sum(quarters) if len(quarters) == 4 else (r.get("v2") or {}).get("ttm")   # reported, before one-offs are removed
    ret, assumed = expected_return(r.get("oe"), r.get("nc"), price, growth, s)
    promoters, flags = promoter_flags(v.get("shareholding"), s)

    guards = []
    cc = r.get("cash_conversion")
    if cc is not None and cc < s["min_cash_conversion"]:
        guards.append(f"cash conversion {cc*100:.0f}%")
    if v.get("history_not_comparable"):
        guards.append("history not comparable")
    if r.get("stale"):
        guards.append("stale results")
    if (r.get("asset_quality") or {}).get("flags"):
        guards.append("bad-loan warning")
    if not positive:
        guards.append("a loss year in the window" if c5 is not None or c3 is not None else "not enough history")

    pe = r.get("pe")
    checks = {"pe": pe is not None and pe <= s["max_pe"],
              "growth": positive and growth is not None and growth >= s["min_eps_cagr"],
              "return": ret is not None and ret >= s["min_return"]}
    missed = [k for k, ok in checks.items() if not ok]
    near_pe = pe is not None and pe <= s["near_max_pe"]
    near_growth = positive and growth is not None and growth >= s["near_min_eps_cagr"]
    if guards:
        tier = ""
    elif not missed:
        tier = "shortlist"
    elif (checks["pe"] and checks["growth"]) or (checks["growth"] and near_pe) or (checks["pe"] and near_growth):
        tier = "near miss"
    else:
        tier = ""
    if (r.get("v2") or {}).get("kind") == "cyclical" or r.get("cyclical"):
        flags.append("cyclical")
    if r["ticker"] in set(s.get("state_owned") or []):
        flags.append("state-owned")
    if extra:
        flags.append(extra)
    return {"ticker": r["ticker"], "name": r["name"], "tier": tier, "missed": missed, "guards": guards, "flags": flags,
            "pe": pe, "pe_trailing": price / ttm if ttm and ttm > 0 else None, "eps_cagr_5y": c5, "eps_cagr_3y": c3,
            "every_year_positive": positive, "growth_needed": r.get("implied_growth"), "assumed_growth": assumed,
            "expected_return": ret, "promoters": promoters, "signal": r["signal"], "action": r["action"],
            "price": price, "price_ccy": r["price_ccy"], "checks": checks}


def sort_key(row):
    ret = row["expected_return"]
    return (TIERS.index(row["tier"]), -(ret if ret is not None else -9))


def rows(results: dict, companies: dict, cfg: dict, extras: dict | None = None) -> list[dict]:
    """Screen rows for every valued company, shortlist first, then near misses, each by expected return."""
    extras = extras or {}
    return sorted((evaluate(r, companies[t], cfg, extras.get(t)) for t, r in results.items() if r["model"] == "growth"),
                  key=sort_key)
