"""Price charts for the company sections: the data for the interactive HTML chart, and a static PNG for the PDF.

Both show RSI(14) above candles with the 20-, 50- and 200-day averages, support / resistance and trend lines found
automatically (chart_levels.py), and our own valuation on the price: the value lines, buy / add levels and the start
of the sell zone, with results (E) and dividend (D) markers. Prices come from output/prices.sqlite (pricedb.py).

    payload(con, symbol, r, c)   → dict for the HTML chart (JSON), or None when there is no history
    static_png(p, path)          → PNG path for the PDF from a payload, or None
"""
from __future__ import annotations

import datetime as dt

from . import chart_levels as L
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


LIGHT_GREEN, DARK_GREEN = "#2FA36B", "#0B5D3F"


def value_lines(r: dict) -> list[dict]:
    """Our valuation drawn on the price, as solid lines: the fair value (15x, 13x for oil; the buy level for growth,
    developers and holders) in green, the cautious value (12x, 10x; NAV; value with no growth) in darker green, and
    the start of the sell zone (25x) in red. A separate buy level (20% below the cautious value, tiers B and C) is
    dashed green. [{"price", "label", "kind", "color", "solid"}]."""
    m = r["model"]
    sell = f"{r['sell_multiple']:g}x sell zone" if r.get("sell_multiple") else "Sell zone"
    if m in ("producer", "cashflow"):
        lo, hi = r.get("mult_lo"), r.get("mult_hi")
        items = [(r.get("v_high"), f"{hi:g}x value" if hi else "Fair value", "value", LIGHT_GREEN, True),
                 (r.get("v_low"), f"{lo:g}x value" if lo else "Value", "value", DARK_GREEN, True),
                 (r.get("buy_level"), "start" if r.get("tier") == "A" else "Buy (20% below)", "buy", LIGHT_GREEN, False),
                 (r.get("add_level"), "add", "add", DARK_GREEN, False),
                 (r.get("call_level"), sell, "sell", S.SIGNAL["red"], True)]
    elif m == "growth":
        items = [(r.get("buy_level"), f"Buy (≤ {r.get('growth_buy', 0.05) * 100:.0f}% growth)", "buy", LIGHT_GREEN, True),
                 (r.get("v0"), "Value, no growth", "value", DARK_GREEN, True),
                 (r.get("call_level"), "Sell zone (25% growth)", "sell", S.SIGNAL["red"], True)]
    elif m in ("developer", "physical", "leases"):
        items = [(r.get("buy_level"), "Buy", "buy", LIGHT_GREEN, True),
                 (r.get("nav") or r.get("v_low"), "NAV" if m != "leases" else "Value", "value", DARK_GREEN, True),
                 (r.get("call_level"), "Sell zone", "sell", S.SIGNAL["red"], True)]
    else:
        items = []
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
            patterns: list | None = None) -> dict | None:
    bars, currency, factor = _scaled(con, symbol)
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
        "markers": _markers(con, symbol, c, factor, l_start),
        "summary": {k: (_r(v) if isinstance(v, float) else v) for k, v in L.summary(bars).items()},
        "signal": r.get("signal"), "action": r.get("action"),
        "watched": [{"lo": _r(x["lo"]), "hi": _r(x["hi"]), "kind": x["kind"], "tf": x.get("tf", "D")} for x in (watched or [])],
        "watched_label": watched_label, "mode": mode, "patterns": patterns or [],
    }
    return out


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


# ------------------------------------------------------------------------------------------------- static chart (PDF)
def static_png(p: dict | None, path, width_in=7.4, height_in=3.3, dpi=150):
    if not p:
        return None
    symbol = p["symbol"]
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from matplotlib.patches import Rectangle  # noqa: PLC0415

    plt.rcParams["font.family"] = S.font_family()
    rows = p["D"]
    closes = [x[4] for x in rows]
    smas = {n: L.sma_series(closes, n) for n in SMA_COLOURS}
    rsi = L.rsi_series(closes)
    first = next(i for i, x in enumerate(rows) if x[0] >= p["show_from"])
    rows, closes = rows[first:], closes[first:]
    xs = range(len(rows))
    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 4.4], hspace=0.05)
    axr, ax = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    for a in (ax, axr):
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(S.LINE)
        a.tick_params(colors=S.INK2, labelsize=6.5, length=2)
        a.set_xlim(-1, len(rows) + 1)
    up, down = S.SIGNAL["green"], S.SIGNAL["red"]
    for i, (_, o, h, lo, cl, v) in enumerate(rows):
        col = up if cl >= o else down
        ax.plot([i, i], [lo, h], color=col, lw=0.5)
        ax.add_patch(Rectangle((i - 0.32, min(o, cl)), 0.64, max(abs(cl - o), 1e-9), color=col, lw=0))
    for n, col in SMA_COLOURS.items():
        ys = smas[n][first:]
        ax.plot([i for i, y in zip(xs, ys) if y], [y for y in ys if y], color=col, lw={20: 0.8, 50: 1.4, 200: 1.9}[n], label=f"SMA {n}")
    lo_y, hi_y = min(x[3] for x in rows), max(x[2] for x in rows)
    span = hi_y - lo_y
    in_view = lambda y: lo_y - 0.25 * span <= y <= hi_y + 0.25 * span  # noqa: E731
    for lvl in nearest_levels(p):
        if in_view(lvl["price"]):
            colour = S.SIGNAL["green"] if lvl["kind"] == "support" else S.SIGNAL["red"]
            ax.axhline(lvl["price"], color=colour, lw=0.7, ls=(0, (1, 2)))
            ax.text(len(rows) + 2, lvl["price"], f"{lvl['kind']} {lvl['price']:,.2f}", fontsize=5.3, color=colour, va="center", ha="left")
    for v in p["values"]:
        if in_view(v["price"]):
            ax.axhline(v["price"], color=v["color"], lw=1.1 if v["solid"] else 0.9, ls="-" if v["solid"] else (0, (4, 2)))
            ax.text(1, v["price"], f" {v['label']} {v['price']:,.2f}", fontsize=5.8, color=v["color"], va="bottom", weight="bold")
    index = {x[0]: i for i, x in enumerate(rows)}
    for t in p["trends"]:
        if t["from"][0] in index or t["from"][0] < rows[0][0]:
            d0 = dt.date.fromisoformat(t["from"][0])
            d1 = dt.date.fromisoformat(t["to"][0])
            day_i = lambda d: next((i for i, x in enumerate(rows) if x[0] >= d.isoformat()), len(rows) - 1)  # noqa: E731
            i0, i1 = day_i(d0), day_i(d1)
            slope = (t["to"][1] - t["from"][1]) / max((d1 - d0).days, 1)
            y0 = t["from"][1] + slope * (dt.date.fromisoformat(rows[i0][0]) - d0).days
            ax.plot([i0, i1], [y0, t["to"][1]], color="#B794F4" if t["kind"] == "resistance" else "#4299E1", lw=1.1)
    ax.axhline(closes[-1], color=S.PRICE, lw=0.7)
    ax.text(len(rows) + 2, closes[-1], f"{closes[-1]:,.2f}", fontsize=5.8, color=S.PRICE, va="center", ha="left", weight="bold")
    ax.set_ylim(lo_y - 0.06 * span, hi_y + 0.06 * span)
    axr.set_xticks([])
    r_vals = rsi[first:]
    axr.plot([i for i, y in zip(xs, r_vals) if y is not None], [y for y in r_vals if y is not None], color=S.SIGNAL["blue"], lw=0.8)
    for y, col in ((70, S.SIGNAL["red"]), (30, S.SIGNAL["green"])):
        axr.axhline(y, color=col, lw=0.5, ls="--")
    axr.set_ylim(0, 100)
    axr.set_yticks([30, 70])
    ticks = [i for i, x in enumerate(rows) if i == 0 or x[0][5:7] != rows[i - 1][0][5:7]][::2]
    ax.set_xticks(ticks)
    ax.set_xticklabels([dt.date.fromisoformat(rows[i][0]).strftime("%b %y") for i in ticks])
    axr.text(1, 92, "RSI(14)", fontsize=5.5, color=S.INK2, va="top")
    ccy = p["currency"] or ""
    axr.set_title(f"{symbol} · daily, 1 year · {ccy} · last {closes[-1]:,.2f}", fontsize=7.5, loc="left", color=S.INK)
    ax.legend(loc="upper left", fontsize=5.5, frameon=False, ncol=3, bbox_to_anchor=(0, 1.0))
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path
