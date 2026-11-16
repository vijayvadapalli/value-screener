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


def judge(x: dict, s: dict) -> dict:
    """The screen's verdict from plain inputs, the same for every market. `x` holds: ticker, name, price, price_ccy,
    eps (the EPS the valuation uses), nc (net cash per share), pe (price minus net cash ÷ eps), eps_ttm (reported),
    eps_annual (yearly EPS, oldest first, comparable across splits), growth_needed, cash_conversion, stale, bad_loans,
    history_break, cyclical, signal, action, owners (promoters or insiders, a fraction, or None), flags (already found).
    `s`: the thresholds (config growth_screen / us_growth_screen)."""
    c5, c3, positive = eps_growth(x.get("eps_annual"), s["years"])
    growth = min(c5, c3) if c5 is not None and c3 is not None else None
    price, ttm = x["price"], x.get("eps_ttm")
    ret, assumed = expected_return(x.get("eps"), x.get("nc"), price, growth, s)
    flags = list(x.get("flags") or [])

    guards = []
    cc = x.get("cash_conversion")
    if cc is not None and cc < s["min_cash_conversion"]:
        guards.append(f"cash conversion {cc*100:.0f}%")
    if x.get("history_break"):
        guards.append("history not comparable")
    if x.get("stale"):
        guards.append("stale results")
    if x.get("bad_loans"):
        guards.append("bad-loan warning")
    if not positive:
        guards.append("a loss year in the window" if c5 is not None or c3 is not None else "not enough history")

    pe = x.get("pe")
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
    if x.get("cyclical"):
        flags.append("cyclical")
    if x["ticker"] in set(s.get("state_owned") or []):
        flags.append("state-owned")
    return {"ticker": x["ticker"], "name": x["name"], "tier": tier, "missed": missed, "guards": guards, "flags": flags,
            "pe": pe, "pe_trailing": price / ttm if ttm and ttm > 0 else None, "eps_cagr_5y": c5, "eps_cagr_3y": c3,
            "every_year_positive": positive, "growth_needed": x.get("growth_needed"), "assumed_growth": assumed,
            "expected_return": ret, "promoters": x.get("owners"), "signal": x["signal"], "action": x["action"],
            "price": price, "price_ccy": x["price_ccy"], "checks": checks}


def evaluate(r: dict, c: dict, cfg: dict, extra: str | None = None) -> dict:
    """One Indian company: its valuation result `r` (engine.run) and company file `c` (the Screener figures)."""
    s = cfg["growth_screen"]
    v = c.get("v2") or {}
    quarters = [q for q in (v.get("eps_quarters") or [])[-4:] if q is not None]
    promoters, flags = promoter_flags(v.get("shareholding"), s)
    x = {"ticker": r["ticker"], "name": r["name"], "price": r["price"], "price_ccy": r["price_ccy"], "eps": r.get("oe"),
         "nc": r.get("nc"), "pe": r.get("pe"),
         "eps_ttm": sum(quarters) if len(quarters) == 4 else (r.get("v2") or {}).get("ttm"),   # reported, before one-offs are removed
         "eps_annual": v.get("eps_annual"), "growth_needed": r.get("implied_growth"), "cash_conversion": r.get("cash_conversion"),
         "stale": r.get("stale"), "bad_loans": bool((r.get("asset_quality") or {}).get("flags")),
         "history_break": v.get("history_not_comparable"),
         "cyclical": (r.get("v2") or {}).get("kind") == "cyclical" or bool(r.get("cyclical")),
         "signal": r["signal"], "action": r["action"], "owners": promoters, "flags": flags}
    row = judge(x, s)
    if extra:
        row["flags"].append(extra)
    return row


def evaluate_us(r: dict, cfg: dict) -> dict:
    """One US company from the US screen (us_screen.py): SEC figures, the EPS history split-adjusted. Insider
    ownership, when known, is shown in the owners column but never flagged – US companies have no promoter group."""
    s = cfg["us_growth_screen"]
    eps, nc = r.get("eps"), r.get("nc") or 0.0
    x = {"ticker": r["ticker"], "name": r["name"], "price": r["price"], "price_ccy": "USD", "eps": eps, "nc": nc,
         "pe": (r["price"] - nc) / eps if eps and eps > 0 else None,
         "eps_ttm": r["price"] / r["pe"] if r.get("pe") else None,
         "eps_annual": r.get("eps_annual"), "growth_needed": r.get("implied_growth"), "cash_conversion": r.get("cash_conversion"),
         "stale": False, "bad_loans": bool((r.get("asset_quality") or {}).get("flags")), "history_break": None,
         "cyclical": bool(r.get("cyclical")), "signal": r["signal"], "action": r["action"],
         "owners": r.get("insiders"), "flags": []}
    return judge(x, s)


def rows_us(us_rows: list[dict], cfg: dict) -> list[dict]:
    """Screen rows for the US screen's valued companies (not the grey 'not valued' or 'data check' ones), best first."""
    return sorted((evaluate_us(r, cfg) for r in us_rows if r.get("signal") in ("green", "blue", "red") and r.get("eps") is not None),
                  key=sort_key)


def sort_key(row):
    ret = row["expected_return"]
    return (TIERS.index(row["tier"]), -(ret if ret is not None else -9))


def rows(results: dict, companies: dict, cfg: dict, extras: dict | None = None) -> list[dict]:
    """Screen rows for every valued company, shortlist first, then near misses, each by expected return."""
    extras = extras or {}
    return sorted((evaluate(r, companies[t], cfg, extras.get(t)) for t, r in results.items() if r["model"] == "growth"),
                  key=sort_key)
