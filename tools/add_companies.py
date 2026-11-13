"""Draft company files from Yahoo's reported statements, for companies you pick by hand, and a list to run them as.

    python tools/add_companies.py oil XOM COP EOG TPL SU.TO CNQ.TO CVE.TO IMO.TO TOU.TO ARX.TO WCP.TO PEY.TO PSK.TO
    python -m valuescreen run --list oil

Writes data/companies/<ticker>.yaml for each company that has no file yet (existing files are never touched) and
data/lists/<list>.yaml with every ticker given, plus any already listed there. The ticker is the symbol without its
exchange suffix (SU.TO → SU); the `yahoo:` field keeps the full symbol for prices.

Model `cashflow` (10x / 13x, for oil & gas and other cyclicals): owner earnings = operating cash flow excluding
working-capital moves − all capex, from Yahoo's annual and quarterly cash-flow statements.
- `earnings`: the latest twelve months (four consecutive quarters, else the latest year).
- `earnings_normalised`: the average of the last four financial years – the value is ranked on this
  (`rank_on_normalised: true`), as for Chevron, so a price spike does not make a company look cheap.
Money is in the price currency (statements converted where they differ, noted in the file). Each file is marked DRAFT:
check it against the latest results, or let tools/update_results.py replace it with the reported quarter.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import warnings
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import growth_data as gd  # noqa: E402
from valuescreen import loader  # noqa: E402

OCF = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
WORKING_CAPITAL = ("Change In Working Capital",)
CAPEX = ("Capital Expenditure",)
YEARS_FOR_NORMAL = 4


def _cfo_ex_wc(ocf: dict, wc: dict, day):
    return None if day not in ocf else ocf[day] - wc.get(day, 0.0)


def draft(symbol: str, sector: str, today: dt.date) -> dict:
    """A cashflow-model company file from Yahoo's statements for one symbol."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = yf.Ticker(symbol)
        info = t.info or {}
        annual, quarterly = t.cashflow, t.quarterly_cashflow
        balance = t.quarterly_balance_sheet
        if balance is None or balance.empty:
            balance = t.balance_sheet
        history = t.history(period="10d", auto_adjust=False)["Close"].dropna()
    if history.empty or not info.get("sharesOutstanding"):
        raise ValueError("no price or share count from Yahoo")
    currency = info.get("currency") or "USD"
    report = info.get("financialCurrency") or currency
    fx = gd.fx_rate(report, currency)
    if fx is None:
        raise ValueError(f"no {report}/{currency} rate")
    m = lambda x: None if x is None else round(x * fx / 1e6, 1)  # noqa: E731 - to millions of the price currency

    ocf_y, wc_y, capex_y = gd._series(annual, *OCF), gd._series(annual, *WORKING_CAPITAL), gd._series(annual, *CAPEX)
    ocf_q, wc_q, capex_q = gd._series(quarterly, *OCF), gd._series(quarterly, *WORKING_CAPITAL), gd._series(quarterly, *CAPEX)
    ttm_ocf, end, label = gd._latest_twelve_months(ocf_q, ocf_y)
    ttm_wc = gd._latest_twelve_months(wc_q, wc_y)[0] or 0.0
    ttm_capex = gd._latest_twelve_months(capex_q, capex_y)[0] or 0.0
    if ttm_ocf is None:
        raise ValueError("no operating cash flow from Yahoo")
    years = sorted(d for d in ocf_y if d in capex_y)[-YEARS_FOR_NORMAL:]
    normal = [(_cfo_ex_wc(ocf_y, wc_y, d), -capex_y[d]) for d in years]
    cash, _ = gd._latest(balance, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    debt, balance_day = gd._latest(balance, "Total Debt")
    shares = round(info["sharesOutstanding"] / 1e6, 3)
    converted = f"; {report} statements converted to {currency} at {fx:.4g}" if report != currency else ""
    span = f"FY{years[0]:%y}–FY{years[-1]:%y}" if years else "n/a"
    company = {
        "ticker": symbol.split(".")[0].upper(), "yahoo": symbol, "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": sector, "model": "cashflow", "currency": currency,
        "period": {"label": label, "end": end.isoformat(), "per_year": 1},
        "earnings": {"cfo_ex_wc": m(ttm_ocf - ttm_wc), "capex": m(-ttm_capex), "shares_m": shares},
        "rank_on_normalised": True,
        "shares_m": shares,
        "balance": {"cash": m(cash or 0.0), "debt": m(debt or 0.0)},
        "multiples": [10, 13],
        "cyclical": True,
        "price": {"value": round(float(history.iloc[-1]), 4), "currency": currency, "date": history.index[-1].date().isoformat(),
                  "source": f"yfinance {symbol}"},
        "sources": [f"Yahoo Finance cash-flow statements and balance sheet via yfinance, fetched {today.isoformat()} "
                    f"(unverified draft{converted})"],
        "assumptions": [
            f"DRAFT from Yahoo's statements ({label}; normal basis {span}), not checked against the filings",
            "Owner earnings = operating cash flow excluding working-capital moves − all capex (growth capex included, so conservative)",
            f"Valued on the {len(years)}-year average ('normal' oil and gas prices), not the latest twelve months – "
            "prices in 2026 include a spike",
            f"Balance sheet at {balance_day.isoformat() if balance_day else 'the latest report'}",
        ],
    }
    if normal and all(a is not None for a, _ in normal):
        company["earnings_normalised"] = {"cfo_ex_wc": m(sum(a for a, _ in normal) / len(normal)),
                                          "capex": m(sum(b for _, b in normal) / len(normal)), "shares_m": shares}
    else:
        company["rank_on_normalised"] = False
        company["assumptions"][2] = "Fewer than four years of statements: valued on the latest twelve months"
    return company


def main():
    ap = argparse.ArgumentParser(description="Draft cashflow-model company files from Yahoo and add them to a list")
    ap.add_argument("list", help="list to write, e.g. oil")
    ap.add_argument("symbols", nargs="+", help="Yahoo symbols, e.g. XOM SU.TO")
    ap.add_argument("--sector", default="energy")
    args = ap.parse_args()
    today = dt.date.today()
    folder = loader.companies_folder()
    list_file = ROOT / "data" / "lists" / f"{args.list.lower()}.yaml"
    listed = yaml.safe_load(list_file.read_text(encoding="utf-8"))["tickers"] if list_file.exists() else []
    tickers = [str(t["ticker"] if isinstance(t, dict) else t).upper() for t in listed]
    for symbol in args.symbols:
        ticker = symbol.split(".")[0].upper()
        path = folder / f"{ticker.lower()}.yaml"
        if path.exists():
            print(f"  {ticker:6} already has a file – left as it is")
        else:
            try:
                company = draft(symbol, args.sector, today)
            except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the rest
                print(f"  {ticker:6} skipped: {e}")
                continue
            path.write_text(yaml.safe_dump(company, sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
            n = company.get("earnings_normalised") or company["earnings"]
            print(f"  {ticker:6} {company['name'][:32]:32} {company['currency']}  owner earnings {company['period']['label']}: "
                  f"{company['earnings']['cfo_ex_wc'] - company['earnings']['capex']:,.0f}m · normal: {n['cfo_ex_wc'] - n['capex']:,.0f}m")
        if ticker not in tickers:
            tickers.append(ticker)
    list_file.write_text(yaml.safe_dump({"name": f"{args.list.title()}", "tickers": tickers}, sort_keys=False), encoding="utf-8")
    print(f"\nList {list_file.relative_to(ROOT)}: {', '.join(tickers)}\nNext: python -m valuescreen validate && "
          f"python -m valuescreen run --list {args.list.lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
