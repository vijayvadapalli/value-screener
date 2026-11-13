"""Reading Screener.in company pages (the Valuation Playbook's source for Indian companies).

Used by tools/fetch_screener.py (Nifty v2 data) and tools/profit_vs_price.py (3-year growth). Needs beautifulsoup4
and lxml. Screener's pages are public; `get` waits and retries when it says we are going too fast.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "https://www.screener.in/company/{symbol}/{view}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; value-screener)"}
PAUSE_SECONDS = 4.0           # between pages
RETRY_WAITS = (30, 60, 120)   # seconds to wait after "429 Too Many Requests" before trying again
MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}


def url(symbol: str, consolidated: bool = True) -> str:
    return URL.format(symbol=urllib.parse.quote(symbol), view="consolidated/" if consolidated else "")


def get(page_url: str) -> str:
    """One page, waiting and retrying when Screener rate-limits us."""
    for wait in RETRY_WAITS + (None,):
        try:
            with urllib.request.urlopen(urllib.request.Request(page_url, headers=HEADERS), timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            retry_after = e.headers.get("Retry-After")
            time.sleep(int(retry_after) if retry_after and retry_after.isdigit() else wait)
    raise RuntimeError("unreachable")


def number(text):
    """'3,55,969' → 355969.0; '29.3 %' → 29.3; '' or '-' → None."""
    t = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(t)
    except ValueError:
        return None


def month_end(label):
    """'Sep 2026' → 2026-09-30."""
    mon, year = label.split()
    y, m = int(year), MONTHS[mon[:3]]
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def soup_of(html: str):
    from bs4 import BeautifulSoup  # noqa: PLC0415 - optional dependency
    return BeautifulSoup(html, "lxml")


def table(soup, section):
    """(column headers, {row name: [numbers]}) for one of the page's data tables."""
    t = soup.select_one(f"section#{section} table.data-table")
    if t is None:
        return [], {}
    headers = [th.get_text(strip=True) for th in t.select("thead th")][1:]
    rows = {}
    for tr in t.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if cells:
            rows[cells[0].replace("+", "").strip()] = [number(x) for x in cells[1:]]
    return headers, rows


def top_ratio(soup, name):
    for li in soup.select("#top-ratios li"):
        text = " ".join(li.get_text(" ", strip=True).split())
        if text.startswith(name):
            return number(text[len(name):].split("/")[0])
    return None


def growth_range(soup, title, period):
    """A figure from the 'Compounded Sales Growth' style boxes, e.g. ('Return on Equity', '5 Years') → 32.0."""
    for t in soup.select("table.ranges-table"):
        cells = [x.get_text(" ", strip=True) for x in t.select("th, td")]
        if cells and cells[0] == title and f"{period}:" in cells:
            return number(cells[cells.index(f"{period}:") + 1])
    return None


def parse_v2(html: str) -> dict:
    """The figures the Nifty v2 rules need (see valuescreen/v2.py)."""
    soup = soup_of(html)
    q_head, quarters = table(soup, "quarters")
    y_head, annual = table(soup, "profit-loss")
    c_head, cash = table(soup, "cash-flow")
    if "EPS in Rs" not in quarters or "EPS in Rs" not in annual:
        raise ValueError("no EPS rows on the page")
    eps_by_year = dict(zip(y_head, annual["EPS in Rs"]))
    profit_by_year = dict(zip(y_head, annual.get("Net Profit", [])))
    cfo_by_year = dict(zip(c_head, cash.get("Cash from Operating Activity", [])))
    years = [y for y in y_head if y != "TTM" and eps_by_year.get(y) is not None][-10:]   # skip blank years
    both = [y for y in years if profit_by_year.get(y) is not None and cfo_by_year.get(y) is not None][-5:]
    roe = growth_range(soup, "Return on Equity", "5 Years")
    return {
        "price": top_ratio(soup, "Current Price"), "market_cap_cr": top_ratio(soup, "Market Cap"),
        "book_value_ps": top_ratio(soup, "Book Value"), "roe_5y": None if roe is None else roe / 100,
        "quarters": q_head[-8:], "eps_quarters": quarters["EPS in Rs"][-8:],
        "years": years, "eps_annual": [eps_by_year[y] for y in years],
        "profit_annual": [profit_by_year[y] for y in both], "cfo_annual": [cfo_by_year[y] for y in both],
    }


def parse_growth(html: str) -> dict:
    """Screener's 3-year compounded growth figures plus the yearly sales and profit they come from (₹ crore)."""
    soup = soup_of(html)
    y_head, annual = table(soup, "profit-loss")
    sales_row = annual.get("Sales") or annual.get("Revenue") or []
    profit_row = annual.get("Net Profit") or []
    pct = lambda title, period: (lambda x: None if x is None else x / 100)(growth_range(soup, title, period))  # noqa: E731
    years = [y for y in y_head if y != "TTM"]
    base = years[-4] if len(years) >= 4 else None   # three financial years before the latest
    by_year = lambda row: dict(zip(y_head, row))  # noqa: E731
    return {
        "price": top_ratio(soup, "Current Price"), "pe_now": top_ratio(soup, "Stock P/E"),
        "sales_growth_3y": pct("Compounded Sales Growth", "3 Years"),
        "profit_growth_3y": pct("Compounded Profit Growth", "3 Years"),
        "profit_growth_ttm": pct("Compounded Profit Growth", "TTM"),
        "price_growth_3y": pct("Stock Price CAGR", "3 Years"), "price_change_1y": pct("Stock Price CAGR", "1 Year"),
        "roe_3y": pct("Return on Equity", "3 Years"),
        "base_label": base, "latest_label": years[-1] if years else None,
        "sales_then": by_year(sales_row).get(base), "sales_now": by_year(sales_row).get("TTM"),
        "profit_then": by_year(profit_row).get(base), "profit_now": by_year(profit_row).get("TTM"),
    }
