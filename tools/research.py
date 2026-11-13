"""Builds the PRIVATE research report from the weekly captures in data/private/research/ (git-ignored).

    python tools/research.py              # the latest capture → output/private/research.html
    python tools/research.py --date 2026-11-08

Each capture is one YAML file per report (see data/private/research/*.yaml): support / resistance levels, targets,
IF / THEN rules, stance and notes per asset. The report puts them next to today's price (output/prices.sqlite – any
symbol not there yet is downloaded first) and our own valuation, with charts showing both sets of levels.
Nothing here is published: output/ is git-ignored and loader.publish refuses private paths.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import update_history  # noqa: E402

from valuescreen import engine, loader, price_chart, pricedb  # noqa: E402
from valuescreen import research as R  # noqa: E402


def our_companies(cfg):
    """{ticker: (company, result, report link)} for every company file, all folders."""
    out = {}
    for folder, report in ((None, None), ("miners", "miners")):
        companies = loader.load_companies(loader.companies_folder(folder))
        results = engine.run(companies, list(companies), cfg)
        for t, c in companies.items():
            out[t] = (c, results[t], report)
    lists = {}
    for name in ("core", "tech", "oil", "watchlist"):
        for t in loader.load_list(name):
            lists.setdefault(t, name)
    return out, lists


def main():
    ap = argparse.ArgumentParser(description="Private research report from the weekly captures")
    ap.add_argument("--date", help="capture date YYYY-MM-DD (default: the latest)")
    args = ap.parse_args()
    weeks = R.load_weeks()
    if not weeks:
        sys.exit(f"No captures in {R.FOLDER}")
    idx = len(weeks) - 1 if not args.date else next(i for i, w in enumerate(weeks) if w["date"] == dt.date.fromisoformat(args.date))
    week, previous = weeks[idx], weeks[idx - 1] if idx else None
    cfg = loader.load_config()
    ours, lists = our_companies(cfg)

    # prices: make sure every symbol has history, then take the latest close
    con = pricedb.connect()
    symbols = {key: item["symbol"] for key, item in week["assets"].items() if item.get("symbol")}
    for key in week["assets"]:   # a company file's Yahoo symbol wins
        if key in ours and not symbols.get(key):
            symbols[key] = ours[key][0].get("yahoo") or key
    missing = {s: ["research"] for s in symbols.values() if pricedb.last_date(con, s) is None}
    if missing:
        print(f"downloading history for {', '.join(missing)}")
        update_history.update(con, missing, 10, False, log=lambda *_: None)
    prices, charts, results, links = {}, {}, {}, {}
    for key, item in week["assets"].items():
        company, result, report = ours.get(key, (None, None, None))
        sym = symbols.get(key)
        if key == "URANIUM":
            prices[key] = cfg["spot"]["uranium"]
        elif sym and pricedb.last_date(con, sym):
            info = pricedb.info(con, sym) or {}
            p, _ = pricedb.to_major(pricedb.bars(con, sym)[-1]["close"], info.get("currency"))
            prices[key] = p
            r = result or {"model": None, "price_ccy": pricedb.to_major(1.0, info.get("currency"))[1]}
            charts[key] = price_chart.payload(con, sym, r, company or {"period": {}},
                                              watched=[x for x in R.levels(item)], watched_label="Their levels")
        if result:
            results[key] = result
            list_name = report or lists.get(key)
            if list_name:
                links[key] = f"../../reports/{list_name}.html#c-{key}"
    rows = R.evaluate(week, prices, results)
    path = R.build_html(week, rows, R.changes(week, previous), charts, links, R.OUT / "research.html", weeks)
    near = [f"{r['asset'] if 'asset' in r else row['key']}" for row in rows for r in row["rules"] if r["status"] in ("near", "triggered")]
    print(f"{len(rows)} assets · rules near or triggered: {', '.join(sorted(set(near))) or 'none'}")
    print(f"Private report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
