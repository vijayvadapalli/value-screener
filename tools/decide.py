"""Adds an entry to a list's PRIVATE decision log, data/private/decisions/<list>.yaml (git-ignored).

    python tools/decide.py AEM wait "RSI 34, not oversold yet; support 152 holds"
    python tools/decide.py FNV buy "first third at support" --price 181.40 --public
    python tools/decide.py CCJ trim "above the 25x sell line" --list core --date 2026-11-14

The core report shows the buy-zone and review lists with the log beside them (valuescreen/buy_zone.py). Only entries
added with --public (`public: true`) appear in the published report; the whole log is on the private page
output/private/<list>-decisions.html after the next run. Edit the YAML by hand to change or remove an entry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from valuescreen import buy_zone, loader  # noqa: E402

DECISIONS = ("buy", "add", "hold", "wait", "skip", "trim", "sell", "review")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Add an entry to a list's private decision log.")
    ap.add_argument("ticker")
    ap.add_argument("decision", help="one of: " + ", ".join(DECISIONS))
    ap.add_argument("note", nargs="?", default="", help="why – one line")
    ap.add_argument("--list", default="core")
    ap.add_argument("--price", type=float, help="the price you acted at (optional)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--public", action="store_true", help="show this entry in the published report")
    a = ap.parse_args(argv)
    ticker, decision = a.ticker.upper(), a.decision.lower()
    if decision not in DECISIONS:
        ap.error(f"decision must be one of: {', '.join(DECISIONS)}")
    members = {t.upper() for t in loader.load_list(a.list)}
    if ticker not in members:
        ap.error(f"{ticker} is not in the {a.list} list")
    date = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    entry = {"date": date, "ticker": ticker, "decision": decision, "price": a.price, "note": a.note or None,
             "public": True if a.public else None}
    path = buy_zone.append_decision(a.list, entry)
    print(f"added to {path.relative_to(ROOT)}: {date} {ticker} {decision}" + (" (public)" if a.public else " (private)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
