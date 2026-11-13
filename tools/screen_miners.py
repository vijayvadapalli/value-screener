"""Quick screen of every miner in the ETF list – which ones deserve a full company file.

    python tools/make_etf_list.py miners GDX GDXJ SIL SILJ COPX URNM URNJ   # once, or to refresh the holdings
    python tools/screen_miners.py                      # screen all ~270 (about 5 minutes the first time each day)
    python tools/screen_miners.py --promote            # also write draft company files for the shortlist
    python tools/screen_miners.py --promote EDV.TO,NST.AX   # ... or for these tickers
    python tools/screen_miners.py --refresh            # ignore today's cached Yahoo figures

Writes output/miners/Miners_Screen_<date>.html and copies it to reports/miners-screen.html. Draft company files go to
data/miners/companies (never overwritten); `python -m valuescreen run --list miners` then values the companies that
have files. Method: valuescreen/miner_screen.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import growth_data, loader  # noqa: E402
from valuescreen import miner_screen as ms  # noqa: E402


def add_holdings(entries: list[dict], list_name: str) -> tuple[list[dict], set]:
    """The screen's entries plus your holdings from data/lists/<list_name>.yaml (Yahoo symbols from your company files).
    Returns (entries, tickers that are held). A holding already in the ETF list is tagged, not added twice."""
    companies = loader.load_companies()
    by_symbol = {e["yahoo"].upper(): e for e in entries}
    held = set()
    for h in loader.load_list_entries(list_name):
        c = companies.get(h["ticker"], {})
        symbol = (c.get("yahoo") or h["ticker"]).upper()
        match = by_symbol.get(symbol) or by_symbol.get(h["ticker"])
        if match is None:
            match = {"ticker": h["ticker"], "yahoo": symbol, "name": c.get("name", h["ticker"]), "metals": [c.get("sector", "other")],
                     "etfs": ["your portfolio"]}
            entries.append(match)
            by_symbol[symbol] = match
        held.add(match["ticker"])
    return entries, held


def main():
    ap = argparse.ArgumentParser(description="Quick screen of a list of miners from Yahoo's figures")
    ap.add_argument("--list", default="miners", help="list in data/lists made by make_etf_list.py (default: miners)")
    ap.add_argument("--promote", nargs="?", const="shortlist", help="write draft company files: the shortlist, or comma-separated tickers")
    ap.add_argument("--refresh", action="store_true", help="fetch again even if today's figures are cached")
    ap.add_argument("--holdings", default="portfolio", help="also show the companies in this list, tagged 'held' (default: portfolio; "
                                                            "'none' to leave them out). Read only – your files are not touched")
    args = ap.parse_args()
    name = args.list.lower()
    list_file = ROOT / "data" / "lists" / f"{name}.yaml"
    if not list_file.exists():
        sys.exit(f"No list at {list_file}. Make it first: python tools/make_etf_list.py {name} GDX GDXJ SIL SILJ COPX URNM URNJ")
    meta = yaml.safe_load(list_file.read_text(encoding="utf-8"))
    folder = meta.get("folder") or name
    entries = loader.load_list_entries(name)
    held = set()
    if args.holdings.lower() != "none":
        entries, held = add_holdings(entries, args.holdings.lower())
    today = dt.date.today()
    out = loader.output_folder(folder)
    # two at a time: Yahoo rate-limits bigger bursts on a list this long (failures are retried on the next run)
    raw = growth_data.collect(entries, {}, folder, out / "screen_cache" / f"{name}-{today}.json", args.refresh, workers=2)

    rows = ms.with_grades([ms.evaluate(raw[e["ticker"]], e) for e in entries if e["ticker"] in raw], raw)
    rows.sort(key=ms.sort_key)
    missing = [e["ticker"] for e in entries if e["ticker"] not in raw]
    in_files = ms.tickers_in_files(loader.company_folders().values())
    for r in rows:
        r["held"] = r["ticker"] in held
    etfs = sorted({x for e in entries for x in e.get("etfs", [])})
    title = f"{name.replace('_', ' ').title()}"
    path = ms.build(rows, out / f"{title.replace(' ', '_')}_Screen_{today:%d%b%Y}.html", title, today, etfs, in_files, missing)
    published = loader.publish(path, name, "-screen.html")

    short = ms.shortlist(rows)
    print(f"\n{len(rows)} screened, {len(missing)} without figures. Shortlist ({len(short)}):")
    for r in short:
        print(f"  {r['ticker']:10} {r['name'][:34]:34} {', '.join(r['metals']):14} MoS {r['mos']*100:+4.0f}%  "
              f"FCF yield {r['fcf_yield']*100:4.1f}%  grade {r['grade']}{'  (in your files)' if r['ticker'] in in_files else ''}")
    if args.promote:
        chosen = short if args.promote == "shortlist" else [r for r in rows if r["ticker"] in {t.strip().upper() for t in args.promote.split(",")}]
        chosen = [r for r in chosen if r["stage"] == "producer" and r["ticker"] not in in_files]
        written, kept = ms.write_drafts(chosen, raw, loader.companies_folder(folder), today)
        print(f"\nDraft company files written to data/{folder}/companies: {', '.join(written) or 'none'}"
              + (f"; already there: {', '.join(kept)}" if kept else ""))
        if written:
            print(f"Next: python tools/update_results.py --folder {folder} --tickers {','.join(written[:5])} --force --dry-run\n"
                  f"      python -m valuescreen run --list {name}")
    print(f"\nReport: {path}\nPublished copy: {published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
