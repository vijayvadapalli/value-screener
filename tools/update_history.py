"""Daily price history from Yahoo into output/prices.sqlite – the base for charts and technical analysis.

    python tools/update_history.py                       # core, tech, oil, watchlist and the promoted miners (default)
    python tools/update_history.py --lists core,tech     # chosen lists
    python tools/update_history.py --tickers NEM,YCA.L   # chosen Yahoo symbols
    python tools/update_history.py --refresh             # download every history again
    python tools/update_history.py --years 5             # how far back a new symbol starts (default 10)

The first run downloads 10 years for each symbol (a minute or two); later runs fetch only the days since the last
update, plus a few days' overlap. A split after the last update makes Yahoo restate every earlier price, so that
symbol's whole history is reloaded. For the miners list only the companies with a full company file (promoted from
the screen) are included. The database is rebuildable and not committed; the module that reads it is
valuescreen/pricedb.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import loader, pricedb  # noqa: E402

DEFAULT_LISTS = ("core", "tech", "oil", "miners", "watchlist")
CHUNK = 20          # symbols per Yahoo request
OVERLAP_DAYS = 7    # re-read the last week on each update (late corrections, the latest day's final close)


def symbols_for(lists) -> dict[str, list[str]]:
    """{Yahoo symbol: [lists it is in]} – the company file's Yahoo symbol where there is a file. Lists whose
    companies live in their own folder (miners) contribute only the companies that have a file."""
    out: dict[str, list[str]] = {}
    for name in lists:
        folder = loader.list_folder(name)
        companies = loader.load_companies(loader.companies_folder(folder))
        for e in loader.load_list_entries(name):
            c = companies.get(e["ticker"])
            if folder and c is None:
                continue
            symbol = ((c or {}).get("yahoo") or e.get("yahoo") or e["ticker"]).strip()
            out.setdefault(symbol, [])
            if name not in out[symbol]:
                out[symbol].append(name)
    return out


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def parse(data, symbol: str):
    """(bars, splits, dividends) for one symbol from a yf.download frame (group_by='column')."""
    try:
        sub = data.xs(symbol, axis=1, level="Ticker")
    except KeyError:
        return [], [], []
    rows, splits, divs = [], [], []
    for day, r in sub.iterrows():
        close = _num(r.get("Close"))
        if close is None:
            continue
        d = day.date().isoformat()
        rows.append((d, _num(r.get("Open")), _num(r.get("High")), _num(r.get("Low")), close, _num(r.get("Adj Close")),
                     _num(r.get("Volume"))))
        if (_num(r.get("Stock Splits")) or 0) > 0:
            splits.append((d, "split", float(r["Stock Splits"])))
        if (_num(r.get("Dividends")) or 0) > 0:
            divs.append((d, "dividend", float(r["Dividends"])))
    return rows, splits, divs


def download(symbols, **kw):
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(list(symbols), auto_adjust=False, actions=True, progress=False, threads=True,
                           group_by="column", **kw)


def currency_of(symbol: str) -> str | None:
    try:
        import yfinance as yf  # noqa: PLC0415
        return yf.Ticker(symbol).fast_info["currency"]
    except Exception:  # noqa: BLE001 - optional detail
        return None


def update(con, wanted: dict[str, list[str]], years: int, refresh: bool, log=print) -> dict:
    """Downloads what is missing for each symbol. Returns {"rows", "new", "updated", "reloaded", "missing"}."""
    stats = {"rows": 0, "new": [], "updated": [], "reloaded": [], "missing": []}
    last = {s: (None if refresh else pricedb.last_date(con, s)) for s in wanted}
    fresh = [s for s in wanted if last[s] is None]
    known = [s for s in wanted if last[s] is not None]
    jobs = [(fresh[i:i + CHUNK], {"period": f"{years}y"}) for i in range(0, len(fresh), CHUNK)]
    for i in range(0, len(known), CHUNK):
        part = known[i:i + CHUNK]
        start = dt.date.fromisoformat(min(last[s] for s in part)) - dt.timedelta(days=OVERLAP_DAYS)
        jobs.append((part, {"start": start.isoformat()}))
    reload = []
    for n, (part, kw) in enumerate(jobs, 1):
        data = download(part, **kw)
        for s in part:
            rows, splits, divs = parse(data, s)
            if not rows:
                stats["missing"].append(s)
                continue
            if last[s] and pricedb.needs_full_refresh([d for d, _, _ in splits], last[s]):
                reload.append(s)
                continue
            if last[s] is None:
                pricedb.replace_bars(con, s, rows)
                stats["new"].append(s)
            else:
                pricedb.save_bars(con, s, rows)
                stats["updated"].append(s)
            stats["rows"] += len(rows)
            pricedb.save_actions(con, s, splits + divs)
            pricedb.save_symbol(con, s, currency_of(s) if last[s] is None else None, ",".join(wanted[s]))
        con.commit()
        log(f"  batch {n}/{len(jobs)}: {len(part)} symbols")
        if n < len(jobs):
            time.sleep(2)
    for s in reload:   # a new split: Yahoo has restated the whole history
        rows, splits, divs = parse(download([s], period=f"{years}y"), s)
        if rows:
            pricedb.replace_bars(con, s, rows)
            pricedb.save_actions(con, s, splits + divs)
            pricedb.save_symbol(con, s, None, ",".join(wanted[s]))
            stats["reloaded"].append(s)
            stats["rows"] += len(rows)
    if stats["missing"]:   # Yahoo sometimes drops a symbol from a batch – one more try, one at a time
        time.sleep(10)
        retry, stats["missing"] = stats["missing"], []
        for s in retry:
            kw = {"period": f"{years}y"} if last[s] is None else {"start": last[s]}
            rows, splits, divs = parse(download([s], **kw), s)
            if not rows:
                stats["missing"].append(s)
                continue
            (pricedb.replace_bars if last[s] is None else pricedb.save_bars)(con, s, rows)
            pricedb.save_actions(con, s, splits + divs)
            pricedb.save_symbol(con, s, currency_of(s) if last[s] is None else None, ",".join(wanted[s]))
            stats["new" if last[s] is None else "updated"].append(s)
            stats["rows"] += len(rows)
    con.commit()
    return stats


def main():
    ap = argparse.ArgumentParser(description="Daily price history from Yahoo into output/prices.sqlite")
    ap.add_argument("--lists", default=",".join(DEFAULT_LISTS), help="comma-separated lists (default: core,tech,oil,miners,watchlist)")
    ap.add_argument("--tickers", help="comma-separated Yahoo symbols instead of lists")
    ap.add_argument("--years", type=int, default=10, help="history for a symbol seen for the first time (default 10)")
    ap.add_argument("--refresh", action="store_true", help="download every history again")
    ap.add_argument("--db", help="database file (default output/prices.sqlite)")
    args = ap.parse_args()
    wanted = ({t.strip(): ["manual"] for t in args.tickers.split(",") if t.strip()} if args.tickers
              else symbols_for([x.strip().lower() for x in args.lists.split(",") if x.strip()]))
    con = pricedb.connect(Path(args.db) if args.db else None)
    print(f"{len(wanted)} symbols")
    t0 = time.time()
    stats = update(con, wanted, args.years, args.refresh)
    print(f"\n{stats['rows']:,} daily rows saved in {time.time() - t0:.0f}s · new {len(stats['new'])} · updated "
          f"{len(stats['updated'])} · reloaded after a split {len(stats['reloaded'])}")
    if stats["missing"]:
        print("No data from Yahoo for: " + ", ".join(stats["missing"]) + " – check the symbol in the company file, or run again later")
    print(f"\n{'Symbol':10} {'Currency':8} {'From':10}  {'To':10}  {'Days':>5}  Lists")
    for s in pricedb.symbols(con):
        if s["ticker"] in wanted:
            n = con.execute("SELECT COUNT(*) FROM bars WHERE ticker = ?", (s["ticker"],)).fetchone()[0]
            print(f"{s['ticker']:10} {s['currency'] or '?':8} {s['first_date']}  {s['last_date']}  {n:5}  {s['lists']}")
    size = Path(args.db or pricedb.DB).stat().st_size / 1e6
    print(f"\nDatabase: {args.db or pricedb.DB} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
