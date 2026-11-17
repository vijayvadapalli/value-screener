"""Valuation models. Pure functions: company dict + config + spot prices -> result dict.

All per-share outputs are in the company's *price* currency, so value and price are always comparable.
Units convention: money in millions of the stated currency; ounces in Moz, pounds in Mlb, per period;
spot and realised metal prices in USD per oz / lb.
"""
from __future__ import annotations

from scipy.optimize import brentq

from . import v2 as v2rules
from .leases import value_leases
from .settings import ValidationError, fx, tier_of
from .types import Result


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


def discount_rate(c, cfg):
    """10% (US) by default; per currency from config (12% for INR); a company file can set its own."""
    d = cfg["growth_dcf"]
    if c.get("discount_rate") is not None:
        return c["discount_rate"]
    return (d.get("discount_rate_by_currency") or {}).get(c.get("currency"), d["discount_rate"])


def dcf_factor(g, cfg, rate=None, exit_multiple=None):
    d = cfg["growth_dcf"]
    q = (1 + g) / (1 + (d["discount_rate"] if rate is None else rate))
    em = d["exit_multiple"] if exit_multiple is None else exit_multiple
    return sum(q ** t for t in range(1, d["years"] + 1)) + em * q ** d["years"]


def fcf_ps(c, cfg):
    """Free cash flow per share a year after ALL capex (not just sustaining), when the file has cfo and capex_total."""
    e = c.get("earnings", {})
    if "cfo" not in e or "capex_total" not in e or not c.get("shares_m"):
        return None
    per_year = e.get("per_year", c["period"]["per_year"])
    return (e["cfo"] - e["capex_total"]) * per_year / c["shares_m"] * fx(cfg, c["currency"], _pc(c))


def curve_delta_ps(c, cfg, spot) -> float:
    """Owner-earnings change per share (price currency) from a `price_sensitivity:` block when `spot` differs from
    today's spot (cfg["spot"]) – 0 at today's spot, so the headline value never moves. For companies whose realised
    price lags spot through long-term contracts (Cameco): the company's own table of expected realised price at each
    spot price, for one year. Change a year, US$m = (sales × Δrealised × (1 − royalty) − purchases at spot × Δspot)
    × (1 − tax)."""
    s = c.get("price_sensitivity")
    if not s or spot[s["metal"]] == cfg["spot"][s["metal"]]:
        return 0.0
    curve = list(zip(s["spot"], s["realised"][s["year"]]))
    now, case = cfg["spot"][s["metal"]], spot[s["metal"]]
    d_realised = interp(curve, case)[0] - interp(curve, now)[0]
    usd_m = (s["sales_mlb"] * d_realised * (1 - s.get("royalty", 0.0)) - s.get("purchases_mlb", 0.0) * (case - now)) \
        * (1 - s.get("tax_rate", c.get("tax_rate", 0.0)))
    return usd_m / c["shares_m"] * fx(cfg, "USD", _pc(c))


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
    oe = oe_rep + delta + (curve_delta_ps(c, cfg, spot) if block == "earnings" else 0.0)
    exp = sum(s * spot[m] for m, s, _, inc in terms if inc)          # value of a 100% move in scenario metals
    nc = net_cash_ps(c, cfg)
    price = c["price"]["value"]
    r = dict(oe_rep=oe_rep, oe=oe, nc=nc, mult_lo=lo, mult_hi=hi, v_low=oe * lo + nc, v_high=oe * hi + nc,
             v_sell=oe * sell_m + nc, sell_multiple=sell_m, exp=exp, basis=block)
    r["pe"] = (price - nc) / oe if oe > 0 else None
    if terms:
        metal = r["primary_metal"] = c.get("primary_metal", terms[0][0])
        sens = next(s for m, s, _, _ in terms if m == metal)
        # the metal price at which the value at each multiple equals the share price
        r["implied_metal_lo"] = spot[metal] + ((price - nc) / lo - oe) / sens if sens else None
        r["implied_metal_hi"] = spot[metal] + ((price - nc) / hi - oe) / sens if sens else None
    cost = next((m.get("aisc") for m in c.get("metals", []) if m.get("aisc")), None)
    if cost:
        r["cost_ratio"] = cost / spot[c.get("primary_metal", c["metals"][0]["metal"])]
    r["scenarios"] = [((oe + s * exp) * lo + nc, (oe + s * exp) * hi + nc) for s in cfg["metal_scenarios"]]
    r["coverage_lo"], r["coverage_hi"] = r["v_low"] / price, r["v_high"] / price
    r["terms"] = [dict(metal=m, sens=sv, realised=rl, spot=spot[m], delta=sv * (spot[m] - rl)) for m, sv, rl, _ in terms]
    gold = next((t for t in r["terms"] if t["metal"] == "gold"), None)
    if gold and gold["sens"]:   # stress test: value if gold falls to each price in config stress_gold
        oe_at = lambda g: oe + gold["sens"] * (g - spot["gold"])  # noqa: E731
        r["stress"] = [(g, oe_at(g) * lo + nc, oe_at(g) * hi + nc) for g in cfg.get("stress_gold", [])]
    r["fcf_ps"] = fcf_ps(c, cfg)
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
    rate = discount_rate(c, cfg)
    price = c["price"]["value"]
    v2 = None
    if c.get("v2"):
        v2 = v2rules.base_eps(c, cfg)
        oe = v2["eps"] * fx(cfg, c["v2"].get("eps_currency", c["currency"]), _pc(c))
        nc = 0.0 if v2["kind"] == "financial" else net_cash_ps(c, cfg)
    else:
        oe = owner_earnings_ps(c, cfg)
        nc = net_cash_ps(c, cfg)
    v = lambda g: oe * dcf_factor(g, cfg, rate) + nc  # noqa: E731
    try:
        g = brentq(lambda x: v(x) - price, -0.6, 2.0) if oe > 0 else None
    except ValueError:
        g = None
    buy_g = cfg["zones"]["growth_buy"]
    if tier_of(c, cfg) == "A":
        buy_g = cfg["zones"].get("growth_buy_tier_a", buy_g)
    r = dict(oe_rep=oe, oe=oe, nc=nc, v0=v(0.0), v_low=v(0.0), v_high=v(0.0), implied_growth=g,
             pe=(price - nc) / oe if oe > 0 else None, exp=None, discount_rate=rate,
             no_growth_multiple=dcf_factor(0.0, cfg, rate), v10=v(0.10), v20=v(0.20),
             v_buy=v(buy_g), v_sell=v(cfg["zones"]["growth_sell"]), growth_buy=buy_g)
    r["scenarios"] = [(v(x),) * 2 for x in cfg["growth_scenarios"]]
    r["coverage_lo"] = r["coverage_hi"] = r["v0"] / price if price else 0.0
    r["value_fn"] = v
    r["fcf_ps"] = fcf_ps(c, cfg)
    if v2:
        r.update(_v2_fields(c["v2"], v2, price, r["no_growth_multiple"]))
    return r


def _v2_fields(data, worked, price, no_growth_multiple):
    """Nifty v2 extras for the report: cash conversion, price-to-book against the fair multiple, EPS history."""
    out = dict(v2=worked, cash_conversion=worked["cash_conversion"], eps_annual=data.get("eps_annual", []),
               eps_years=data.get("years", []), cfo_annual=data.get("cfo_annual", []), profit_annual=data.get("profit_annual", []))
    if worked["kind"] == "financial" and data.get("book_value_ps"):
        roe = data.get("roe_5y")
        book = worked.get("adjusted_book_ps") or data["book_value_ps"]   # book less bad loans not provided for
        out["pb"] = price / book if book > 0 else None
        out["pb_reported"] = price / data["book_value_ps"]
        out["fair_pb"] = roe * no_growth_multiple if roe is not None else None
        out["asset_quality"] = worked.get("asset_quality")
    return out


def value_liquid(c, cfg, spot):
    """Not valued (UEC, UUUU): no earnings and no single study. Shows liquid assets as a share of market value."""
    pc, sh, price = _pc(c), c["shares_m"], c["price"]["value"]
    items = [(it["label"], it["amount"] * fx(cfg, it.get("currency", c["currency"]), pc)) for it in c.get("liquid_assets", [])]
    h = c.get("holdings")
    if h:
        items.append((f"Physical {h['metal']} {h['units']:g} M units at spot", h["units"] * spot[h["metal"]] * fx(cfg, "USD", pc)))
    debt = c.get("debt", 0.0) * fx(cfg, c["currency"], pc)
    liquid = sum(a for _, a in items)
    mcap = price * sh
    r = dict(liquid_items=items, liquid=liquid, debt=debt, market_value=mcap, liquid_ratio=(liquid - debt) / mcap,
             v_low=None, v_high=None, oe=None, nc=None, exp=None)
    r["scenarios"] = [((liquid - debt) / sh,) * 2 for _ in cfg["metal_scenarios"]]
    r["coverage_lo"] = r["coverage_hi"] = r["liquid_ratio"]
    return r


MODEL_FN = {"producer": value_producer, "cashflow": value_producer, "developer": value_developer,
            "physical": value_physical, "growth": value_growth, "leases": value_leases, "liquid": value_liquid}


def market_value_usd_bn(c, cfg):
    sh = c.get("shares_m") or c.get("units_m")
    if not sh:
        return None
    try:
        return c["price"]["value"] * sh * fx(cfg, c["price"]["currency"], "USD") / 1000
    except ValidationError:  # a missing FX rate only costs the shade
        return None


def shade(mv_bn, cfg, sector=""):
    """darkest / medium / light / lightest by market value (Valuation Playbook)."""
    s = cfg.get("market_cap_shades_usd_bn") or {"darkest": 100, "medium": 30, "light": 10, "tech_mega": 200}
    if mv_bn is None:
        return None
    top = s.get("tech_mega", s["darkest"]) if sector == "tech" else s["darkest"]
    return "darkest" if mv_bn >= top else "medium" if mv_bn >= s["medium"] else "light" if mv_bn >= s["light"] else "lightest"


def value_company(c: dict, cfg: dict, spot: dict | None = None) -> Result:
    spot = {**cfg["spot"], **(spot or {})}
    r = MODEL_FN[c["model"]](c, cfg, spot)
    p = c["price"]
    r.update(ticker=c["ticker"], name=c["name"], model=c["model"], sector=c.get("sector", ""),
             period=c["period"]["label"], period_end=c["period"]["end"], price=p["value"], price_ccy=p["currency"],
             price_date=p["date"], price_source=p.get("source", "file"), cyclical=c.get("cyclical", False),
             tier=tier_of(c, cfg), price_undated=bool(p.get("undated")), price_note=p.get("note", ""),
             flags_file=list(c.get("flags", [])), comment=c.get("comment", ""), currency=c["currency"],
             period_reported=c["period"].get("reported"), display_ticker=c.get("display_ticker", c["ticker"]))
    r["market_value_usd_bn"] = market_value_usd_bn(c, cfg)
    r["shade"] = shade(r["market_value_usd_bn"], cfg, c.get("sector", ""))
    if c.get("projects") and c["model"] != "leases":
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
