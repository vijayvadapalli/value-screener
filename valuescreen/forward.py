"""Forward estimates: owner earnings for a coming year, built line by line from the company's own published estimates
(its outlook, capital plan, contract table) – every line sourced in the company file. Shown on the company page beside
the trailing value as "company estimates – assumption, not reported"; the headline value stays on reported results.

Company file (amounts in the reporting currency, millions a year; costs negative):

  forward:
    tax_rate: 0.25                  # on the pre-tax lines
    usdcad: 1.35                    # the exchange rate the company's outlook assumes (for contract_sales)
    years:
    - year: 2028
      basis: what the year rests on
      contract_sales:               # optional: uranium sold under contracts, realised price from the company's own
        sales_mlb: 28               # table (price_sensitivity, the row for this year) at today's spot
        unit_cost: 68.5             # per lb including D&A and royalties at base_realised
        base_realised: 93.5         # per lb; royalty is charged on the realised price above it
        royalty: 0.077
      pre_tax:   [{name, amount}]
      after_tax: [{name, amount}]
    checks: [text]                  # how the inputs compare with reported results and analyst consensus
    consensus: [{year, eps, low, high, analysts, currency, source, date}]   # reference only, never used in a value

Pure functions:  years(c, r, cfg) → [{year, basis, lines, pre_tax, tax, after_tax, oe_m, oe_ps, values, pe}]
"""
from __future__ import annotations

from .models import interp
from .settings import fx


def contract_gross_profit(c: dict, f: dict, y: dict, cfg: dict) -> tuple[float, str]:
    """Gross profit (reporting currency, $m) on contract sales at today's spot, and its working."""
    k, s = y["contract_sales"], c["price_sensitivity"]
    spot = cfg["spot"][s["metal"]]
    realised_usd = interp(list(zip(s["spot"], s["realised"][y["year"]])), spot)[0]
    realised = realised_usd * f.get("usdcad", 1 / fx(cfg, c["currency"], "USD"))
    unit = k["unit_cost"] + k.get("royalty", 0.0) * (realised - k["base_realised"])
    gp = k["sales_mlb"] * (realised - unit)
    return gp, (f"{s['metal'].title()} gross profit: {k['sales_mlb']:g}m lb × (realised {realised:,.2f} − cost {unit:,.2f}); "
                f"realised US${realised_usd:,.2f} from the company's {y['year']} contract table at spot US${spot:,.2f}")


def years(c: dict, r: dict, cfg: dict) -> list[dict]:
    f = c.get("forward")
    if not f:
        return []
    conv = fx(cfg, c["currency"], c["price"]["currency"])
    shares = c["shares_m"]
    lo, hi, sell = r["mult_lo"], r["mult_hi"], r["sell_multiple"]
    out = []
    for y in f["years"]:
        lines = []
        if y.get("contract_sales"):
            gp, name = contract_gross_profit(c, f, y, cfg)
            lines.append(dict(name=name, amount=gp, taxed=True))
        lines += [dict(x, taxed=True) for x in y.get("pre_tax", [])]
        pre = sum(x["amount"] for x in lines)
        tax = -pre * y.get("tax_rate", f.get("tax_rate", 0.0))
        after = [dict(x, taxed=False) for x in y.get("after_tax", [])]
        oe_m = pre + tax + sum(x["amount"] for x in after)
        oe_ps = oe_m / shares * conv
        out.append(dict(year=y["year"], basis=y.get("basis", ""), lines=lines + after, pre_tax=pre, tax=tax, oe_m=oe_m,
                        oe_ps=oe_ps, values=(oe_ps * lo + r["nc"], oe_ps * hi + r["nc"], oe_ps * sell + r["nc"]),
                        pe=(r["price"] - r["nc"]) / oe_ps if oe_ps > 0 else None))
    return out


def consensus_rows(c: dict, r: dict, cfg: dict) -> list[dict]:
    """Analyst consensus EPS from the file, converted to the price currency – a reference row, never used in a value."""
    out = []
    for x in (c.get("forward") or {}).get("consensus", []):
        eps = x["eps"] * fx(cfg, x.get("currency", c["currency"]), r["price_ccy"])
        out.append(dict(x, eps_pc=eps, pe=r["price"] / eps if eps > 0 else None))
    return out
