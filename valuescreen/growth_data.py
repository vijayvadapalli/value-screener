"""Fetching the figures for the profit-vs-price comparison (see profit_vs_price.py for the method).

Indian companies come from Screener.in's 3-year growth figures; everything else from Yahoo Finance statements
(needs yfinance). collect() caches the raw figures per list and day, so a second run the same day fetches nothing.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import warnings
from pathlib import Path

from . import screener

THREE_YEARS = 3 * 365.25
MIN_YEARS = 1.5          # a base year closer than this to the latest figures is too short to compare


# ------------------------------------------------------------------------------------------------- Yahoo
def _series(frame, *names):
    """{date: value} for the first row name that has figures, NaNs dropped."""
    if frame is None or frame.empty:
        return {}
    for name in names:
        if name in frame.index:
            row = frame.loc[name].dropna()
            if len(row):
                return {col.date(): float(v) for col, v in row.items()}
    return {}


def _latest_twelve_months(quarterly, annual):
    """(value, end date, label): the last four quarters added up when they are consecutive, else the latest full year."""
    dates = sorted(quarterly)[-4:]
    if len(dates) == 4 and all(80 <= (b - a).days <= 100 for a, b in zip(dates, dates[1:])):
        return sum(quarterly[d] for d in dates), dates[-1], f"TTM {dates[-1]:%b %y}"
    if annual:
        end = max(annual)
        return annual[end], end, f"FY{end:%y}"
    return None, None, None


def _base_year(annual, end):
    """The financial year closest to three years before `end`. If that year was a loss, the nearest later profitable
    year (at least 1.5 years back) – growth from a loss means nothing. Returns (date, note)."""
    candidates = sorted((d for d in annual if (end - d).days >= MIN_YEARS * 365.25), key=lambda d: abs((end - d).days - THREE_YEARS))
    if not candidates:
        return None, None
    first = candidates[0]
    if annual[first] > 0:
        return first, None
    later = [d for d in candidates if d > first and annual[d] > 0]
    if later:
        return min(later), f"FY{first:%y} was a loss, so this starts from FY{min(later):%y}"
    return first, None


def _close_on_or_before(closes, day):
    earlier = [(d, v) for d, v in closes if d <= day]
    return earlier[-1][1] if earlier else None


def yahoo_record(symbol: str) -> dict:
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = yf.Ticker(symbol)
        info = t.info or {}
        income, quarterly = t.income_stmt, t.quarterly_income_stmt
        history = t.history(period="6y", auto_adjust=False)["Close"].dropna()
    closes = [(ts.date(), float(v)) for ts, v in history.items()]
    currency = info.get("currency") or "USD"
    divisor = 100.0 if currency in ("GBp", "GBX") else 1.0   # London prices in pence
    currency = "GBP" if divisor == 100 else currency
    rec = {"source": "yahoo", "symbol": symbol, "currency": currency, "report_ccy": info.get("financialCurrency") or currency,
           "name": info.get("shortName") or symbol, "pe_now": info.get("trailingPE"), "roe": info.get("returnOnEquity")}
    if not closes:
        return {**rec, "nm_reason": "no price history"}
    rec.update(price=closes[-1][1] / divisor, price_date=closes[-1][0].isoformat())
    year_ago = _close_on_or_before(closes, closes[-1][0] - dt.timedelta(days=365))
    rec["price_change_1y"] = closes[-1][1] / year_ago - 1 if year_ago else None

    eps_year = _series(income, "Diluted EPS", "Basic EPS")
    eps_now, end, label = _latest_twelve_months(_series(quarterly, "Diluted EPS", "Basic EPS"), eps_year)
    base, base_note = _base_year(eps_year, end) if end else (None, None)
    if base is None:
        return {**rec, "nm_reason": "less than two years of statements"}
    revenue_year, profit_year = _series(income, "Total Revenue"), _series(income, "Net Income Common Stockholders", "Net Income")
    rec.update(
        years=(end - base).days / 365.25, base_label=f"FY{base:%y}", latest_label=label, note=base_note,
        eps_then=eps_year[base], eps_now=eps_now,
        sales_then=revenue_year.get(base), sales_now=_latest_twelve_months(_series(quarterly, "Total Revenue"), revenue_year)[0],
        profit_then=profit_year.get(base),
        profit_now=_latest_twelve_months(_series(quarterly, "Net Income Common Stockholders", "Net Income"), profit_year)[0],
        price_then=(_close_on_or_before(closes, base) or 0) / divisor or None)
    return rec


# ------------------------------------------------------------------------------------------------- Screener.in
def screener_record(symbol: str) -> dict:
    data, page = None, None
    for consolidated in (True, False):
        page = screener.url(symbol, consolidated)
        data = screener.parse_growth(screener.get(page))
        if data["profit_growth_3y"] is not None or data["price_growth_3y"] is not None:
            break
        time.sleep(screener.PAUSE_SECONDS)
    base = data["base_label"]
    return {**data, "source": "screener", "symbol": symbol, "page": page, "currency": "INR", "report_ccy": "INR",
            "roe": data["roe_3y"], "years": 3.0, "price_date": dt.date.today().isoformat(),
            "base_label": f"FY{base[-2:]}" if base else None, "latest_label": "TTM"}


# ------------------------------------------------------------------------------------------------- one list
def is_indian(entry: dict, company: dict | None, folder: str | None) -> bool:
    symbol = (company or {}).get("yahoo") or entry.get("yahoo") or ""
    return folder == "nifty50" or symbol.endswith((".NS", ".BO")) or (company or {}).get("currency") == "INR"


def collect(entries: list[dict], companies: dict, folder: str | None, cache_file: Path, refresh: bool = False, log=print) -> dict:
    """{ticker: raw figures} for every entry, from today's cache where possible. Failures are logged and left out."""
    cache = {} if refresh or not cache_file.exists() else json.loads(cache_file.read_text())
    todo = [e for e in entries if e["ticker"] not in cache]
    if todo:
        log(f"profit vs price: fetching {len(todo)} companies ({len(entries) - len(todo)} from today's cache)")
    fetched_indian = False
    for entry in todo:
        company = companies.get(entry["ticker"])
        try:
            if is_indian(entry, company, folder):
                if fetched_indian:
                    time.sleep(screener.PAUSE_SECONDS)
                cache[entry["ticker"]] = screener_record(entry["ticker"])
                fetched_indian = True
            else:
                cache[entry["ticker"]] = yahoo_record((company or {}).get("yahoo") or entry.get("yahoo") or entry["ticker"])
        except Exception as e:  # noqa: BLE001 - one bad page must not stop the report
            log(f"profit vs price: {entry['ticker']} failed ({e})")
            continue
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return cache
