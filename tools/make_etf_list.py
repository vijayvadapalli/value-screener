"""A list file from ETF holdings – the universe for a quick screen.

    python tools/make_etf_list.py miners GDX GDXJ SIL SILJ COPX URNM URNJ

Writes data/lists/<name>.yaml with `folder: <name>`: one entry per company (its US listing when an ETF holds that),
with its Yahoo symbol, name, metals and ETFs. Every symbol is checked against Yahoo with one bulk price download;
Toronto names Yahoo does not know on the main exchange are tried on the Venture exchange (.V), and names with no price
at all are left out and listed. Run it again whenever you want the latest holdings. Funds: valuescreen/etf_holdings.py.
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
from valuescreen import etf_holdings  # noqa: E402


def priced(symbols):
    """The symbols Yahoo has a recent close for (one bulk download)."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)   # Yahoo logs every unknown symbol; the summary lists them
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = yf.download(sorted(symbols), period="5d", progress=False, auto_adjust=False, threads=True)["Close"]
    return {s for s in data.columns if data[s].notna().any()} if hasattr(data, "columns") else set()


def main():
    ap = argparse.ArgumentParser(description="Make a list file from ETF holdings")
    ap.add_argument("name", help="list name, e.g. miners")
    ap.add_argument("etfs", nargs="+", help=f"ETFs: {', '.join(etf_holdings.FUNDS)}")
    args = ap.parse_args()
    etfs = [e.upper() for e in args.etfs]
    unknown = [e for e in etfs if e not in etf_holdings.FUNDS]
    if unknown:
        ap.error(f"unknown ETF(s): {', '.join(unknown)} – known: {', '.join(etf_holdings.FUNDS)}")
    entries = etf_holdings.universe(etfs)
    print(f"{len(entries)} companies in {', '.join(etfs)}; checking Yahoo symbols...")
    ok = priced(e["yahoo"] for e in entries)
    retry = {e["yahoo"]: e["yahoo"][:-3] + ".V" for e in entries if e["yahoo"] not in ok and e["yahoo"].endswith(".TO")}
    ok |= priced(retry.values()) if retry else set()
    kept, dropped = [], []
    for e in entries:
        if e["yahoo"] not in ok and retry.get(e["yahoo"]) in ok:
            e["ticker"] = e["yahoo"] = retry[e["yahoo"]]
        (kept if e["yahoo"] in ok else dropped).append(e)
    path = ROOT / "data" / "lists" / f"{args.name.lower()}.yaml"
    path.write_text(f"# Written by tools/make_etf_list.py from {', '.join(etfs)} holdings on {dt.date.today()}. Re-run it to refresh.\n"
                    + yaml.safe_dump({"name": f"{args.name} ({', '.join(etfs)})", "folder": args.name.lower(), "tickers": kept},
                                     sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
    print(f"Wrote {len(kept)} companies to {path.relative_to(ROOT)}")
    if dropped:
        print(f"No Yahoo price, left out ({len(dropped)}): " + ", ".join(f"{e['yahoo']} ({e['name']})" for e in dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
