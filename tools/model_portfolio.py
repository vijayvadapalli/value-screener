"""Builds the model portfolios from today's screens: balanced, and resource-heavy with value first.

    python tools/model_portfolio.py                      # both profiles
    python tools/model_portfolio.py --profile resources  # just one (balanced | resources)

Run the screens first so their figures are current (each caches its own day):
    python -m valuescreen run --list core --live      # and oil, tech – full company files
    python tools/screen_us.py                         # S&P 500 / Nasdaq-100, fills the price database
    python tools/screen_miners.py                     # miners from the ETF holdings

Writes output/model/Model_<profile>_<date>.html and copies each to reports/model-portfolio.html and
reports/model-resources.html. Method: valuescreen/model_portfolio.py. Educational framework, not investment advice.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import engine, factsdb, loader  # noqa: E402
from valuescreen import miner_screen as ms  # noqa: E402
from valuescreen import model_portfolio as mp  # noqa: E402
from valuescreen import us_screen as us  # noqa: E402

LISTS = ("core", "oil", "tech")   # lists whose companies have full files in data/companies
FRESH_DAYS = 5                    # database closes older than this are fetched again


def file_candidates(cfg):
    companies = loader.load_companies()
    source = {}
    for name in LISTS:
        for t in loader.load_list(name):
            source.setdefault(t, f"{name} list")
    results = engine.run(companies, list(companies), cfg)
    out = []
    for t, r in results.items():
        r["yahoo"] = companies[t].get("yahoo") or t
        out.append(mp.from_company_file(r, source.get(t, "company file")))
    return out


def us_candidates(cfg, today, notes):
    out = loader.output_folder("us")
    db = out / "us_facts.sqlite"
    if not db.exists():
        notes.append("S&P 500 / Nasdaq-100 left out: run tools/screen_us.py first")
        return [], None
    con = factsdb.connect(db)
    rows, _ = us.rows_from_db(con, factsdb.companies(con), cfg, today, out / "screen_cache", log=lambda *_: None)
    return [mp.from_us_screen(r) for r in rows], con


def miner_candidates(notes):
    caches = sorted((loader.output_folder("miners") / "screen_cache").glob("miners-*.json"))
    if not caches:
        notes.append("miners screen left out: run tools/screen_miners.py first")
        return []
    import json  # noqa: PLC0415
    raw = json.loads(caches[-1].read_text(encoding="utf-8"))
    entries = [e for e in loader.load_list_entries("miners") if e["ticker"] in raw]
    seen, rows = set(), []
    for e in entries:
        if e["ticker"] not in seen:
            seen.add(e["ticker"])
            rows.append(ms.evaluate(raw[e["ticker"]], e))
    notes.append(f"miners screen figures from {caches[-1].stem.split('-', 1)[1]}")
    return [mp.from_miners_screen(r) for r in ms.with_grades(rows, raw)]


def closes_for(symbols, con, today):
    """{symbol: [closes, oldest first]} – the price database where it is fresh, Yahoo for the rest."""
    found, need = {}, []
    for s in symbols:
        rows = factsdb.closes(con, s) if con else []
        if rows and (today - dt.date.fromisoformat(rows[-1][0])).days <= FRESH_DAYS:
            found[s] = [c for _, c in rows]
        else:
            need.append(s)
    if need:
        import yfinance as yf  # noqa: PLC0415
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(need, period="2y", auto_adjust=False, progress=False, threads=True, group_by="column")
        for s in need:
            try:
                col = data["Close"][s].dropna() if len(need) > 1 else data["Close"].squeeze().dropna()
            except KeyError:
                continue
            if len(col):
                found[s] = [float(v) for v in col.values]
    return found


def main():
    ap = argparse.ArgumentParser(description="Model portfolios from today's screens")
    ap.add_argument("--profile", choices=list(mp.PROFILES), action="append", help="build only this profile (repeatable)")
    args = ap.parse_args()
    cfg = loader.load_config()
    today = dt.date.today()
    notes = []
    files = file_candidates(cfg)
    us_rows, con = us_candidates(cfg, today, notes)
    candidates = mp.merge(files, us_rows, miner_candidates(notes), [mp.etf_candidate(s) for s in mp.ETFS])
    # momentum matters only for candidates that pass the value and quality tests (and the ETFs)
    live = [c for c in candidates if not c["reasons"]]
    closes = closes_for(sorted({c["yahoo"] for c in live}), con, today)
    for c in live:
        mp.momentum(c, mp.price_stats(closes.get(c["yahoo"], [])))
    no_history = [c["ticker"] for c in live if "stats" not in c]
    if no_history:
        notes.append("no price history (started with a third): " + ", ".join(no_history))
    for c in candidates:
        if c["reasons"]:
            c.update(momentum_score=0.0, entry="third", vol=0.4)
    print(f"{len(candidates)} candidates, {len(live) - len(mp.ETFS)} pass value and quality")
    out = loader.output_folder("model")
    for name in args.profile or list(mp.PROFILES):
        result = mp.build(candidates, name)
        risk = mp.portfolio_risk(result["holdings"], {c["key"]: closes.get(c["yahoo"]) for c in result["holdings"]})
        path = mp.report(result, risk, out / f"Model_{name}_{today:%d%b%Y}.html", today, notes)
        published = loader.publish(path, mp.PROFILES[name]["file"], ".html")
        print(f"\n{mp.PROFILES[name]['title']} – {len(result['holdings'])} positions")
        for c in result["holdings"]:
            print(f"  {c['ticker']:9} {mp.SLEEVE_NAMES[c['sleeve']][:18]:18} {c['weight']*100:5.1f}%  {c.get('entry', ''):5}  "
                  f"score {c['score']:.2f}  {c['value_text']}")
        if risk:
            print(f"  past year of today's mix: volatility {risk['vol']*100:.0f}%, worst fall {risk['max_fall']*100:.0f}%")
        print(f"Report: {published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
