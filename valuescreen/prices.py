"""Live prices with offline fallback. yfinance is optional; any failure falls back to the price stored in the file."""
from __future__ import annotations

import datetime as dt
import warnings

SPOT_SYMBOLS = {"gold": "GC=F", "silver": "SI=F", "copper": "HG=F"}  # uranium has no free feed: set it in config.yaml


def _yf():
    try:
        import yfinance as yf  # noqa: PLC0415
        return yf
    except ImportError:
        return None


def _last_close(yf, symbol):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        h = yf.Ticker(symbol).history(period="10d", auto_adjust=False)
    if h is None or h.empty:
        return None
    return float(h["Close"].iloc[-1]), h.index[-1].date()


def refresh_prices(companies: dict, tickers: list[str]) -> list[str]:
    """Updates company['price'] in place where a live close is available. Returns log lines."""
    yf = _yf()
    if yf is None:
        return ["yfinance not installed - using prices stored in the company files (pip install yfinance for live prices)"]
    log = []
    for t in tickers:
        c = companies[t]
        try:
            got = _last_close(yf, c["yahoo"])
        except Exception as e:  # noqa: BLE001
            got = None
            log.append(f"{t}: live price failed ({e.__class__.__name__}) - using {c['price']['value']} from {c['price']['date']}")
        if got:
            px, d = got
            c["price"].update(value=px, date=d, source=f"yfinance {c['yahoo']}")
    return log


def refresh_spot(cfg: dict) -> list[str]:
    yf = _yf()
    if yf is None:
        return []
    log = []
    for metal, sym in SPOT_SYMBOLS.items():
        try:
            got = _last_close(yf, sym)
        except Exception:  # noqa: BLE001
            got = None
        if got:
            cfg["spot"][metal] = got[0]
            log.append(f"spot {metal} = {got[0]:,.2f} ({sym}, {got[1]})")
        else:
            log.append(f"spot {metal}: live price unavailable - using {cfg['spot'][metal]} from config.yaml")
    log.append(f"spot uranium = {cfg['spot']['uranium']} (manual, config.yaml)")
    return log


def today():
    return dt.date.today()
