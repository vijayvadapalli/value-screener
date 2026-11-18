"""Price charts for the company sections: the data for the interactive HTML chart.

It shows RSI(14) above candles with the 20-, 50- and 200-day averages, support / resistance and trend lines found
automatically (chart_levels.py), and our own valuation on the price: the value lines, buy / add levels and the start
of the sell zone, with results (E) and dividend (D) markers. Prices come from output/prices.sqlite (pricedb.py).

    payload(con, symbol, r, c)   → dict for the HTML chart (JSON), or None when there is no history
"""
from __future__ import annotations

import datetime as dt

from . import chart_levels as L
from . import kinds
from . import pricedb
from . import style as S

DAILY_DAYS, WARMUP_DAYS, LONG_YEARS = 365, 300, 10   # daily bars for a year (+ room for the 200-day average)
SMA_COLOURS = {20: "#A0AEC0", 50: S.SIGNAL["green"], 200: "#9B2C2C"}   # 20-day light grey, 50-day green, 200-day dark red


def _r(x):
    if x is None:
        return None
    return round(x, 2) if abs(x) >= 10 else round(x, 4)


def _scaled(con, symbol):
    """All daily bars in the major currency unit (pence → pounds) and that currency."""
    info = pricedb.info(con, symbol) or {}
    bars = pricedb.bars(con, symbol)
    if not bars:
        return [], None, 1.0
    _, major = pricedb.to_major(1.0, info.get("currency"))
    factor = pricedb.to_major(1.0, info.get("currency"))[0]
    if factor != 1.0:
        bars = [dict(b, **{k: (b[k] * factor if b[k] is not None else None) for k in ("open", "high", "low", "close", "adj_close")})
                for b in bars]
    return bars, major, factor


LIGHT_GREEN, DARK_GREEN = S.VALUE_LIGHT, S.VALUE_DARK


def value_lines(r: dict) -> list[dict]:
    """Our valuation drawn on the price, as solid lines: the fair value (15x, 13x for oil; the buy level for growth,
    developers and holders) in green, the cautious value (12x, 10x; NAV; value with no growth) in darker green, and
    the start of the sell zone (25x) in red. A separate buy level (20% below the cautious value, tiers B and C) is
    dashed green. [{"price", "label", "kind", "color", "solid"}]."""
    kind = kinds.KINDS.get(r.get("model"))   # none for a symbol we do not value (a commodity, an ETF)
    items = kind.value_lines(r) if kind else []
    merged = {}   # tier A: the start and add levels are the 15x and 12x values – one line, both labels
    for price, label, kind, colour, solid in items:
        if price and price > 0:
            key = round(price, 4)
            if key in merged:
                merged[key]["label"] += " · " + label
                merged[key]["solid"] = merged[key]["solid"] or solid
            else:
                merged[key] = {"price": _r(price), "label": label, "kind": kind, "color": colour, "solid": solid}
    return list(merged.values())


def _markers(con, symbol, c, factor, start):
    out = [{"date": a["date"], "kind": "D", "text": f"Dividend {a['value'] * factor:.4g}"} for a in pricedb.actions(con, symbol, "dividend")
           if a["date"] >= start]
    out += [{"date": a["date"], "kind": "S", "text": f"Split {a['value']:g}:1" if a["value"] >= 1 else f"Consolidation 1:{1 / a['value']:.0f}"}
            for a in pricedb.actions(con, symbol, "split") if a["date"] >= start]
    reported = (c.get("period") or {}).get("reported")
    if reported:
        d = reported.isoformat() if isinstance(reported, dt.date) else str(reported)
        if d >= start:
            out.append({"date": d, "kind": "E", "text": f"Results {c['period'].get('label', '')}"})
    return sorted(out, key=lambda x: x["date"])


def payload(con, symbol: str, r: dict, c: dict, watched: list | None = None, watched_label: str = "Watched levels",
            mode: str = "public", long_years: int | None = LONG_YEARS, long_monthly: list | None = None,
            patterns: list | None = None, bars: list | None = None) -> dict | None:
    """bars: ready-made daily bars (e.g. a ratio from ratio_bars) instead of the symbol's own – no markers then."""
    own = bars is None
    bars, currency, factor = _scaled(con, symbol) if own else (bars, r.get("price_ccy"), 1.0)
    if len(bars) < 30:
        return None
    last_day = dt.date.fromisoformat(bars[-1]["date"])
    d_start = (last_day - dt.timedelta(days=DAILY_DAYS + WARMUP_DAYS)).isoformat()
    l_start = (last_day - dt.timedelta(days=365 * long_years)).isoformat() if long_years else bars[0]["date"]
    row = lambda b: [b["date"], _r(b["open"]), _r(b["high"]), _r(b["low"]), _r(b["close"]), int(b["volume"] or 0)]  # noqa: E731
    long_bars = [b for b in bars if b["date"] >= l_start]
    ten_years = (last_day - dt.timedelta(days=365 * LONG_YEARS)).isoformat()
    same_ccy = currency == r.get("price_ccy")
    lv = L.levels(bars)
    out = {
        "symbol": symbol, "currency": currency, "same_currency": same_ccy,
        "D": [row(b) for b in bars if b["date"] >= d_start],
        "W": [row(b) for b in pricedb.resample([b for b in long_bars if b["date"] >= ten_years], "W")],
        "M": _with_history([row(b) for b in pricedb.resample(long_bars, "M")], long_monthly),
        "show_from": (last_day - dt.timedelta(days=365)).isoformat(),
        "levels": [{"price": _r(x["price"]), "kind": side, "touches": x["touches"]} for side in ("support", "resistance") for x in lv[side]],
        "trends": [{"kind": t["kind"], "from": [t["from"][0], _r(t["from"][1])], "to": [t["to"][0], _r(t["to"][1])], "touches": t["touches"],
                    "tentative": t.get("tentative", False)}
                   for t in L.trend_lines(bars)],
        "values": value_lines(r) if same_ccy else [],
        "markers": _markers(con, symbol, c, factor, l_start) if own else [],
        "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in L.summary(bars).items()},
        "signal": r.get("signal"), "action": r.get("action"),
        "watched": [{"lo": _r(x["lo"]), "hi": _r(x["hi"]), "kind": x["kind"], "tf": x.get("tf", "D")} for x in (watched or [])],
        "watched_label": watched_label, "mode": mode, "patterns": patterns or [],
    }
    return out


def ratio_bars(con, num: str, den: str) -> list[dict]:
    """Daily bars of one symbol divided by another on the days both traded (open / open, high / high, low / low,
    close / close – as charting sites draw a ratio), each in its major currency unit."""
    a, _, _ = _scaled(con, num)
    b = {x["date"]: x for x in _scaled(con, den)[0]}
    out = []
    for x in a:
        y = b.get(x["date"])
        if not y or not all(x[k] and y[k] for k in ("open", "high", "low", "close")):
            continue
        o, h, l, c = (x[k] / y[k] for k in ("open", "high", "low", "close"))
        out.append({"date": x["date"], "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c, "adj_close": c,
                    "volume": 0})
    return out


def monthly_closes(con, symbol: str) -> list[tuple[str, float]]:
    """[(YYYY-MM-01, last close of the month)] from the daily history, in the major currency unit."""
    bars, _, _ = _scaled(con, symbol)
    return [(b["date"][:7] + "-01", b["close"]) for b in pricedb.resample(bars, "M")] if bars else []


def nearest_levels(p: dict) -> list[dict]:
    """The nearest support below and the nearest resistance above the price (levels come nearest first)."""
    return [x for k in ("support", "resistance") for x in [next((l for l in p["levels"] if l["kind"] == k), None)] if x]


def _with_history(monthly_rows: list, long_monthly: list | None) -> list:
    """Monthly bars, preceded by a long monthly series (date, price) for the months before the daily data starts.
    The earlier months have no high / low – each is drawn as a flat bar at the monthly average."""
    if not long_monthly or not monthly_rows:
        return monthly_rows
    first = monthly_rows[0][0][:7]
    early = [[d, _r(v), _r(v), _r(v), _r(v), 0] for d, v in long_monthly if d[:7] < first]
    return early + monthly_rows


def payload_monthly(name: str, points: list, note: str = "", watched: list | None = None, mode: str = "research") -> dict | None:
    """A monthly-only chart (no daily data – e.g. the IMF uranium series): one bar per month at the monthly price."""
    if len(points) < 24:
        return None
    rows = [[d, _r(v), _r(v), _r(v), _r(v), 0] for d, v in points]
    closes = [v for _, v in points]
    return {"symbol": name, "currency": "USD", "same_currency": True, "D": [], "W": [], "M": rows, "show_from": rows[0][0],
            "levels": [], "trends": [], "values": [], "markers": [],
            "summary": {"last": _r(closes[-1]), "date": rows[-1][0], "high52": _r(max(closes[-12:])), "low52": _r(min(closes[-12:]))},
            "signal": None, "action": None, "watched": watched or [], "watched_label": "Their levels", "mode": mode,
            "note": note, "monthly_only": True}


def caption(p: dict) -> str:
    """One line under the chart: where the price sits against its averages, RSI, 52-week range, nearest levels."""
    s = p["summary"]
    parts = []
    for n in (50, 200):
        if s.get(f"vs{n}") is not None:
            parts.append(f"{s[f'vs{n}'] * 100:+.0f}% vs {n}-day")
    if s.get("rsi") is not None:
        rsi = s["rsi"]
        parts.append(f"RSI {rsi:.0f}" + (" (oversold)" if rsi < 30 else " (overbought)" if rsi > 70 else ""))
    if p.get("monthly_only"):
        return f"monthly series to {s['date'][:7]}, last {s['last']:,.2f} · " + (p.get("note") or "")
    parts.append(f"52-week {s['low52']:,.2f}–{s['high52']:,.2f}")
    sup = [x for x in p["levels"] if x["kind"] == "support"]
    res = [x for x in p["levels"] if x["kind"] == "resistance"]
    if sup:
        parts.append(f"support {sup[0]['price']:,.2f}")
    if res:
        parts.append(f"resistance {res[0]['price']:,.2f}")
    return " · ".join(parts)
