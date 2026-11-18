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

from valuescreen import engine, loader, longterm, price_chart, pricedb  # noqa: E402
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


def _leg(con, name: str) -> dict:
    """{YYYY-MM-01: price} for one side of a monthly ratio: a long-term series (gold, silver, uranium_spot) or a
    Yahoo symbol's month-end closes."""
    return dict(longterm.series(name) if name.lower() in longterm.COLUMNS else price_chart.monthly_closes(con, name))


def ratio_chart(con, item, watched, patterns):
    """(chart, latest ratio) for `ratio: [A, B]` – A ÷ B. Two Yahoo symbols give daily bars (with `long: [a, b]`,
    the long-term monthly series before the daily data); a long-term series on either side gives a monthly chart."""
    a, b = item["ratio"]
    name = item.get("name") or f"{a} ÷ {b}"
    if a.lower() in longterm.COLUMNS or b.lower() in longterm.COLUMNS:
        sa, sb = _leg(con, a), _leg(con, b)
        points = [(d, sa[d] / sb[d]) for d in sorted(sa) if sb.get(d)]
        chart = price_chart.payload_monthly(name, points, f"{a} ÷ {b}, month-end", watched=watched)
        if chart:
            chart.update(patterns=patterns, currency="ratio")
        return chart, points[-1][1] if points else None
    long = None
    if item.get("long"):
        la, lb = (dict(longterm.series(x)) for x in item["long"])
        long = [(d, la[d] / lb[d]) for d in sorted(la) if lb.get(d)]
    bars = price_chart.ratio_bars(con, a, b)
    chart = price_chart.payload(con, f"{a} ÷ {b}", {"model": None, "price_ccy": "ratio"}, {"period": {}}, watched=watched,
                                watched_label="Their levels", mode="research", long_years=None, long_monthly=long,
                                patterns=patterns, bars=bars)
    return chart, bars[-1]["close"] if bars else None


def history_chart(item, watched, patterns):
    """`history: {series, from, to}` – a past stretch of a long-term monthly series (e.g. silver 1971–1980)."""
    h = item["history"]
    points = [(d, v) for d, v in longterm.series(h["series"]) if str(h["from"]) <= d[:7] <= str(h["to"])]
    chart = price_chart.payload_monthly(item.get("name", h["series"]), points,
                                        f"{h['series']} monthly average {h['from']} to {h['to']} (World Bank)", watched=watched)
    if chart:
        chart["patterns"] = patterns
    return chart


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
    legs = {x for item in week["assets"].values() for x in item.get("ratio") or [] if x.lower() not in longterm.COLUMNS}
    missing_legs = {s: ["research"] for s in legs if pricedb.last_date(con, s) is None and s not in missing}
    for wanted, years in ((missing, 10), (missing_legs, 0)):   # ratio legs: all the history Yahoo has
        if wanted:
            print(f"downloading history for {', '.join(wanted)}")
            update_history.update(con, wanted, years, False, log=lambda *_: None)
    prices, charts, results, links = {}, {}, {}, {}
    for key, item in week["assets"].items():
        company, result, report = ours.get(key, (None, None, None))
        sym = symbols.get(key)
        if item.get("ratio"):
            charts[key], prices[key] = ratio_chart(con, item, R.levels(item), R.pattern_lines(item))
        elif item.get("history"):
            charts[key] = history_chart(item, R.levels(item), R.pattern_lines(item))
        elif key == "URANIUM":
            prices[key] = cfg["spot"]["uranium"]
            spot = longterm.series("uranium_spot")   # Cameco month-end spot: their spot levels can be drawn on it
            charts[key] = (price_chart.payload_monthly("Uranium spot (Cameco)", spot, longterm.NOTES["uranium_spot"],
                                                       watched=R.levels(item)) if spot else
                           price_chart.payload_monthly("Uranium (IMF)", longterm.series("uranium"), longterm.NOTES["uranium"]))
        elif sym and pricedb.last_date(con, sym):
            info = pricedb.info(con, sym) or {}
            p, _ = pricedb.to_major(pricedb.bars(con, sym)[-1]["close"], info.get("currency"))
            prices[key] = p
            r = result or {"model": None, "price_ccy": pricedb.to_major(1.0, info.get("currency"))[1]}
            history = longterm.series(key.lower()) if key.lower() in longterm.COLUMNS else None
            charts[key] = price_chart.payload(con, sym, r, company or {"period": {}}, watched=R.levels(item),
                                              watched_label="Their levels", mode="research", long_years=None,
                                              long_monthly=history, patterns=R.pattern_lines(item))
        if charts.get(key) and not charts[key].get("patterns"):
            charts[key]["patterns"] = R.pattern_lines(item)
        lv = R.levels(item)
        if charts.get(key) and lv and not any(x["tf"] in ("D", "W") for x in lv):
            charts[key]["open"] = ["M", "Max"]   # drawn on a monthly chart in the report: open there
        if not charts.get(key):
            charts.pop(key, None)
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
