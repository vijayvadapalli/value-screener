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
from concurrent.futures import ThreadPoolExecutor
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


_FX = {}


def fx_rate(frm: str, to: str):
    """How many `to` per one `frm`, from Yahoo's latest close (cached for the run); None if Yahoo has no rate."""
    if frm == to:
        return 1.0
    if (frm, to) not in _FX:
        import yfinance as yf  # noqa: PLC0415
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            h = yf.Ticker(f"{frm}{to}=X").history(period="5d")["Close"].dropna()
        _FX[(frm, to)] = float(h.iloc[-1]) if len(h) else None
    return _FX[(frm, to)]


def _latest(frame, *names):
    """(value, date) from the most recent column of a balance sheet."""
    values = _series(frame, *names)
    if not values:
        return None, None
    d = max(values)
    return values[d], d


def yahoo_record(symbol: str) -> dict:
    """One company's figures from Yahoo: price history, the latest twelve months and the year about three years back
    (for profit vs price), and the cash-flow and balance-sheet figures the quick screens use. Money in full units of
    the statements' currency (`report_ccy`); `fx` converts it to the price currency."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = yf.Ticker(symbol)
        info = t.info or {}
        income, quarterly = t.income_stmt, t.quarterly_income_stmt
        cash_flow, quarterly_cash = t.cashflow, t.quarterly_cashflow
        balance = t.quarterly_balance_sheet
        if balance is None or balance.empty:
            balance = t.balance_sheet
        history = t.history(period="6y", auto_adjust=False)["Close"].dropna()
    closes = [(ts.date(), float(v)) for ts, v in history.items()]
    currency = info.get("currency") or "USD"
    divisor = 100.0 if currency in ("GBp", "GBX") else 1.0   # London prices in pence
    currency = "GBP" if divisor == 100 else currency
    report_ccy = info.get("financialCurrency") or currency
    rec = {"source": "yahoo", "symbol": symbol, "currency": currency, "report_ccy": report_ccy,
           "name": info.get("longName") or info.get("shortName") or symbol, "pe_now": info.get("trailingPE"),
           "roe": info.get("returnOnEquity"), "shares": info.get("sharesOutstanding"), "ebitda": info.get("ebitda"),
           "book_value_ps": info.get("bookValue"), "sector": info.get("sector"), "industry": info.get("industry")}
    if not closes:
        return {**rec, "nm_reason": "no price history"}
    rec.update(price=closes[-1][1] / divisor, price_date=closes[-1][0].isoformat())
    year_ago = _close_on_or_before(closes, closes[-1][0] - dt.timedelta(days=365))
    rec["price_change_1y"] = closes[-1][1] / year_ago - 1 if year_ago else None
    rec["fx"] = fx_rate(report_ccy, currency)    # statements' currency → price currency
    rec["usd"] = fx_rate(currency, "USD")         # price currency → US$, for market value

    # the latest twelve months (four consecutive quarters, else the latest year) for the screen
    def ttm(names, frame_q, frame_y):
        return _latest_twelve_months(_series(frame_q, *names), _series(frame_y, *names))
    revenue_names, profit_names = ("Total Revenue",), ("Net Income Common Stockholders", "Net Income")
    ocf_names = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Cash Flowsfromusedin Operating Activities Direct")
    da_names = ("Depreciation And Amortization", "Depreciation Amortization Depletion", "Depreciation")
    revenue_now, end, label = ttm(revenue_names, quarterly, income)
    cash, balance_date = _latest(balance, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    debt, _ = _latest(balance, "Total Debt")
    rec.update(sales_now=revenue_now, profit_now=ttm(profit_names, quarterly, income)[0],
               ocf_ttm=ttm(ocf_names, quarterly_cash, cash_flow)[0], capex_ttm=ttm(("Capital Expenditure",), quarterly_cash, cash_flow)[0],
               da_ttm=ttm(da_names, quarterly_cash, cash_flow)[0] or ttm(("Reconciled Depreciation",), quarterly, income)[0], cash=cash, debt=debt or 0.0,
               balance_date=balance_date.isoformat() if balance_date else None, ttm_label=label,
               ttm_end=end.isoformat() if end else None)

    # profit vs price: diluted EPS about three years back against the latest twelve months
    eps_year = _series(income, "Diluted EPS", "Basic EPS")
    eps_now, end, label = _latest_twelve_months(_series(quarterly, "Diluted EPS", "Basic EPS"), eps_year)
    base, base_note = _base_year(eps_year, end) if end else (None, None)
    if base is None:
        return {**rec, "nm_reason": "less than two years of statements"}
    revenue_year, profit_year = _series(income, *revenue_names), _series(income, *profit_names)
    rec.update(years=(end - base).days / 365.25, base_label=f"FY{base:%y}", latest_label=label, note=base_note,
               eps_then=eps_year[base], eps_now=eps_now, sales_then=revenue_year.get(base), profit_then=profit_year.get(base),
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


def collect(entries: list[dict], companies: dict, folder: str | None, cache_file: Path, refresh: bool = False, log=print,
            workers: int = 4) -> dict:
    """{ticker: raw figures} for every entry, from today's cache where possible. Yahoo companies are fetched `workers`
    at a time; Screener.in pages one by one with a pause. Failures are logged and left out."""
    cache = {} if refresh or not cache_file.exists() else json.loads(cache_file.read_text())
    todo = [e for e in entries if e["ticker"] not in cache]
    if todo:
        log(f"fetching {len(todo)} companies ({len(entries) - len(todo)} from today's cache)")
    indian = [e for e in todo if is_indian(e, companies.get(e["ticker"]), folder)]
    others = [e for e in todo if e not in indian]

    def save():
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))

    def symbol(entry):
        return (companies.get(entry["ticker"]) or {}).get("yahoo") or entry.get("yahoo") or entry["ticker"]

    blocked = []   # set once Yahoo rate-limits us: the rest are skipped rather than hammered

    def fetch(entry):
        if blocked:
            return entry["ticker"], None, None
        try:
            return entry["ticker"], yahoo_record(symbol(entry)), None
        except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the run
            if "Too Many Requests" in str(e) or "Rate limited" in str(e):
                blocked.append(entry["ticker"])
            return entry["ticker"], None, e

    with ThreadPoolExecutor(workers) as pool:
        for i, (ticker, rec, err) in enumerate(pool.map(fetch, others), 1):
            if rec is not None:
                cache[ticker] = rec
            elif err and not blocked:
                log(f"{ticker} failed ({err})")
            if i % 25 == 0:
                save()
    if blocked:
        log(f"Yahoo is rate-limiting this computer: {sum(1 for e in others if e['ticker'] not in cache)} companies not fetched. "
            "Run again in 15–60 minutes; today's cache keeps everything already fetched.")
    for n, entry in enumerate(indian):
        if n:
            time.sleep(screener.PAUSE_SECONDS)
        try:
            cache[entry["ticker"]] = screener_record(entry["ticker"])
        except Exception as e:  # noqa: BLE001
            log(f"{entry['ticker']} failed ({e})")
            continue
        save()
    if todo:
        save()
    return cache
