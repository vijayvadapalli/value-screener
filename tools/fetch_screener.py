"""Fill the Nifty v2 block of Indian company files from Screener.in's consolidated pages (Valuation Playbook source).

    python tools/fetch_screener.py nifty50                    # every company in data/lists/nifty50.yaml
    python tools/fetch_screener.py nifty50 --tickers ITC,TCS  # just these
    python tools/fetch_screener.py nifty50 --dry-run          # show what would change, write nothing

For each company it reads the last 8 quarterly EPS, up to 10 yearly EPS, yearly net profit and cash from operations,
book value per share, 5-year return on equity, each year-end's equity, borrowings and net profit (the quality
check), the current price and market value – from the consolidated page, or
the standalone one when that has no quarterly figures. For lenders (financial companies other than insurers) it also
reads gross and net NPA % for the last 8 quarters – banks fill these on the standalone page only – and the loans they
apply to (see valuescreen/asset_quality.py). It writes them into the company file's `v2:` block (see
valuescreen/v2.py) and updates the price, share count and period. Everything else in the file – net cash, notes,
sources – is kept. Files that do not exist yet are created with net cash 0 and a note to add it.

Needs `pip install beautifulsoup4 lxml`. One request every ~4 seconds, backing off when rate limited.
Numbers from a web page can be wrong: check the key figures against the company's results before relying on them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import loader  # noqa: E402
from valuescreen import screener  # noqa: E402

HAND_SET_V2 = ("kind", "flags", "history_not_comparable", "eps_currency")   # kept when the v2 block is re-fetched


def fetch(symbol: str, lender: bool = False) -> tuple[dict, str]:
    """(figures, page URL): the consolidated page, or the standalone one when the consolidated page has no quarterly EPS
    (some companies, e.g. SBI Life, publish only standalone quarters). For a lender, figures["asset_quality"] too."""
    problem = "no page"
    for consolidated in (True, False):
        page = screener.url(symbol, consolidated)
        try:
            html = screener.get(page)
            data = screener.parse_v2(html)
        except ValueError as e:
            problem = str(e)
        else:
            if len(data["eps_quarters"]) >= 4 and None not in data["eps_quarters"]:
                if lender:
                    data["asset_quality"] = fetch_asset_quality(symbol, consolidated, html)
                return data, page
            problem = "fewer than 4 quarters of EPS"
        time.sleep(screener.PAUSE_SECONDS)
    raise ValueError(f"{problem} on the consolidated and standalone pages")


def fetch_asset_quality(symbol: str, consolidated: bool, html: str) -> dict | None:
    """Gross and net NPA % and the loans they apply to: from the page already read, else from the standalone page."""
    aq = screener.parse_asset_quality(html)
    if aq is None and consolidated:
        time.sleep(screener.PAUSE_SECONDS)
        consolidated = False
        aq = screener.parse_asset_quality(screener.get(screener.url(symbol, False)))
    if aq is None:
        return None
    time.sleep(screener.PAUSE_SECONDS)
    loans, basis = screener.loans_cr(aq, consolidated)
    return {"quarters": aq["quarters"], "gross_npa_pct": aq["gross_npa_pct"], "net_npa_pct": aq["net_npa_pct"],
            "loans_cr": loans, "loans_basis": basis, "page": screener.url(symbol, consolidated)}


def is_lender(entry: dict, cfg: dict) -> bool:
    rules = cfg.get("nifty_v2", {})
    return (entry.get("industry") in rules.get("financial_industries", [])
            and entry["ticker"].upper() not in rules.get("insurers", []))


def update_file(existing: dict | None, entry: dict, data: dict, today: dt.date, url: str = "") -> dict:
    """The company file with the new v2 block, price, share count and period; other fields kept."""
    if None in data["eps_quarters"] or len(data["eps_quarters"]) < 4:
        raise ValueError("fewer than 4 quarters of EPS")
    if not data.get("price") or not data.get("market_cap_cr"):   # Screener blanks the figures when it throttles
        raise ValueError("the page came without its price / market value (Screener throttling?) – re-run these later")
    c = dict(existing or {})
    c.update(ticker=entry["ticker"], yahoo=entry.get("yahoo", c.get("yahoo")), name=entry.get("name", c.get("name")),
             sector=entry.get("industry", c.get("sector", "")), model="growth", currency="INR")
    end = screener.month_end(data["quarters"][-1])
    c["period"] = {"label": f"TTM to {data['quarters'][-1]}", "end": end.isoformat(), "per_year": 4}
    c["price"] = {"value": data["price"], "currency": "INR", "date": today.isoformat(), "source": f"Screener.in ({today:%d %b %Y})"}
    c["shares_m"] = round(data["market_cap_cr"] * 10 / data["price"], 3)
    c.pop("earnings", None)   # the v2 block replaces the draft's yearly net income
    kept = {k: v for k, v in (c.get("v2") or {}).items() if k in HAND_SET_V2}   # your judgement, not Screener's figures
    c["v2"] = {k: data[k] for k in ("eps_quarters", "eps_annual", "years", "profit_annual", "cfo_annual", "book_value_ps", "roe_5y")}
    c["v2"].update({k: data[k] for k in ("profit_growth_5y", "sales_growth_5y", "shareholding", "balance_annual")
                    if data.get(k) is not None})
    c["v2"].update(kept)
    if data.get("asset_quality"):
        c["v2"]["asset_quality"] = data["asset_quality"]
    c.setdefault("balance", {"net_cash": 0.0})
    url = url or screener.url(entry["ticker"])
    page = "consolidated" if "/consolidated/" in url else "standalone"
    source = f"Screener.in {page} page, fetched {today:%d %b %Y}: {url}"
    aq = data.get("asset_quality")
    if aq and aq["page"] != url:
        source += f"; NPA figures from the standalone page: {aq['page']}"
    c["sources"] = [s for s in c.get("sources", []) if not str(s).startswith(("Screener.in", "Yahoo Finance annual"))] + [source]
    assumptions = [a for a in c.get("assumptions", [])
                   if not str(a).startswith(("DRAFT", "Placeholder", "Nifty v2:", "Shares derived", "Standalone quarters"))]
    if data.get("standalone_quarters"):
        assumptions.append(f"Standalone quarters: Screener shows {data['standalone_quarters']} of the last 4 quarters standalone "
                           "(marked (S) – no consolidated figures for them), so the 12-month EPS mixes the two")
    assumptions += ["Nifty v2: EPS (attributable, as Screener reports it), net profit and cash from operations from Screener.in",
                    "Shares derived from Screener's market value ÷ price"]
    if existing is None or "balance" not in existing:
        assumptions.append("Net cash not yet added – set balance from StockAnalysis (cash & short-term investments − total debt incl. leases)")
    c["assumptions"] = assumptions
    c.setdefault("notes", [])
    return c


def main():
    ap = argparse.ArgumentParser(description="Fill Nifty v2 data from Screener.in")
    ap.add_argument("list", help="a list in data/lists, e.g. nifty50")
    ap.add_argument("--tickers", help="comma-separated subset")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    lst = yaml.safe_load((ROOT / "data" / "lists" / f"{args.list.lower()}.yaml").read_text(encoding="utf-8"))
    folder = loader.companies_folder(lst.get("folder"))
    entries = [e for e in lst["tickers"] if isinstance(e, dict) and not e.get("market")]   # indices: price only
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        entries = [e for e in entries if e["ticker"].upper() in wanted]
    today = dt.date.today()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    done, failed = [], []
    for i, entry in enumerate(entries):
        if i:
            time.sleep(screener.PAUSE_SECONDS)
        path = folder / f"{entry['ticker'].lower()}.yaml"
        try:
            data, url = fetch(entry["ticker"], lender=is_lender(entry, cfg))
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
            new = update_file(existing, entry, data, today, url)
        except Exception as e:  # noqa: BLE001 - one bad page must not stop the run
            failed.append((entry["ticker"], str(e)))
            print(f"  {entry['ticker']:11} failed: {e}")
            continue
        ttm = sum(data["eps_quarters"][-4:])
        print(f"  {entry['ticker']:11} price ₹{data['price']:,.0f} · TTM EPS {ttm:,.2f} · BV {data['book_value_ps']} · "
              f"ROE 5y {data['roe_5y']}")
        if data.get("asset_quality"):
            aq = data["asset_quality"]
            print(f"  {'':11} gross NPA {aq['gross_npa_pct'][-1]}% · net NPA {aq['net_npa_pct'][-1]}% · "
                  f"loans ₹{aq['loans_cr'] or 0:,.0f} cr ({aq['loans_basis'] or 'not found'})")
        if not args.dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(new, sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
        done.append(entry["ticker"])
    print(f"\n{'Would update' if args.dry_run else 'Updated'} {len(done)} files in {folder.relative_to(ROOT)}; {len(failed)} failed.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
