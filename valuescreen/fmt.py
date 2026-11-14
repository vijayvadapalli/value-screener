"""Formatting for the report text: escaping, money, dates and the small phrases every model uses."""
from __future__ import annotations

import html

from . import style as S


def esc(x):
    return html.escape(str(x), quote=False)


def money(x, ccy, nd=2):
    if x is None:
        return "–"
    if ccy == "GBP" and abs(x) < 100:   # LSE shares are quoted in pence
        return f"{x * 100:,.0f}p"
    return S.money(x, ccy, nd if abs(x) < 10000 else 0)


def day(d):
    return f"{d.day} {d:%b %Y}" if d else "–"


def price_date(r):
    return "date not shown" if r.get("price_undated") else day(r["price_date"])


def per_year(n):
    return "4/3" if abs(n - 4 / 3) < 1e-6 else f"{n:g}"


def signed(x, nd=2):
    return f"{'−' if x < 0 else '+'}{abs(x):,.{nd}f}"


def net_cash_term(nc, ccy):
    return f"+ {money(nc, ccy)} net cash" if nc >= 0 else f"− {money(-nc, ccy)} net debt"


def flag_text(r):
    return " ".join(f"[{esc(f)}]" for f in r.get("flags", []))


def has_earnings(r):
    return (r.get("oe") or 0) > 0
