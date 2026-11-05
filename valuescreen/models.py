"""Valuation models. Pure functions: company dict + config + spot prices -> result dict.

All per-share outputs are in the company's *price* currency, so value and price are always comparable.
Units convention: money in millions of the stated currency; ounces in Moz, pounds in Mlb, per period;
spot and realised metal prices in USD per oz / lb.
"""
from __future__ import annotations

from scipy.optimize import brentq

from .loader import fx


# ---------------------------------------------------------------- helpers
def _pc(c):
    return c["price"]["currency"]


def net_cash_ps(c, cfg) -> float:
    """Net cash per share in price currency. balance may be a dict {cash, debt, net_cash, currency} or a list of items."""
    b = c.get("balance", {})
    pc, sh = _pc(c), c.get("shares_m_balance", c.get("shares_m"))
    if not sh:
        return 0.0
    total = 0.0
    if isinstance(b, list):
        for it in b:
            total += it["amount"] * fx(cfg, it.get("currency", c["currency"]), pc)
    else:
        ccy = b.get("currency", c["currency"])
        amt = b["net_cash"] if "net_cash" in b else b.get("cash", 0.0) - b.get("debt", 0.0)
        total = amt * fx(cfg, ccy, pc)
    return total / sh


def owner_earnings_period(e: dict) -> float:
    """Owner earnings for one period, in reporting currency $m."""
    if "owner_earnings" in e:
        base = e["owner_earnings"]
    elif "cfo_ex_wc" in e:
        base = e["cfo_ex_wc"] - e.get("capex", 0.0)
    else:
        ni = e["adj_net_income"] if "adj_net_income" in e else e["net_income"]
        base = ni + e.get("addbacks", 0.0) + e.get("da", 0.0) - e.get("sustaining_capex", 0.0)
    for a in e.get("adjustments", []):
        base += a["amount"] * (1 - a.get("tax_rate", 0.0))
    return base


def owner_earnings_ps(c, cfg, block="earnings") -> float:
    """Annual owner earnings per share at the period's own prices, price currency."""
    e = c[block]
    per_year = e.get("per_year", c["period"]["per_year"])
    pc = _pc(c)
    if "eps_per_period" in e:
        return e["eps_per_period"] * per_year * e.get("adr_ratio", 1.0) * fx(cfg, e.get("eps_currency", c["currency"]), pc)
    shares = e.get("shares_m", c["shares_m"])
    return owner_earnings_period(e) * per_year / shares * fx(cfg, c["currency"], pc)


def _metal_terms(c, cfg, spot):
    """Yields (metal, after-tax $/share per $1 of metal price, realised, include_in_scenarios)."""
    if not c.get("metals"):
        return
    per_year = c["period"]["per_year"]
    tax = c.get("tax_rate", 0.0)
    conv = fx(cfg, "USD", _pc(c))
    for m in c.get("metals", []):
        roy = m.get("royalty", c.get("royalty_rate", 0.0))
        sens = m["units"] * per_year * (1 - roy) * (1 - tax) / c["shares_m"] * conv
        yield m["metal"], sens, m["realised"], m["metal"] in cfg["scenario_metals"]


def interp(points, x):
    """Linear interpolation with linear extrapolation beyond the end points. Returns (y, extrapolated?)."""
    pts = sorted(points)
    if len(pts) == 1:
        return pts[0][1], x != pts[0][0]
    if x <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif x >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                break
    y = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return y, not (pts[0][0] <= x <= pts[-1][0])


def dcf_factor(g, cfg):
    d = cfg["growth_dcf"]
    q = (1 + g) / (1 + d["discount_rate"])
    return sum(q ** t for t in range(1, d["years"] + 1)) + d["exit_multiple"] * q ** d["years"]


# ---------------------------------------------------------------- models
def value_producer(c, cfg, spot):
    """Producer, streamer, royalty and cash-flow (oil) models."""
    model = c["model"]
    lo, hi = c.get("multiples", cfg["multiples"]["cashflow" if model == "cashflow" else "producer"])
    sell_m = c.get("sell_multiple", cfg["multiples"]["sell"])
    block = "earnings_normalised" if c.get("rank_on_normalised") and "earnings_normalised" in c else "earnings"
    oe_rep = owner_earnings_ps(c, cfg, block)
    terms = list(_metal_terms(c, cfg, spot)) if block == "earnings" else []
    delta = sum(s * (spot[m] - r) for m, s, r, _ in terms)
    oe = oe_rep + delta
    exp = sum(s * spot[m] for m, s, _, inc in terms if inc)          # value of a 100% move in scenario metals
    nc = net_cash_ps(c, cfg)
    price = c["price"]["value"]
    r = dict(oe_rep=oe_rep, oe=oe, nc=nc, mult_lo=lo, mult_hi=hi, v_low=oe * lo + nc, v_high=oe * hi + nc,
             v_sell=oe * sell_m + nc, sell_multiple=sell_m, exp=exp, basis=block)
    r["pe"] = (price - nc) / oe if oe > 0 else None
    if terms:
        m0, s0, _, _ = terms[0]
        r["primary_metal"] = c.get("primary_metal", m0)
        s0 = next(s for m, s, _, _ in terms if m == r["primary_metal"])
        r["implied_metal_lo"] = spot[r["primary_metal"]] + ((price - nc) / lo - oe) / s0 if s0 else None
        r["implied_metal_hi"] = spot[r["primary_metal"]] + ((price - nc) / hi - oe) / s0 if s0 else None
        r["sens_per_unit"] = s0
    if block != "earnings":
        r["oe_reported_quarter"] = owner_earnings_ps(c, cfg, "earnings")
    cost = next((m.get("aisc") for m in c.get("metals", []) if m.get("aisc")), None)
    if cost:
        r["cost_ratio"] = cost / spot[c.get("primary_metal", c["metals"][0]["metal"])]
    r["scenarios"] = [((oe + s * exp) * lo + nc, (oe + s * exp) * hi + nc) for s in cfg["metal_scenarios"]]
    r["coverage_lo"], r["coverage_hi"] = r["v_low"] / price, r["v_high"] / price
    return r


def value_developer(c, cfg, spot):
    curve = c["npv_curve"]
    pc, sh = _pc(c), c["shares_m"]
    own = curve.get("ownership", 1.0)
    conv = fx(cfg, curve.get("currency", c["currency"]), pc)
    metal = curve["metal"]
    hold = c.get("holdings")  # e.g. physical uranium held by a developer

    def nav_at(mult):
        npv, extra = interp(curve["points"], spot[metal] * mult)
        h = hold["units"] * spot[hold["metal"]] * mult * fx(cfg, "USD", pc) if hold else 0.0
        return (npv * own * conv + h) / sh + net_cash_ps(c, cfg), extra

    nav, extrap = nav_at(1.0)
    price = c["price"]["value"]
    r = dict(nav=nav, nav_extrapolated=extrap, v_low=nav, v_high=nav, pnav=price / nav if nav else None,
             nc=net_cash_ps(c, cfg), oe=None, exp=None)
    r["scenarios"] = [(nav_at(1 + s)[0],) * 2 for s in cfg["metal_scenarios"]]
    r["coverage_lo"] = r["coverage_hi"] = nav / price
    return r


def value_physical(c, cfg, spot):
    h = c["holdings"]
    pc = _pc(c)
    other = c.get("other_net_assets", 0.0)

    def nav_at(mult):
        gross = h["units"] * spot[h["metal"]] * mult + other * fx(cfg, c["currency"], "USD")
        if "nav_ref" in c:
            ref = c["nav_ref"]
            base = h["units"] * ref["spot"] + other * fx(cfg, c["currency"], "USD")
            return ref["value"] * gross / base
        return gross * fx(cfg, "USD", pc) / c["units_m"]

    nav = nav_at(1.0)
    price = c["price"]["value"]
    other_usd = other * fx(cfg, c["currency"], "USD")
    implied = (price / nav * (h["units"] * spot[h["metal"]] + other_usd) - other_usd) / h["units"]
    r = dict(nav=nav, v_low=nav, v_high=nav, pnav=price / nav, implied_metal_lo=implied, implied_metal_hi=implied,
             primary_metal=h["metal"], oe=None, nc=None, exp=None)
    r["scenarios"] = [(nav_at(1 + s),) * 2 for s in cfg["metal_scenarios"]]
    r["coverage_lo"] = r["coverage_hi"] = nav / price
    return r


def value_growth(c, cfg, spot):
    oe = owner_earnings_ps(c, cfg)
    nc = net_cash_ps(c, cfg)
    price = c["price"]["value"]
    v = lambda g: oe * dcf_factor(g, cfg) + nc  # noqa: E731
    try:
        g = brentq(lambda x: v(x) - price, -0.6, 2.0)
    except ValueError:
        g = None
    r = dict(oe_rep=oe, oe=oe, nc=nc, v0=v(0.0), v_low=v(0.0), v_high=v(0.0), implied_growth=g,
             pe=(price - nc) / oe if oe > 0 else None, exp=None,
             v_buy=v(cfg["zones"]["growth_buy"]), v_sell=v(cfg["zones"]["growth_sell"]))
    r["scenarios"] = [(v(x),) * 2 for x in cfg["growth_scenarios"]]
    r["coverage_lo"] = r["coverage_hi"] = r["v0"] / price
    r["value_fn"] = v
    return r


MODEL_FN = {"producer": value_producer, "cashflow": value_producer, "developer": value_developer,
            "physical": value_physical, "growth": value_growth}


def value_company(c, cfg, spot=None):
    spot = {**cfg["spot"], **(spot or {})}
    r = MODEL_FN[c["model"]](c, cfg, spot)
    p = c["price"]
    r.update(ticker=c["ticker"], name=c["name"], model=c["model"], sector=c.get("sector", ""),
             period=c["period"]["label"], period_end=c["period"]["end"], price=p["value"], price_ccy=p["currency"],
             price_date=p["date"], price_source=p.get("source", "file"), cyclical=c.get("cyclical", False))
    if c.get("projects"):
        r["projects"] = [dict(name=x["name"], value_ps=x["npv"] * fx(cfg, x.get("currency", "USD"), p["currency"]) / c["shares_m"])
                         for x in c["projects"]]
    return r


def etf_lookthrough(etf, results):
    """Weighted value ÷ price across the holdings that have been valued."""
    rows, w_tot, lo, hi = [], 0.0, 0.0, 0.0
    for h in etf["holdings"]:
        r = results.get(h["ticker"].upper())
        if r is None:
            rows.append(dict(ticker=h["ticker"], name=h.get("name", ""), weight=h["weight"], valued=False))
            continue
        w_tot += h["weight"]; lo += h["weight"] * r["coverage_lo"]; hi += h["weight"] * r["coverage_hi"]
        rows.append(dict(ticker=h["ticker"], name=r["name"], weight=h["weight"], valued=True,
                         coverage_lo=r["coverage_lo"], coverage_hi=r["coverage_hi"], zone=r.get("zone")))
    if not w_tot:
        return dict(rows=rows, coverage_weight=0.0)
    return dict(rows=rows, coverage_weight=w_tot, ratio_lo=lo / w_tot, ratio_hi=hi / w_tot,
                value_lo=etf["price"]["value"] * lo / w_tot, value_hi=etf["price"]["value"] * hi / w_tot)
