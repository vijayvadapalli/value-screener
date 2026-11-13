"""Before-buying checks (Valuation Playbook): price against its 200-day average, RSI and MACD.

Pure functions on a list of daily closes, plus an optional yfinance fetch. Only used with `run --technicals`.
"""
from __future__ import annotations

import warnings


def sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def ema_series(xs, n):
    k, out = 2 / (n + 1), []
    for x in xs:
        out.append(x if not out else x * k + out[-1] * (1 - k))
    return out


def rsi(closes, n=14):
    """Wilder's RSI on the last close."""
    if len(closes) <= n:
        return None
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd(closes, fast=12, slow=26, signal=9):
    """(macd line, signal line, histogram) on the last close."""
    if len(closes) < slow + signal:
        return None
    line = [a - b for a, b in zip(ema_series(closes, fast), ema_series(closes, slow))]
    sig = ema_series(line, signal)
    return line[-1], sig[-1], line[-1] - sig[-1]


def read(closes):
    """The checks and a one-line read-across for the playbook's buying rules."""
    if not closes:
        return None
    last, ma200, r, m = closes[-1], sma(closes, 200), rsi(closes), macd(closes)
    out = dict(last=last, ma200=ma200, rsi=r, macd=m, below_200=ma200 is not None and last < ma200)
    notes = []
    if ma200 is not None:
        notes.append(f"{(last / ma200 - 1) * 100:+.0f}% vs 200-day")
        if out["below_200"]:
            notes.append("below 200-day: buy in thirds")
    if r is not None:
        notes.append(f"RSI {r:.0f}" + (" (oversold – pullback)" if r < 30 else " (overbought)" if r > 70 else ""))
    if m is not None:
        notes.append("MACD " + ("rising" if m[2] > 0 else "falling"))
    out["note"] = " · ".join(notes)
    return out


def fetch(symbol):
    """About 15 months of daily closes from yfinance, or None."""
    try:
        import yfinance as yf  # noqa: PLC0415
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            h = yf.Ticker(symbol).history(period="15mo", auto_adjust=False)
        return None if h is None or h.empty else [float(x) for x in h["Close"].dropna()]
    except Exception:  # noqa: BLE001 - optional data
        return None
