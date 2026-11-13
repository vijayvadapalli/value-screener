"""Quick screen of the S&P 500 and Nasdaq-100 from official SEC figures, with a database of figures and prices.

    export SEC_USER_AGENT="Your Name your.email@example.com"   # once, in ~/.zshrc – the SEC requires a contact
    python tools/screen_us.py              # first run: ~1–1.5 GB SEC download + 6 years of prices (10–20 minutes)
    python tools/screen_us.py              # later runs: SEC file refreshed weekly, prices daily (a minute or two)
    python tools/screen_us.py --refresh    # download the SEC file again now

Writes output/us/US_Screen_<date>.html and copies it to reports/us-screen.html. The database is output/us/us_facts.sqlite
(rebuildable, not committed). Method: valuescreen/us_screen.py; figures: valuescreen/us_fundamentals.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import factsdb, growth_data, loader, sec, us_universe  # noqa: E402
from valuescreen import miner_screen  # noqa: E402
from valuescreen import us_screen as us  # noqa: E402
from valuescreen.us_fundamentals import summarize, wanted_tags  # noqa: E402

OUT = loader.output_folder("us")
DB = OUT / "us_facts.sqlite"
BULK = OUT / "companyfacts.zip"
CHUNK = 100   # tickers per Yahoo price download


def load_facts(con, entries, refreshed: bool):
    """Copies our companies' figures from the SEC bulk file into the database when the file is newer than the last load."""
    stamp = str(int(BULK.stat().st_mtime))
    if not refreshed and factsdb.get_meta(con, "facts_from") == stamp:
        return 0
    ciks = [e["cik"] for e in entries if not e["foreign"]]
    n = 0
    for cik, facts in sec.iter_companyfacts(BULK, ciks):
        factsdb.save_facts(con, cik, facts, wanted_tags())
        n += 1
    factsdb.set_meta(con, "facts_from", stamp)
    con.commit()
    return n


def load_prices(con, entries, log=print):
    """Six years of daily closes and splits for every ticker, once a day."""
    today = dt.date.today().isoformat()
    if factsdb.get_meta(con, "prices_on") == today:
        return
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    symbols = [e["yahoo"] for e in entries]
    for i in range(0, len(symbols), CHUNK):
        part = symbols[i:i + CHUNK]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(part, period="6y", actions=True, auto_adjust=False, progress=False, threads=True, group_by="column")
        for sym in part:
            try:
                close = data["Close"][sym].dropna()
                splits = data["Stock Splits"][sym].fillna(0)
            except KeyError:
                continue
            factsdb.save_prices(con, sym, [(d.date().isoformat(), float(v)) for d, v in close.items()],
                                [(d.date().isoformat(), float(v)) for d, v in splits.items() if v and v > 0])
        log(f"prices: {min(i + CHUNK, len(symbols))} of {len(symbols)}")
        time.sleep(2)
    factsdb.set_meta(con, "prices_on", today)
    con.commit()


def price_info(con, symbol):
    rows = factsdb.closes(con, symbol)
    if not rows:
        return None
    last_day, last = rows[-1]

    def on(day):
        earlier = [c for d, c in rows if d <= day]
        return earlier[-1] if earlier else None
    year_ago = on((dt.date.fromisoformat(last_day) - dt.timedelta(days=365)).isoformat())
    return {"price": last, "date": last_day, "change_1y": last / year_ago - 1 if year_ago else None, "on": on,
            "split_since": lambda day: factsdb.split_factor_since(con, symbol, day)}


def main():
    ap = argparse.ArgumentParser(description="Quick screen of the S&P 500 and Nasdaq-100 from SEC figures")
    ap.add_argument("--refresh", action="store_true", help="download the SEC bulk file again now")
    args = ap.parse_args()
    cfg = loader.load_config()
    today = dt.date.today()
    con = factsdb.connect(DB)
    entries = us_universe.universe(sec.company_tickers(OUT / "company_tickers.json"))
    factsdb.save_companies(con, entries)
    print(f"{len(entries)} companies in the S&P 500 and Nasdaq-100")
    refreshed = sec.download_bulk(BULK, args.refresh)
    loaded = load_facts(con, entries, refreshed)
    print(f"SEC figures: {'loaded for ' + str(loaded) + ' companies' if loaded else 'up to date'}")
    load_prices(con, entries)

    rows, notes, via_yahoo = [], [], [e for e in entries if e["foreign"]]
    for e in entries:
        if e["foreign"]:
            continue
        facts = factsdb.load_facts(con, e["cik"])
        if "us-gaap" not in facts["facts"]:   # a foreign filer (20-F, IFRS) – use Yahoo's figures
            via_yahoo.append(e)
            continue
        px = price_info(con, e["yahoo"])
        if not px:
            notes.append(f"{e['ticker']}: no price from Yahoo")
            continue
        try:
            rows.append(us.evaluate_sec(e, summarize(facts), px, cfg))
        except Exception as err:  # noqa: BLE001 - one odd filer must not stop the screen
            notes.append(f"{e['ticker']}: could not read its figures ({err.__class__.__name__})")
    raw = growth_data.collect(via_yahoo, {}, "us", OUT / "screen_cache" / f"foreign-{today}.json", workers=2)
    rows += [us.evaluate_yahoo(e, raw[e["ticker"]], cfg) for e in via_yahoo if e["ticker"] in raw]
    notes += [f"{e['ticker']}: no figures from the SEC or Yahoo" for e in via_yahoo if e["ticker"] not in raw]
    rows.sort(key=us.sort_key)
    factsdb.save_run(con, today.isoformat(), rows)
    con.commit()

    in_files = miner_screen.tickers_in_files(loader.company_folders().values())
    path = us.build(rows, OUT / f"US_Screen_{today:%d%b%Y}.html", today, in_files, notes, cfg)
    published = loader.publish(path, "us", "-screen.html")
    short = us.shortlist(rows)
    print(f"\n{len(rows)} screened. Shortlist ({len(short)}):")
    for r in short:
        print(f"  {r['ticker']:6} {r['name'][:32]:32} {r['sector'][:22]:22} needs {r['implied_growth']*100:+5.1f}%/yr  grade {r['grade']}")
    print(f"\nReport: {path}\nPublished copy: {published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
