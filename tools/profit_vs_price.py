"""Profit growth vs price growth report on its own (the same figures also appear in every `valuescreen run` report).

    python tools/profit_vs_price.py --list core
    python tools/profit_vs_price.py --list tech
    python tools/profit_vs_price.py --list nifty50              # Screener.in, about 4 minutes the first time each day
    python tools/profit_vs_price.py --list core --refresh  # ignore today's cached figures

Writes output/<folder>/<List>_Profit_vs_Price_<date>.pdf and copies it to reports/<list>-profit-vs-price.pdf. Method and grades: valuescreen/profit_vs_price.py;
data sources: valuescreen/growth_data.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import growth_data, loader  # noqa: E402
from valuescreen import profit_vs_price as pvp  # noqa: E402
from valuescreen.engine import run  # noqa: E402
from valuescreen.pdf import list_title  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Profit growth vs price growth report for a list")
    ap.add_argument("--list", required=True, help="a list in data/lists, e.g. core, tech, nifty50")
    ap.add_argument("--refresh", action="store_true", help="fetch again even if today's figures are cached")
    args = ap.parse_args()
    name = args.list.lower()
    folder = loader.list_folder(name)
    entries = loader.load_list_entries(name)
    companies = loader.load_companies(loader.companies_folder(folder))
    cfg = loader.load_config()
    out_dir = loader.output_folder(folder)
    today = dt.date.today()
    raw = growth_data.collect(entries, companies, folder, out_dir / "profit_vs_price_cache" / f"{name}-{today}.json", args.refresh)
    results = run(companies, [e["ticker"] for e in entries if e["ticker"] in companies], cfg)
    rows = pvp.rows(entries, raw, results, companies)
    title = list_title(name)
    path = pvp.build(rows, out_dir / f"{title.replace(' ', '_')}_Profit_vs_Price_{today:%d%b%Y}.pdf", title, today,
                     pvp.sources_text(rows, today))
    loader.publish(path, name, "-profit-vs-price.pdf")
    pct = lambda x: "" if x is None else f"{x*100:+.0f}%"  # noqa: E731
    print(f"\n{'TICKER':11} {'GRADE':5} {'P/E CHANGE':>10}  {'PROFIT/YR':>9} {'PRICE/YR':>9}  VALUE")
    for r in rows:
        print(f"{r['ticker']:11} {r['grade']:5} {pct(r['pe_change']):>10}  {pct(r['profit_growth']):>9} {pct(r['price_growth']):>9}  "
              f"{(r.get('value') or {}).get('signal', '')}")
    missing = [e["ticker"] for e in entries if e["ticker"] not in raw]
    if missing:
        print(f"\nNo figures for: {', '.join(missing)} – run again later (the cache keeps the rest).")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
