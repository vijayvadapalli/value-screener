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
    filters(s) → the settings panel's switches at their defaults (config `default_filters`)
    apply_filters(rows, s) → the rows the page shows by default: out-of-list names and cyclicals left out, low
                             promoter holding and government-owned held back from the shortlist (as assets/screen.js)
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
    state_owned = x["ticker"] in set(s.get("state_owned") or [])
    if x.get("cyclical"):
        flags.append("cyclical")
    if state_owned:
        flags.append("state-owned")
    return {"ticker": x["ticker"], "name": x["name"], "tier": tier, "missed": missed, "guards": guards, "flags": flags,
            "pe": pe, "pe_trailing": price / ttm if ttm and ttm > 0 else None, "eps_cagr_5y": c5, "eps_cagr_3y": c3,
            "every_year_positive": positive, "growth_needed": x.get("growth_needed"), "assumed_growth": assumed,
            "expected_return": ret, "promoters": x.get("owners"), "signal": x["signal"], "action": x["action"],
            "price": price, "price_ccy": x["price_ccy"], "checks": checks,
            # for the report's settings panel (assets/screen.js recomputes the tiers in the browser)
            "eps": x.get("eps"), "nc": x.get("nc"), "state_owned": state_owned, "cyclical": bool(x.get("cyclical")),
            "pledged": x.get("pledged"), "extra": None,
            "roe": x.get("roe"), "de": x.get("de"), "financial": bool(x.get("financial")), "quality_year": x.get("quality_year")}


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
         "signal": r["signal"], "action": r["action"], "owners": promoters, "flags": flags,
         "financial": is_financial(c, cfg), **quality_figures(v.get("balance_annual"))}
    row = judge(x, s)
    src = r
    row["quality_src"] = {k: src.get(k) for k in ("pb", "fair_pb", "asset_quality", "cash_conversion", "fcf_ps", "price", "no_growth_multiple")}   # the Quality column (html_report)
    if extra:
        row["flags"].append(extra)
        row["extra"] = extra
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
    row = judge(x, s)
    from .models import dcf_factor  # noqa: PLC0415
    from .us_screen import RATE  # noqa: PLC0415
    src = dict(r, no_growth_multiple=dcf_factor(0.0, cfg, RATE))   # fair P/B = 5-yr ROE × this
    row["quality_src"] = {k: src.get(k) for k in ("pb", "fair_pb", "asset_quality", "cash_conversion", "fcf_ps", "price", "no_growth_multiple")}
    return row


def evaluate_tech(r: dict, us_row: dict | None, cfg: dict) -> dict:
    """A company in the tech list: the report's own valuation (`r`: P/E, growth needed, signal) with the EPS history
    and cash conversion from the SEC figures (`us_row`, the US screen's row for the same ticker; None for foreign
    filers, which then lack the history). The US thresholds apply."""
    s = cfg["us_growth_screen"]
    u = us_row or {}
    x = {"ticker": r["ticker"], "name": r["name"], "price": r["price"], "price_ccy": r["price_ccy"], "eps": r.get("oe"),
         "nc": r.get("nc"), "pe": r.get("pe"), "eps_ttm": r["price"] / u["pe"] if u.get("pe") else None,
         "eps_annual": u.get("eps_annual"), "growth_needed": r.get("implied_growth"),
         "cash_conversion": u.get("cash_conversion"), "stale": r.get("stale"),
         "bad_loans": bool((u.get("asset_quality") or {}).get("flags")), "history_break": None,
         "cyclical": bool(r.get("cyclical")), "signal": r["signal"], "action": r["action"], "owners": u.get("insiders"),
         "flags": [] if us_row else ["no SEC history (foreign filer)"]}
    row = judge(x, s)
    src = dict(r, cash_conversion=u.get("cash_conversion"))
    row["quality_src"] = {k: src.get(k) for k in ("pb", "fair_pb", "asset_quality", "cash_conversion", "fcf_ps", "price", "no_growth_multiple")}
    return row


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


def is_financial(c: dict, cfg: dict) -> bool:
    """Banks, NBFCs and insurers (config nifty_v2.financial_industries) – the quality check treats them separately."""
    return c.get("sector", "") in (cfg.get("nifty_v2") or {}).get("financial_industries", [])


def quality_figures(ba: dict | None, known=lambda label: True) -> dict:
    """ROE and debt to equity from the yearly balance sheet (Screener's balance_annual): the latest year `known(label)`
    allows – every year for today, the years whose results were out on a past date for the backtest. ROE = that year's
    net profit ÷ the average of the opening and closing equity (the closing alone for the first year); debt to equity
    = borrowings ÷ closing equity. None where a figure is missing or equity is not positive."""
    none = {"roe": None, "de": None, "quality_year": None}
    if not ba or not ba.get("years"):
        return none
    idx = [i for i, y in enumerate(ba["years"]) if known(y)]
    if not idx:
        return none
    i = idx[-1]
    eq, prev = ba["equity"][i], ba["equity"][i - 1] if i else None
    profit, borrow = ba["net_profit"][i], ba["borrowings"][i]
    avg = (eq + prev) / 2 if eq is not None and prev is not None and prev > 0 else eq
    return {"roe": profit / avg if profit is not None and avg and avg > 0 else None,
            "de": borrow / eq if borrow is not None and eq and eq > 0 else None, "quality_year": ba["years"][i]}


def quality(s: dict) -> dict:
    """The quality check's settings: min ROE, min ROE for financials, max debt to equity (None: no limit) and whether
    financials are treated separately (their own ROE bar, no debt limit – a lender's borrowings are its business).
    Off at the Midcap 150 defaults (0, 0, None), so Dr. Gupta's screen stays his five rules."""
    return {"roe": s.get("min_roe") or 0.0, "roe_fin": s.get("min_roe_financials") or 0.0, "de": s.get("max_debt_equity"),
            "fin": bool(s.get("financials_separate", True))}


def quality_on(q: dict) -> bool:
    return q["roe"] > 0 or q["roe_fin"] > 0 or q["de"] is not None


def quality_guards(row: dict, q: dict) -> list[str]:
    """What the quality check holds against a row (screen.js qualityGuards writes the same)."""
    if not quality_on(q):
        return []
    fin = q["fin"] and row.get("financial")
    need, roe, de, out = (q["roe_fin"] if fin else q["roe"]), row.get("roe"), row.get("de"), []
    if need > 0 and (roe is None or roe < need):
        out.append("no ROE figures" if roe is None else f"ROE {roe*100:.0f}% (< {need*100:.0f}%)")
    if q["de"] is not None and not fin:
        if de is None:
            out.append("no debt figures")
        elif de > q["de"]:
            out.append(f"debt/equity {de:.1f} (> {q['de']:.1f})")
    return out


def promoter_rule(s: dict, rows_: list[dict] | None = None) -> bool:
    """Whether the list has a promoter rule at all: a minimum above 0 (the Nifty 50 sets 0) and, given the screen's rows,
    a holding in its files. Without one the rule is not listed, counted or offered in the panel."""
    return s.get("min_promoter", 0) > 0 and (not rows_ or any(r.get("promoters") is not None for r in rows_))


FILTERS = ("prule", "psu", "mid", "cyc")   # promoter rule, no government-owned, the list only (no extras), no cyclicals


def filters(s: dict, rows_: list[dict] | None = None) -> dict:
    """The settings panel's four switches at their defaults (`default_filters` in the screen's config; off when absent).
    With the screen's `rows_`, a list with no promoter holding at all (the Nifty 50 files have none) starts with the
    promoter rule off – it would otherwise leave out every company."""
    d = s.get("default_filters") or {}
    f = {k: bool(d.get(k)) for k in FILTERS}
    if not promoter_rule(s, rows_):
        f["prule"] = False
    return f


def in_universe(row: dict, f: dict) -> bool:
    """Midcap 150 only leaves out the names added by hand (`extra`); excluding cyclicals leaves them out entirely."""
    return not (f["mid"] and row.get("extra")) and not (f["cyc"] and row.get("cyclical"))


def filter_guards(row: dict, f: dict, min_promoter: float, known_only: bool = False) -> list[str]:
    """What the promoter and government-owned rules hold against a row – screen.js judgeRow writes the same. With
    `known_only` (the backtest) an unknown holding is not held against it."""
    out, p = [], row.get("promoters")
    if f["prule"] and not (known_only and p is None) and (p is None or p < min_promoter):
        out.append("no promoter holding" if p is None else f"promoters {p*100:.0f}% (< {min_promoter*100:.0f}%)")
    if f["psu"] and row.get("state_owned"):
        out.append("government-owned")
    return out


def apply_filters(rows_: list[dict], s: dict, f: dict | None = None) -> list[dict]:
    """The rows as the page shows them at the panel's defaults: the universe narrowed, a row the promoter or
    government-owned rule holds back loses its tier (the reason joins its guards), best first again. The rows
    themselves are not changed – the page's panel still needs them as they were."""
    f = f or filters(s, rows_)
    out = []   # the quality check (quality()) applies here too: off unless the list sets it
    for r in rows_:
        if not in_universe(r, f):
            continue
        extra = quality_guards(r, quality(s)) + filter_guards(r, f, s.get("min_promoter", 0.0))
        out.append(dict(r, guards=r["guards"] + extra, tier="") if extra else r)
    return sorted(out, key=sort_key)
