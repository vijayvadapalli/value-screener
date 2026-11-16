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
from valuescreen import factsdb, growth_screen, loader, pricedb, sec, us_pages, us_universe  # noqa: E402
from valuescreen import miner_screen  # noqa: E402
from valuescreen import us_screen as us  # noqa: E402
from valuescreen.us_fundamentals import wanted_tags  # noqa: E402

OUT = loader.output_folder("us")
DB = OUT / "us_facts.sqlite"
BULK = OUT / "companyfacts.zip"
CHUNK = 100   # tickers per Yahoo price download


def load_facts(con, entries, refreshed: bool):
    """Copies our companies' figures from the SEC bulk file into the database when the file is newer than the last load."""
    tags = wanted_tags()
    stamp = str(int(BULK.stat().st_mtime))
    tag_set = str(sum(len(t) for ns in tags.values() for t in ns))   # changes when tags are added, e.g. lenders' loan figures
    if not refreshed and factsdb.get_meta(con, "facts_from") == stamp and factsdb.get_meta(con, "facts_tags") == tag_set:
        return 0
    ciks = [e["cik"] for e in entries if not e["foreign"]]
    n = 0
    for cik, facts in sec.iter_companyfacts(BULK, ciks):
        factsdb.save_facts(con, cik, facts, tags)
        n += 1
    factsdb.set_meta(con, "facts_from", stamp)
    factsdb.set_meta(con, "facts_tags", tag_set)
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


def pages_for(rows: list[dict], screen_rows: list[dict], cfg: dict, today: dt.date) -> tuple[list[str], list]:
    """The interesting companies' pages: insider ownership, up to 20 years of prices (output/prices.sqlite), the pages."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import update_history  # noqa: PLC0415
    tickers = us_pages.interesting(screen_rows)
    by_t = {r["ticker"]: r for r in rows}
    held = us_pages.insiders([by_t[t]["yahoo"] for t in tickers])
    for sr in screen_rows:
        if sr["ticker"] in by_t and by_t[sr["ticker"]]["yahoo"] in held:
            sr["promoters"] = held[by_t[sr["ticker"]]["yahoo"]]   # the owners column: insiders for US companies
    years = cfg["us_growth_screen"]["page_years"]
    pcon = pricedb.connect()
    update_history.update(pcon, {by_t[t]["yahoo"]: ["us-screen"] for t in tickers}, years, True, log=lambda *_: None)
    pcon.commit()
    written = us_pages.build(rows, screen_rows, tickers, pcon, cfg, OUT, years, us.RATE)
    return tickers, written


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

    rows, notes = us.rows_from_db(con, entries, cfg, today, OUT / "screen_cache")
    factsdb.save_run(con, today.isoformat(), rows)
    con.commit()

    in_files = miner_screen.tickers_in_files(loader.company_folders().values())
    screen_rows = growth_screen.rows_us(rows, cfg)
    tickers, written = pages_for(rows, screen_rows, cfg, today)
    print(f"Growth screen: {sum(r['tier'] == 'shortlist' for r in screen_rows)} shortlisted, "
          f"{sum(r['tier'] == 'near miss' for r in screen_rows)} near misses · {len(written)} company pages")
    path = us.build(rows, OUT / f"US_Screen_{today:%d%b%Y}.html", today, in_files, notes, cfg, screen_rows, set(tickers))
    published = loader.publish(path, "us", "-screen.html")
    loader.publish_dir(OUT / us_pages.FOLDER, us_pages.FOLDER)
    loader.publish_dir(OUT / "assets", "assets")
    short = us.shortlist(rows)
    print(f"\n{len(rows)} screened. Shortlist ({len(short)}):")
    for r in short:
        print(f"  {r['ticker']:6} {r['name'][:32]:32} {r['sector'][:22]:22} needs {r['implied_growth']*100:+5.1f}%/yr  grade {r['grade']}")
    print(f"\nReport: {path}\nPublished copy: {published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
