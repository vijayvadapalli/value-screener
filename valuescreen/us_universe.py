"""The S&P 500 and Nasdaq-100 constituents, from their Wikipedia lists (maintained, free, with sectors).

    universe(cik_by_ticker) → [{"ticker", "yahoo", "name", "sector", "industry", "cik", "isin", "indexes", "foreign"}]

The S&P 500 table carries each company's SEC CIK and GICS sector; the Nasdaq-100 table carries an ISIN and an ICB
industry, which is mapped to the nearest GICS sector. A company in both lists appears once with both indexes.
`foreign` marks companies with no SEC CIK. Companies that have a CIK but file foreign (20-F, IFRS) reports – ADRs such
as ASML or Arm – are found later, when the SEC data has no US-GAAP figures for them; both use Yahoo's figures instead.
"""
from __future__ import annotations

import urllib.request

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
UA = "Mozilla/5.0 (compatible; value-screener)"
ICB_TO_GICS = {"Technology": "Information Technology", "Telecommunications": "Communication Services",
               "Basic Materials": "Materials", "Health Care": "Health Care", "Financials": "Financials",
               "Real Estate": "Real Estate", "Energy": "Energy", "Utilities": "Utilities", "Industrials": "Industrials",
               "Consumer Discretionary": "Consumer Discretionary", "Consumer Staples": "Consumer Staples"}


def _rows(url, table_id="constituents"):
    from bs4 import BeautifulSoup  # noqa: PLC0415 - optional dependency
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        soup = BeautifulSoup(resp.read(), "lxml")
    table = soup.select_one(f"table#{table_id}")
    if table is None:
        raise ValueError(f"no '{table_id}' table on {url} – the page layout may have changed")
    trs = table.select("tr")
    head = [c.get_text(" ", strip=True).split(" [")[0] for c in trs[0].select("th")]
    return [dict(zip(head, [c.get_text(" ", strip=True) for c in tr.select("td,th")])) for tr in trs[1:] if tr.select("td")]


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")   # BRK.B → BRK-B


def sp500() -> list[dict]:
    return [{"ticker": r["Symbol"], "name": r["Security"], "sector": r.get("GICS Sector"), "industry": r.get("GICS Sub-Industry"),
             "cik": int(r["CIK"]) if r.get("CIK", "").isdigit() else None, "isin": None, "index": "S&P 500"}
            for r in _rows(SP500_URL)]


def nasdaq100() -> list[dict]:
    return [{"ticker": r["Ticker"], "name": r["Company"], "sector": ICB_TO_GICS.get(r.get("ICB Industry"), r.get("ICB Industry")),
             "industry": r.get("ICB Subsector"), "cik": None, "isin": r.get("ISIN"), "index": "Nasdaq-100"}
            for r in _rows(NASDAQ100_URL)]


def universe(cik_by_ticker: dict | None = None) -> list[dict]:
    """Both lists merged by ticker; CIKs for Nasdaq-only names come from the SEC's ticker map when given."""
    cik_by_ticker = cik_by_ticker or {}
    merged = {}
    for r in sp500() + nasdaq100():
        e = merged.setdefault(r["ticker"], {"ticker": r["ticker"], "yahoo": yahoo_symbol(r["ticker"]), "name": r["name"],
                                            "sector": r["sector"], "industry": r["industry"], "cik": r["cik"], "isin": r["isin"],
                                            "indexes": []})
        e["indexes"].append(r["index"])
        e["cik"] = e["cik"] or r["cik"] or cik_by_ticker.get(yahoo_symbol(r["ticker"]).upper())
        e["isin"] = e["isin"] or r["isin"]
    for e in merged.values():
        e["foreign"] = e["cik"] is None
    return sorted(merged.values(), key=lambda e: e["ticker"])
