"""Markets: price-only entries in a list – commodities, an index, ETFs – shown with a chart and a few price facts, not
valued (there are no earnings to value).

A list entry is a market when it has `market: true`:

    - {ticker: GOLD, name: Gold (COMEX futures), yahoo: GC=F, unit: US$/oz, market: true}
    - {ticker: URANIUM, name: Uranium spot, series: uranium_spot, unit: US$/lb, market: true}

`yahoo` entries take their daily history from output/prices.sqlite (tools/update_history.py fills it from the lists);
`series` entries use a monthly series from data/longterm (see longterm.py) – uranium has no daily series on Yahoo.

    rows(entries, log, con=None) → [{ticker, name, unit, symbol, price, currency, date, chg_1w, chg_1m, chg_1y, vs50, vs200, rsi,
                           low52, high52, monthly, note, chart}]
"""
from __future__ import annotations

import datetime as dt

from . import longterm, price_chart, pricedb


def is_market(entry: dict) -> bool:
    return bool(entry.get("market"))


def _change(closes_by_date, days):
    """Change from the last close on or before `days` calendar days ago to the latest close."""
    last_day, last = closes_by_date[-1]
    target = (dt.date.fromisoformat(last_day) - dt.timedelta(days=days)).isoformat()
    then = [c for d, c in closes_by_date if d <= target]
    return last / then[-1] - 1 if then and then[-1] else None


def _daily(con, entry, log):
    sym = entry.get("yahoo") or entry["ticker"]
    if con is None or pricedb.last_date(con, sym) is None:
        log(f"no price history for {sym} ({entry['ticker']}) – python tools/update_history.py --tickers {sym}")
        return None
    chart = price_chart.payload(con, sym, {"model": None, "price_ccy": None}, {"period": {}})
    if not chart:
        return None
    rows = chart["D"] or chart["M"]
    closes = [(r[0], r[4]) for r in rows]
    s = chart["summary"]
    return dict(symbol=sym, price=s["last"], currency=chart["currency"], date=s["date"], monthly=False,
                chg_1w=_change(closes, 7), chg_1m=_change(closes, 30), chg_1y=_change(closes, 365),
                vs50=s.get("vs50"), vs200=s.get("vs200"), rsi=s.get("rsi"), low52=s.get("low52"), high52=s.get("high52"),
                note="", chart=chart)


def _monthly(entry, log):
    name = entry["series"]
    points = longterm.series(name)
    if len(points) < 24:
        log(f"no long-term series '{name}' for {entry['ticker']} – python -m valuescreen.longterm")
        return None
    note = longterm.NOTES.get(name, "")
    chart = price_chart.payload_monthly(entry.get("name", entry["ticker"]), points, note, mode="public")
    closes = [(d, v) for d, v in points]
    year = [v for _, v in points[-12:]]
    return dict(symbol=name.replace("_", " "), price=points[-1][1], currency="USD", date=points[-1][0][:7], monthly=True,
                chg_1w=None, chg_1m=_change(closes, 31), chg_1y=_change(closes, 365), vs50=None, vs200=None, rsi=None,
                low52=min(year), high52=max(year), note=note, chart=chart)


def rows(entries: list[dict], log=print, con=None) -> list[dict]:
    """`con`: the price-history database; opened here when not given (None when there is no database yet)."""
    if con is None and pricedb.DB.exists():
        con = pricedb.connect()
    out = []
    for e in entries:
        r = _monthly(e, log) if e.get("series") else _daily(con, e, log)
        if r:
            out.append({"ticker": e["ticker"], "name": e.get("name", e["ticker"]), "unit": e.get("unit", ""), **r})
    return out
