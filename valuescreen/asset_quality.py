"""Bad loans at banks and other lenders: how much of the book value is real, and when to stop trusting the earnings.

A lender's book value and earnings are only as good as its loans. Two things follow:
- **Adjusted book value** = book value − bad loans not yet provided for, per share. In India that is the net NPA
  (net NPA % × loans); in the US, where the allowance already covers expected lifetime losses (CECL), it is only the
  shortfall when nonaccrual loans exceed the allowance (usually zero). The financial rule then values
  adjusted book × 5-year ROE, and price-to-book is shown on the adjusted book.
- **Warning signs** cap a cheap signal at blue and keep the company off the shortlist (thresholds in config.yaml,
  `asset_quality`):
  India – net NPA above 2% of loans, gross NPA above 5%, provision coverage below 60%, gross NPA up more than half a
  point over four quarters.
  US – nonaccrual loans above 2% of loans, allowance below the nonaccrual loans, net charge-off rate up by more than
  half on a year earlier.

Sources: Screener.in's quarterly "Gross NPA %" / "Net NPA %" rows and its balance-sheet breakdown for loans (India,
written into the company file by tools/fetch_screener.py); SEC facts for allowance, loans, nonaccrual loans and
charge-offs (US, see us_fundamentals.py). Capital ratios (CET1 / CAR) are not in either source – check them by hand.
"""
from __future__ import annotations

DEFAULTS = {"max_net_npa": 0.02, "max_gross_npa": 0.05, "min_coverage": 0.60, "max_gross_npa_rise": 0.005,
            "max_nonaccrual": 0.02, "max_nco_rise": 0.5, "min_nco_for_rise": 0.002}


def limits(cfg) -> dict:
    return {**DEFAULTS, **(cfg.get("asset_quality") or {})}


def _last(xs):
    xs = [x for x in (xs or []) if x is not None]
    return xs[-1] if xs else None


def india(aq: dict | None, shares_m: float | None, cfg) -> dict | None:
    """From the company file's `v2.asset_quality` block:
        quarters: [...]  gross_npa_pct: [...]  net_npa_pct: [...]   # Screener's quarterly rows, oldest first, in %
        loans_cr: 307834   loans_basis: "..."                         # loans (₹ crore) the percentages apply to
    Returns {gross_npa, net_npa, coverage, gross_npa_change, bad_loans_ps, lines, flags} or None without NPA figures."""
    if not aq:
        return None
    gross_q = [None if x is None else x / 100 for x in aq.get("gross_npa_pct") or []]
    net_q = [None if x is None else x / 100 for x in aq.get("net_npa_pct") or []]
    gross, net = _last(gross_q), _last(net_q)
    if gross is None and net is None:
        return None
    lim = limits(cfg)
    out = {"gross_npa": gross, "net_npa": net, "quarter": _last(aq.get("quarters")), "lines": [], "flags": []}
    # Coverage ≈ share of the bad loans already provided for. Approximate: net NPA % is on net loans, gross on gross.
    out["coverage"] = 1 - net / gross if gross and net is not None and gross > 0 else None
    known = [x for x in gross_q if x is not None]
    out["gross_npa_change"] = known[-1] - known[-5] if len(known) >= 5 else None
    loans = aq.get("loans_cr")
    out["bad_loans_ps"] = net * loans * 10 / shares_m if net is not None and loans and shares_m else None  # ₹ crore → ₹
    out["lines"].append(("Gross NPA · net NPA" + (f" ({out['quarter']})" if out["quarter"] else ""),
                         f"{_pct(gross)} · {_pct(net)}"))
    if out["coverage"] is not None:
        out["lines"].append(("Provision coverage (approx.)", _pct(out["coverage"], 0)))
    if out["gross_npa_change"] is not None:
        out["lines"].append(("Gross NPA change over 4 quarters", f"{out['gross_npa_change']*100:+.2f} pts"))
    if loans:
        out["lines"].append(("Loans the NPA % applies to", f"₹{loans:,.0f} cr – {aq.get('loans_basis', 'Screener.in')}"))
    if net is not None and net > lim["max_net_npa"]:
        out["flags"].append(f"net NPA {_pct(net)}")
    if gross is not None and gross > lim["max_gross_npa"]:
        out["flags"].append(f"gross NPA {_pct(gross)}")
    if out["coverage"] is not None and out["coverage"] < lim["min_coverage"]:
        out["flags"].append(f"provision coverage {_pct(out['coverage'], 0)}")
    if out["gross_npa_change"] is not None and out["gross_npa_change"] > lim["max_gross_npa_rise"]:
        out["flags"].append(f"gross NPA up {out['gross_npa_change']*100:.1f} pts in a year")
    return out


def us(credit: dict | None, shares: float | None, cfg) -> dict | None:
    """From us_fundamentals.summarize()["credit"]: loans, allowance, nonaccrual (with dates), and net charge-offs for the
    last twelve months and the twelve months before. Returns None for a company without a loan book."""
    if not credit or not credit.get("loans") or credit["loans"] <= 0:
        return None
    lim = limits(cfg)
    loans, allowance, nonaccrual = credit["loans"], credit.get("allowance"), credit.get("nonaccrual")
    nco, nco_prev, provision = credit.get("nco_ttm"), credit.get("nco_prev_ttm"), credit.get("provision_ttm")
    out = {"loans": loans, "lines": [], "flags": [],
           "reserve_ratio": allowance / loans if allowance is not None else None,
           "nonaccrual": nonaccrual / loans if nonaccrual is not None else None,
           "coverage": allowance / nonaccrual if allowance is not None and nonaccrual else None,
           "nco_rate": nco / loans if nco is not None else None,
           "nco_rate_prev": nco_prev / loans if nco_prev is not None else None,
           "credit_cost": provision / loans if provision is not None else None}
    shortfall = max(0.0, nonaccrual - allowance) if nonaccrual is not None and allowance is not None else 0.0
    out["bad_loans_ps"] = shortfall / shares if shares else None
    if out["nonaccrual"] is not None:
        out["lines"].append(("Nonaccrual loans ÷ loans", _pct(out["nonaccrual"])))
    if out["reserve_ratio"] is not None:
        out["lines"].append(("Allowance ÷ loans", _pct(out["reserve_ratio"])))
    if out["nco_rate"] is not None:
        prev = f" (year before {_pct(out['nco_rate_prev'])})" if out["nco_rate_prev"] is not None else ""
        out["lines"].append(("Net charge-offs, 12 months ÷ loans", _pct(out["nco_rate"]) + prev))
    if out["nonaccrual"] is not None and out["nonaccrual"] > lim["max_nonaccrual"]:
        out["flags"].append(f"nonaccrual loans {_pct(out['nonaccrual'])}")
    if out["coverage"] is not None and out["coverage"] < 1:
        out["flags"].append(f"allowance covers {_pct(out['coverage'], 0)} of nonaccrual loans")
    r, p = out["nco_rate"], out["nco_rate_prev"]
    if r is not None and p and r >= lim["min_nco_for_rise"] and r > p * (1 + lim["max_nco_rise"]):
        out["flags"].append(f"charge-offs up {_pct(p)} → {_pct(r)}")
    return out


def _pct(x, digits=2):
    return "–" if x is None else f"{x*100:.{digits}f}%"
