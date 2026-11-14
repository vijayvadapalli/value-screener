"""Technical analysis for the charts: moving averages, RSI, swing points, support / resistance and trend lines.

Pure functions on daily bars ({date, open, high, low, close, volume}, oldest first) – no network, no plotting.

    sma_series(values, n)        simple moving average, None until n values
    rsi_series(closes, n=14)     Wilder's RSI
    pivots(bars, k)              swing highs and lows: the highest high / lowest low within k bars either side
    levels(bars, ...)            horizontal support below and resistance above the last close, from clustered pivots
    trend_lines(bars, ...)       a falling resistance line through lower highs and a rising support line through higher
                                 lows – only when the fit is clean (enough touches, no close through the line since);
                                 the other edge of a channel (rising resistance, falling support) near the price; and a
                                 two-touch line from the year's extreme to the latest turn

Lines and levels are found mechanically and marked "auto" in the reports: a guide to where the price has turned
before, not a forecast.
"""
from __future__ import annotations

import datetime as dt


def sma_series(values, n):
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        out.append(total / n if i >= n - 1 else None)
    return out


def rsi_series(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(b - a, 0.0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0.0) for a, b in zip(closes, closes[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(gains)):
        ag, al = (ag * (n - 1) + gains[i]) / n, (al * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def pivots(bars, k=5):
    """[(index, 'high' | 'low', price)] – a bar whose high (low) is the highest (lowest) within k bars either side."""
    out = []
    for i in range(k, len(bars) - k):
        window = bars[i - k:i + k + 1]
        if bars[i]["high"] == max(b["high"] for b in window):
            out.append((i, "high", bars[i]["high"]))
        if bars[i]["low"] == min(b["low"] for b in window):
            out.append((i, "low", bars[i]["low"]))
    return out


def levels(bars, k=5, lookback=500, tolerance=0.025, keep=3, max_distance=0.4):
    """Horizontal levels where the price turned more than once. Pivots within `tolerance` of each other are merged;
    each level scores by touches, recent touches counting more. Returns {"support": [...], "resistance": [...]}, each
    [{"price", "touches", "last"}] nearest first, at most `keep`, within `max_distance` of the last close."""
    bars = bars[-lookback:]
    if len(bars) < 2 * k + 2:
        return {"support": [], "resistance": []}
    last = bars[-1]["close"]
    clusters = []
    for i, _, price in sorted(pivots(bars, k), key=lambda p: p[2]):
        if clusters and price <= clusters[-1]["top"] * (1 + tolerance):
            c = clusters[-1]
            c["prices"].append(price)
            c["idx"].append(i)
            c["top"] = price
        else:
            clusters.append({"prices": [price], "idx": [i], "top": price})
    out = {"support": [], "resistance": []}
    n = len(bars)
    for c in clusters:
        if len(c["prices"]) < 2:
            continue
        price = sum(c["prices"]) / len(c["prices"])
        if abs(price / last - 1) > max_distance or abs(price / last - 1) < 0.005:
            continue
        score = sum(0.5 + i / n for i in c["idx"])
        item = {"price": price, "touches": len(c["prices"]), "last": bars[max(c["idx"])]["date"], "score": score}
        out["support" if price < last else "resistance"].append(item)
    for side in out:
        best = sorted(out[side], key=lambda x: -x["score"])[:keep]
        out[side] = sorted(best, key=lambda x: abs(x["price"] - last))
        for x in out[side]:
            del x["score"]
    return out


def _line_at(a, b, i):
    (i0, p0), (i1, p1) = a, b
    return p0 + (p1 - p0) * (i - i0) / (i1 - i0)


def trend_lines(bars, k=5, lookback=260, touch=0.02, min_touches=3, max_gap=0.25):
    """Up to two lines: 'resistance' through falling swing highs and 'support' through rising swing lows, over the
    last `lookback` bars. A line needs `min_touches` pivots within `touch` of it, no close more than 1% beyond it
    from its first anchor to today, and today's value within `max_gap` of the last close.
    Returns [{"kind", "from": (date, price), "to": (date, price), "touches"}]."""
    bars = bars[-lookback:]
    if len(bars) < 4 * k:
        return []
    last_i, last = len(bars) - 1, bars[-1]["close"]
    piv = pivots(bars, k)
    found = []
    for kind, side, sign in (("resistance", "high", -1), ("support", "low", 1)):
        pts = [(i, p) for i, s, p in piv if s == side]
        best = None
        for x in range(len(pts)):
            for y in range(x + 1, len(pts)):
                a, b = pts[x], pts[y]
                if (b[1] - a[1]) * sign <= 0 or b[0] - a[0] < 2 * k:   # resistance must fall, support must rise
                    continue
                now = _line_at(a, b, last_i)
                if now <= 0 or abs(now / last - 1) > max_gap:
                    continue
                broken = any((bars[i]["close"] - _line_at(a, b, i)) * -sign > 0.01 * _line_at(a, b, i)
                             for i in range(a[0], last_i + 1))
                if broken:
                    continue
                touches = sum(1 for i, p in pts if i >= a[0] and abs(p / _line_at(a, b, i) - 1) <= touch)
                key = (touches, b[0] - a[0])
                if touches >= min_touches and (best is None or key > best[0]):
                    best = (key, a, b)
        if best:
            (touches, _), a, b = best
            found.append({"kind": kind, "from": (bars[a[0]]["date"], a[1]),
                          "to": (bars[last_i]["date"], _line_at(a, b, last_i)), "touches": touches, "tentative": False})
        channel = _channel_line(bars, piv, side, sign, k, touch, min_touches, max_gap)
        if channel:
            (touches, _), a, b = channel
            found.append({"kind": kind, "from": (bars[a[0]]["date"], a[1]), "to": (bars[last_i]["date"], _line_at(a, b, last_i)),
                          "touches": touches, "tentative": False, "channel": True})
        recent = _recent_line(bars, side, sign, k, touch, max_gap)
        if recent and not (best and best[1][0] == recent[0][0]):   # same starting point: the confirmed line already shows it
            (ia, pa), (ib, pb) = recent
            touches = sum(1 for i, s, p in piv if s == side and i >= ia and abs(p / _line_at((ia, pa), (ib, pb), i) - 1) <= touch)
            found.append({"kind": kind, "from": (bars[ia]["date"], pa), "to": (bars[last_i]["date"], _line_at((ia, pa), (ib, pb), last_i)),
                          "touches": max(touches, 2), "tentative": True})
    return found


def _channel_line(bars, piv, side, sign, k, touch, min_touches, max_gap, k_edge=3, near=0.15, min_move=0.05):
    """The other edge of a channel: a RISING resistance through higher highs, or a FALLING support through lower lows,
    with the same tests as the main lines (`min_touches` swing points within `touch`, no close more than 1% through it
    since its first point). The latest swing counts after `k_edge` bars. Stricter, so it stays a guide and not noise:
    today's value within `near` of the last close, and a move of at least `min_move` between its two points.
    Returns ((touches, span), a, b) or None."""
    max_gap = min(max_gap, near)
    last_i, last = len(bars) - 1, bars[-1]["close"]
    pts = [(i, p) for i, s, p in piv if s == side] + _edge_pivots(bars, side, k, k_edge)
    best = None
    for x in range(len(pts)):
        for y in range(x + 1, len(pts)):
            a, b = pts[x], pts[y]
            if (b[1] / a[1] - 1) * -sign < min_move or b[0] - a[0] < 2 * k:   # resistance must rise, support must fall
                continue
            now = _line_at(a, b, last_i)
            if now <= 0 or abs(now / last - 1) > max_gap:
                continue
            if any((bars[i]["close"] - _line_at(a, b, i)) * -sign > 0.01 * _line_at(a, b, i) for i in range(a[0], last_i + 1)):
                continue
            touches = sum(1 for i, p in pts if i >= a[0] and abs(p / _line_at(a, b, i) - 1) <= touch)
            key = (touches, b[0] - a[0])
            if touches >= min_touches and (best is None or key > best[0]):
                best = (key, a, b)
    return best


def _edge_pivots(bars, side, k, k_edge):
    """Swing points in the last k bars, confirmed by only `k_edge` bars after them (a turn the full rule sees later)."""
    n, out = len(bars), []
    for i in range(max(k, n - k), n - k_edge):
        window = bars[i - k:i + k + 1]
        if side == "high" and bars[i]["high"] == max(b["high"] for b in window):
            out.append((i, bars[i]["high"]))
        if side == "low" and bars[i]["low"] == min(b["low"] for b in window):
            out.append((i, bars[i]["low"]))
    return out


def _recent_line(bars, side, sign, k, touch, max_gap, window=260, k_edge=3, min_move=0.05):
    """The line a chartist draws from the big turn of the last year to the latest swing: from the lowest swing low to
    the latest higher low (support), or from the highest swing high to the latest lower high (resistance). When that
    line has been broken, the next most extreme turn is tried, and so on. Two touches are enough, but the second point
    must be at least `min_move` away from the first and no close may have gone more than 1% through the line since.
    Returns ((i, price), (i, price)) or None."""
    last_i, last = len(bars) - 1, bars[-1]["close"]
    pts = [(i, p) for i, s, p in pivots(bars, k) if s == side and i >= last_i - window] + _edge_pivots(bars, side, k, k_edge)
    for a in sorted(pts, key=lambda x: (x[1] * sign, -x[0])):   # the lowest low / highest high first, later on a tie
        later = [p for p in pts if p[0] - a[0] >= 2 * k and (p[1] / a[1] - 1) * sign >= min_move]
        if not later:
            continue
        b = max(later, key=lambda x: x[0])                       # the latest higher low / lower high
        now = _line_at(a, b, last_i)
        if now <= 0 or abs(now / last - 1) > max_gap:
            continue
        if any((bars[i]["close"] - _line_at(a, b, i)) * -sign > 0.01 * _line_at(a, b, i) for i in range(a[0], last_i + 1)):
            continue
        return a, b
    return None


def summary(bars) -> dict:
    """The latest values for the chart's caption: price vs each average, RSI, 52-week high and low."""
    closes = [b["close"] for b in bars]
    if not closes:
        return {}
    last = closes[-1]
    out = {"last": last, "date": bars[-1]["date"]}
    for n in (20, 50, 200):
        s = sma_series(closes, n)[-1]
        out[f"sma{n}"] = s
        out[f"vs{n}"] = last / s - 1 if s else None
    out["rsi"] = rsi_series(closes)[-1]
    year = [b for b in bars if b["date"] >= (dt.date.fromisoformat(bars[-1]["date"]) - dt.timedelta(days=365)).isoformat()]
    out["high52"] = max(b["high"] for b in year)
    out["low52"] = min(b["low"] for b in year)
    return out
