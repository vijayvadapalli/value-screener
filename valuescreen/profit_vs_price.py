"""Profit growth vs price growth: did the share price run ahead of the company's profits over about three years?

For each company: yearly growth in sales, profit and share price over the same years, and what that did to the P/E:

    P/E change = ((1 + price growth) / (1 + profit growth)) ^ years − 1

Grade A = P/E fell 25% or more (profits clearly outran the price) · B = fell up to 25% · C = rose up to a third
(roughly in line) · D = rose more than a third (price ran ahead of profits) · n/m = not comparable (a loss at either
end, or missing figures). Each row also shows the company's value-report signal, so "cheap and improving" (A/B +
green) and "expensive and stretched" (D + red) stand out.

Currencies: prices in the stock exchange's currency; sales and profits as the company reports them. Growth rates and
the P/E change do not depend on the currency.
Sources: Screener.in's compounded 3-year growth for Indian companies (net profit), Yahoo Finance's annual and
quarterly statements for the rest (diluted EPS, so buybacks and new shares count).
"""
from __future__ import annotations

import datetime as dt

from . import style as S
from .wording import esc, money

ASSET_MODELS = {"developer": "a developer, valued on its study NAV, not profits",
                "physical": "holds the metal; profits are revaluations, so it is valued on NAV",
                "leases": "valued on contracted lease cash, not today's profits",
                "liquid": "no meaningful profits; not valued"}
GRADE_COLOUR = {"A": S.SIGNAL["green"], "B": "#4FA884", "C": "#B7791F", "D": S.SIGNAL["red"], "n/m": S.MUTED}


# ------------------------------------------------------------------------------------------------- the numbers
def cagr(then, now, years):
    """Yearly growth from `then` to `now`; None when either end is not positive or the period is unknown."""
    if then is None or now is None or not years or then <= 0 or now <= 0:
        return None
    return (now / then) ** (1 / years) - 1


def pe_change(price_growth, profit_growth, years):
    if price_growth is None or profit_growth is None or not years:
        return None
    return ((1 + price_growth) / (1 + profit_growth)) ** years - 1


def grade(change):
    if change is None:
        return "n/m"
    return "A" if change <= -0.25 else "B" if change <= 0 else "C" if change <= 1 / 3 else "D"


def evaluate(rec: dict) -> dict:
    """Adds sales / profit / price growth, the P/E change and the grade to one company's raw record.

    Screener records carry Screener's own 3-year growth rates; Yahoo records carry the figures at both ends."""
    out = dict(rec)
    years = rec.get("years") or 3.0
    model = (rec.get("value") or {}).get("model")
    if model in ASSET_MODELS:   # profits here are revaluations or there are none – the value report uses assets instead
        return dict(out, years=years, sales_growth=None, profit_growth=None, pe_change=None, grade="n/m",
                    price_growth=rec.get("price_growth_3y") or cagr(rec.get("price_then"), rec.get("price"), years),
                    nm_reason=ASSET_MODELS[model])
    if rec.get("not_comparable"):   # the company file says the past years are a different company or hold a one-off
        return dict(out, years=years, sales_growth=None, profit_growth=None, pe_change=None, grade="n/m",
                    price_growth=rec.get("price_growth_3y") or cagr(rec.get("price_then"), rec.get("price"), years),
                    nm_reason=f"profit history not comparable ({rec['not_comparable']})")
    if rec.get("source") == "screener":
        sales, profit, price = rec.get("sales_growth_3y"), rec.get("profit_growth_3y"), rec.get("price_growth_3y")
        if rec.get("profit_then") is not None and rec["profit_then"] <= 0:
            profit = None   # growth from a loss means nothing
    else:
        sales = cagr(rec.get("sales_then"), rec.get("sales_now"), years)
        profit = cagr(rec.get("eps_then"), rec.get("eps_now"), years)
        price = cagr(rec.get("price_then"), rec.get("price"), years)
    change = pe_change(price, profit, years)
    out.update(years=years, sales_growth=sales, profit_growth=profit, price_growth=price, pe_change=change, grade=grade(change))
    if change is None:
        out["nm_reason"] = rec.get("nm_reason") or ("a loss or no profit at one end" if profit is None else "no price history")
    return out


def value_summary(r: dict) -> dict:
    """The value report's verdict for one company, as shown next to its grade."""
    m = r["model"]
    if m == "growth":
        g = r.get("implied_growth")
        detail = "no valid earnings" if g is None else f"needs {g*100:+.1f}%/yr"
    elif m in ("developer", "physical"):
        detail = f"{r['pnav']:.2f}× NAV"
    elif m == "leases":
        detail = f"{r['pnav']:.2f}× cautious value"
    elif m == "liquid":
        detail = "not valued"
    elif r.get("margin_of_safety") is None:
        detail = "no earnings"
    else:
        detail = f"price vs 15x: {money(r['price'], r['price_ccy'])} vs {money(r['v_high'], r['price_ccy'])}"
    return {"signal": r["signal"], "action": r["action"], "detail": detail, "model": m}


def rows(entries: list[dict], raw: dict, results: dict, companies: dict) -> list[dict]:
    """Evaluated rows for every list entry that has figures, best grade first. `results` are the value results."""
    out = []
    for entry in entries:
        t = entry["ticker"]
        if not raw.get(t):
            continue
        company = companies.get(t) or {}
        price_date = raw[t].get("price_date")
        out.append(evaluate({**raw[t], "ticker": t, "quantity": entry.get("quantity"),
                             "name": company.get("name") or entry.get("name") or raw[t].get("name", t),
                             "price_date": dt.date.fromisoformat(price_date) if isinstance(price_date, str) else price_date,
                             "value": value_summary(results[t]) if t in results else None,
                             "not_comparable": (company.get("v2") or {}).get("history_not_comparable")}))
    return sorted(out, key=sort_key)


def sources_text(rows_: list[dict], as_of: dt.date) -> str:
    used = sorted({"Screener.in company pages (3-year compounded growth)" if r["source"] == "screener" else
                   "Yahoo Finance annual and quarterly statements and prices" for r in rows_})
    return "; ".join(used) + f", fetched {as_of:%d %b %Y}; value signals from this project's company files."


def comment(r: dict) -> str:
    if r["grade"] == "n/m":
        text = f"Not comparable: {r['nm_reason']}."
        if r.get("price_growth") is not None:
            text += f" Price {r['price_growth']*100:+.0f}%/yr."
    else:
        direction = "down" if r["pe_change"] < 0 else "up"
        text = (f"Profits {r['profit_growth']*100:+.0f}%/yr vs price {r['price_growth']*100:+.0f}%/yr – P/E {direction} "
                f"{abs(r['pe_change'])*100:.0f}% in {r['years']:.0f} years.")
    value = r.get("value")
    if value and value.get("action") == "No valid value":
        text += " No valid value on the value report."
    elif value:
        text += {"green": " Cheap on the value report.", "red": " Expensive on the value report.",
                 "blue": " Watch / hold on the value report."}.get(value["signal"], "")
    return text + (f" {esc(r['note'])}" if r.get("note") else "")


# ------------------------------------------------------------------------------------------------- report text
def _amount(x, ccy, unit):
    if x is None:
        return "–"
    if unit == "cr":
        return f"{S.money(x, ccy, 0)} cr"
    millions = x / 1e6
    return f"{S.money(millions / 1000, ccy, 1)}bn" if abs(millions) >= 10000 else f"{S.money(millions, ccy, 0)}m"


def _at_a_glance(rows):
    counts = {g: sum(1 for r in rows if r["grade"] == g) for g in GRADE_COLOUR}
    text = "<b>At a glance:</b> " + " · ".join(f"{g} {n}" for g, n in counts.items() if n)
    cheap = [r["ticker"] for r in rows if r["grade"] in ("A", "B") and (r.get("value") or {}).get("signal") == "green"]
    dear = [r["ticker"] for r in rows if r["grade"] == "D" and (r.get("value") or {}).get("signal") == "red"]
    if cheap:
        text += f". <b>Profits outran the price and cheap on value (A/B + green):</b> {', '.join(cheap)}"
    if dear:
        text += f". <b>Price outran profits and expensive (D + red):</b> {', '.join(dear)}"
    return text + "."


HOW_TO_READ = ("<b>How to read it.</b> Growth is a yearly rate over about three years: for Indian companies Screener.in's "
               "compounded figures (net profit, latest three financial years; share price over three years); for the rest, "
               "Yahoo Finance statements from the financial year about three years back to the latest twelve months "
               "(diluted EPS, so buybacks and new shares count). P/E change = ((1 + price growth) ÷ (1 + profit growth)) ^ years "
               "− 1: negative means the share is cheaper relative to profits than at the start. <b>Grade:</b> A = P/E fell "
               "25% or more · B = fell up to 25% · C = rose up to a third · D = rose more than a third · n/m = not comparable. "
               "Prices are in the exchange's currency; sales and profits as reported (m = millions, cr = crore). Profits "
               "include one-offs – check large jumps in the filing. A rising metal price lifts miners' profits faster than "
               "their prices (most gold miners grade A now); if the metal falls, profits fall faster too.")


def sort_key(r):
    """A first (most negative P/E change), n/m last."""
    return (r["pe_change"] is None, r["pe_change"] if r["pe_change"] is not None else 0)
