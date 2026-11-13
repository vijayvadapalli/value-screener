"""Contracted-lease developer model (built for Hut 8), ported from valuation-models/valmodels/leases.py.

For each project, year by year: NOI − interest − bond repayment − tax = cash to shareholders. Discount at the return you
want, add the site's value when the lease ends (a multiple of NOI), subtract any equity still to be paid in, and scale
unfinanced projects by the chance they complete. Then add bitcoin, cash and the rest of the business, minus other debt.
A cap-rate check (NOI ÷ yield − all debt) shows what a buyer of the finished sites might pay.
Zone on the cautious value: BUY ≤ 0.8×, WATCH to 1.0×, HOLD to 1.5×, SELL above.
"""
from __future__ import annotations

import datetime as dt

from scipy.optimize import brentq


def decimal_year(d: dt.date) -> float:
    start = dt.date(d.year, 1, 1)
    return d.year + (d - start).days / (dt.date(d.year + 1, 1, 1) - start).days


class LeaseModel:
    def __init__(self, c: dict, as_of: dt.date):
        self.c = c
        self.t0 = c.get("valuation_date") or decimal_year(as_of)
        self.sh = c["shares_m"]
        self.px = c["price"]["value"]
        b = c["balance"]
        self.project_debt = sum(p["debt"] for p in c["projects"].values() if not p.get("unfunded_equity"))
        self.other_debt = b.get("debt_total", self.project_debt) - self.project_debt
        self.tax = c.get("tax_rate", 0.21)

    def project_cf(self, pr, rate=None, noi_scale=1.0, delay=0.0, comps=None):
        """One project's yearly cash to shareholders, {year: $m}."""
        rate = pr["rate"] if rate is None else rate
        bal, cfs, dep = pr["debt"], {}, pr["cost"] / 15
        n = pr["mat"] - pr["io_until"]
        pay = bal * rate / (1 - (1 + rate) ** -n)
        for y in range(pr["start"], pr["end"] + 1):
            frac = pr["frac0"] if y == pr["start"] else 1.0
            noi = pr["noi"] * noi_scale * frac
            interest = bal * rate * frac  # pre-delivery carry is paid from the bond proceeds
            principal = 0.0 if y <= pr["io_until"] else min(bal, pay - bal * rate)
            tax = max(0.0, noi - interest - dep * frac) * self.tax
            cfs[y + delay] = noi - interest - principal - tax
            if comps is not None:
                comps[y] = dict(noi=noi, interest=interest, principal=principal, tax=tax)
            bal -= principal
        return cfs

    def _pv(self, cfs, r):
        return sum(cf / (1 + r) ** (y + 0.5 - self.t0) for y, cf in cfs.items())

    def other_assets(self, btc_move=0.0):
        b = self.c["balance"]
        return {"Bitcoin": b.get("btc_hut", 0.0) * (1 + btc_move),
                "Bitcoin stake": b.get("abtc_stake", 0.0) * b.get("btc_abtc", 0.0) * (1 + btc_move),
                "Cash + investments": b.get("cash", 0.0) + b.get("other_investments", 0.0)}

    def value(self, s, noi_scale=1.0, btc_move=0.0, r=None, resid=None, delay=None, detail=False):
        r = s["r"] if r is None else r
        resid = s["resid"] if resid is None else resid
        delay = s.get("delay", 0.0) if delay is None else delay
        parts = {}
        for name, pr in self.c["projects"].items():
            rate = s.get("bp2_rate") if pr.get("scenario_rate") else None
            v = self._pv(self.project_cf(pr, rate, noi_scale, delay), r)
            v += pr["noi"] * noi_scale * resid / (1 + r) ** (pr["end"] + delay + 1 - self.t0)
            if pr.get("unfunded_equity"):
                v -= pr["unfunded_equity"] / (1 + r) ** (pr["equity_year"] + delay - self.t0)
            if pr.get("probability"):
                v *= s.get("p_bp2", 1.0)
            parts[name] = v
        parts.update(self.other_assets(btc_move))
        parts["Other operations"] = s.get("ops", 0) * self.c.get("adj_ebitda_quarter", 0.0) * 4
        parts["Other debt"] = -self.other_debt
        v = sum(parts.values()) / self.sh
        return (v, parts) if detail else v

    def implied_return(self, price=None, s=None):
        price = self.px if price is None else price
        s = s or self.c["scenarios"]["Base"]
        try:
            return brentq(lambda r: self.value(s, r=r) - price, -0.02, 0.8)
        except ValueError:
            return None

    def caprate_value(self, cap, r, ops, years=2.0):
        projects = self.c["projects"].values()
        noi = sum(p["noi"] for p in projects)
        debt = sum(p["debt"] for p in projects) + self.other_debt
        eq_in = sum(p.get("unfunded_equity", 0) for p in projects)
        eq = noi / cap - debt - eq_in + sum(self.other_assets().values()) + ops * self.c.get("adj_ebitda_quarter", 0.0) * 4
        return eq / self.sh / (1 + r) ** years

    def timeline(self, s):
        """Base-case cash to shareholders by year and project, for the chart."""
        out = {}
        for name, pr in self.c["projects"].items():
            rate = s.get("bp2_rate") if pr.get("scenario_rate") else None
            out[name] = self.project_cf(pr, rate, 1.0, s.get("delay", 0.0))
        return out


def value_leases(c, cfg, spot):
    m = LeaseModel(c, cfg["as_of"])
    sc = c["scenarios"]
    res = {k: m.value(s, detail=True) for k, s in sc.items()}
    cautious, base, fair = res["Cautious"][0], res["Base"][0], res["Fair"][0]
    price = c["price"]["value"]
    cap = {k: m.caprate_value(*v) for k, v in c.get("caprate_check", {}).items()}
    r = dict(v_low=cautious, v_base=base, v_high=fair, nav=cautious, pnav=price / cautious if cautious else None,
             parts={k: v[1] for k, v in res.items()}, scenario_values={k: v[0] for k, v in res.items()},
             caprate=cap, irr=m.implied_return(), irr_cautious=m.implied_return(s=sc["Cautious"]),
             timeline=m.timeline(sc["Base"]), oe=None, nc=None, exp=None, shares_m=c["shares_m"])
    # sensitivity: return wanted × site value at lease end (base case otherwise)
    returns, resids = [0.08, 0.09, 0.10, 0.11, 0.12, 0.14], [0, 2, 4, 7, 10]
    r["sens_return_resid"] = (returns, resids, [[m.value(sc["Base"], r=x, resid=y) for y in resids] for x in returns])
    r["irr_curve"] = [(p, m.implied_return(price=p), m.implied_return(price=p, s=sc["Cautious"]))
                      for p in [price * f for f in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)]]
    r["scenarios"] = [(cautious, fair)] * len(cfg["metal_scenarios"])
    r["coverage_lo"], r["coverage_hi"] = cautious / price, fair / price
    return r
