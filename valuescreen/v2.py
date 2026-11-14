"""Nifty v2 rules (Valuation Playbook): which earnings per share the growth model values.

A company file opts in with a `v2:` block, usually written by tools/fetch_screener.py:

    v2:
      kind: normal | cyclical | financial      # optional; otherwise from the industry lists in config.yaml
      eps_quarters: [8 quarterly EPS, oldest first]   # attributable to shareholders (minorities excluded)
      eps_annual:   [up to 10 yearly EPS, oldest first]
      profit_annual: [...]  cfo_annual: [...]  # net profit and operating cash flow, same years, for cash conversion
      book_value_ps: 57.0
      roe_5y: 0.32                             # average return on equity over 5 years, as a fraction
      asset_quality: {quarters, gross_npa_pct, net_npa_pct, loans_cr, loans_basis}   # lenders; see asset_quality.py
      flags: [conglomerate, insurer]           # optional, also set from config.yaml lists
      history_not_comparable: "why"            # optional: past years are a different company (demerger) or hold a
                                               # one-off gain, so no 5-year average; the profit-vs-price row is n/m

Hand-set keys (kind, flags, history_not_comparable, eps_currency) survive a re-fetch by tools/fetch_screener.py.

Rules:
- Last 12 months = the latest four quarters, after removing a one-off quarter: one that is more than 2x the median of
  the other seven AND more than 1.6x its neighbours is replaced by its neighbours' average.
- Cyclicals (oil & gas, metals, cement, power, autos, airlines): average of the 12-month EPS and the 5-year average EPS.
- Financials: average of the 12-month EPS and book value x 5-year ROE. No net-cash adjustment. For lenders, book value
  is first cut by the bad loans not yet provided for (net NPA), and NPA warning signs cap the signal at blue.
- Cash conversion = operating cash flow / net profit over 5 years. Below 70% caps the signal at blue. Not used for
  financials, whose operating cash flow includes deposits and loans.
"""
from __future__ import annotations

from statistics import median

from . import asset_quality


def clean_quarters(q, median_x=2.0, neighbour_x=1.6):
    """Returns (cleaned list, [(index, old, new), ...]) for one-off quarters replaced by their neighbours' average."""
    q = [float(x) for x in q]
    out, changes = list(q), []
    if len(q) < 3:
        return out, changes
    for i, x in enumerate(q):
        others = q[:i] + q[i + 1:]
        med = median(others)
        nbrs = [q[j] for j in (i - 1, i + 1) if 0 <= j < len(q)]
        if med <= 0 or not nbrs or max(nbrs) <= 0:
            continue
        if x > median_x * med and x > neighbour_x * max(nbrs):
            new = sum(nbrs) / len(nbrs)
            out[i] = new
            changes.append((i, x, new))
    return out, changes


def kind_of(c, cfg):
    v = c.get("v2", {})
    if v.get("kind"):
        return v["kind"]
    rules = cfg.get("nifty_v2", {})
    sector, t = c.get("sector", ""), c["ticker"].upper()
    if sector in rules.get("financial_industries", []):
        return "financial"
    if sector in rules.get("cyclical_industries", []) or t in rules.get("cyclical_tickers", []):
        return "cyclical"
    return "normal"


def flags_of(c, cfg):
    rules = cfg.get("nifty_v2", {})
    t = c["ticker"].upper()
    flags = list(c.get("v2", {}).get("flags", []))
    if t in rules.get("conglomerates", []) and "conglomerate" not in flags:
        flags.append("conglomerate")
    if t in rules.get("insurers", []) and "insurer" not in flags:
        flags.append("insurer")
    return flags


def cash_conversion(cfo, profit, years=5):
    pairs = [(c, p) for c, p in zip(cfo or [], profit or []) if c is not None and p is not None]
    cfo, profit = [c for c, _ in pairs][-years:], [p for _, p in pairs][-years:]
    n = min(len(cfo), len(profit))
    if n == 0:
        return None
    p = sum(profit[-n:])
    return sum(cfo[-n:]) / p if p > 0 else None


def base_eps(c, cfg):
    """The EPS the growth model values, with the working shown. Returns a dict."""
    v = c["v2"]
    rules = cfg.get("nifty_v2", {})
    kind = kind_of(c, cfg)
    out = {"kind": kind, "flags": flags_of(c, cfg), "one_offs": []}
    q = v.get("eps_quarters") or []
    if len(q) >= 4:
        cleaned, changes = clean_quarters(q[-8:], rules.get("one_off_median_x", 2.0), rules.get("one_off_neighbour_x", 1.6))
        ttm = sum(cleaned[-4:])
        out["one_offs"] = [(i, old, new) for i, old, new in changes if i >= len(cleaned) - 4]  # the ones inside the 12 months
        out["quarters_cleaned"] = cleaned
    elif v.get("eps_ttm") is not None:
        ttm = float(v["eps_ttm"])
    else:
        raise ValueError(f"{c['ticker']}: v2 needs eps_quarters (8 quarters) or eps_ttm")
    out["ttm"] = ttm
    annual = [float(x) for x in v.get("eps_annual", []) if x is not None]
    avg5 = sum(annual[-5:]) / len(annual[-5:]) if annual else None
    broken = v.get("history_not_comparable")
    if broken:   # e.g. a demerger: the past years belong to a different company, or hold a one-off gain
        avg5 = None
        out["history_not_comparable"] = broken
    out["eps_5y_avg"] = avg5
    if kind == "cyclical" and broken:
        out["eps"] = ttm
        out["how"] = f"cyclical, but the 5-year average is not used ({broken}): 12-month EPS {ttm:,.2f}"
    elif kind == "cyclical" and avg5 is not None:
        out["eps"] = (ttm + avg5) / 2
        out["how"] = f"cyclical: average of 12-month EPS {ttm:,.2f} and 5-year average {avg5:,.2f}"
    elif kind == "financial" and v.get("book_value_ps") and v.get("roe_5y") is not None:
        aq = asset_quality.india(v.get("asset_quality"), c.get("shares_m"), cfg)
        bad = (aq or {}).get("bad_loans_ps") or 0.0
        book = v["book_value_ps"] - bad
        norm = book * v["roe_5y"]
        out.update(asset_quality=aq, book_value_ps=v["book_value_ps"], adjusted_book_ps=book, normal_eps=norm, eps=(ttm + norm) / 2)
        book_text = (f"adjusted book {book:,.2f} (book {v['book_value_ps']:,.2f} − bad loans not provided for {bad:,.2f})"
                     if bad else f"book value {book:,.2f}")
        out["how"] = f"financial: average of 12-month EPS {ttm:,.2f} and {book_text} × 5-year ROE {v['roe_5y']*100:.1f}% = {norm:,.2f}"
    else:
        out["eps"] = ttm
        out["how"] = f"12-month EPS {ttm:,.2f}"
    # A bank's or insurer's operating cash flow mixes in deposits and loans, so it says nothing about earnings quality;
    # financials are checked on price-to-book instead.
    out["cash_conversion"] = None if kind == "financial" else cash_conversion(v.get("cfo_annual"), v.get("profit_annual"))
    return out
