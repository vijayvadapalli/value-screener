"""Net cash for Indian company files that do not have it yet, from Yahoo's latest quarterly balance sheet.

    python tools/fill_net_cash.py midcap150             # files whose balance is still the placeholder (net cash 0)
    python tools/fill_net_cash.py midcap150 --all       # every file in the list's folder (a refresh)
    python tools/fill_net_cash.py midcap150 --dry-run   # show what would change, write nothing

Net cash = cash & short-term investments − Yahoo's total debt (which usually includes leases; the hand-entered
StockAnalysis figure can be higher), in millions like the share count. Banks,
lenders and insurers are skipped: their valuation uses no net cash. Each filled file says where the figure came from
and its date, marked as derived – check a few against the annual report (or StockAnalysis) before relying on them.
Needs yfinance.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import loader, v2  # noqa: E402

PLACEHOLDER = {"net_cash": 0.0}
CASH = ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
DEBT = ("Total Debt",)
NOTE_PREFIX = "Net cash derived"
OLD_NOTE = "Net cash not yet added"


def latest(frame, names):
    """(value, date) from the most recent column that has a figure, or (None, None)."""
    if frame is None or frame.empty:
        return None, None
    for name in names:
        if name in frame.index:
            row = frame.loc[name].dropna()
            if len(row):
                d = max(row.index)
                return float(row[d]), d.date()
    return None, None


def balance_from_yahoo(symbol: str) -> dict | None:
    """{cash, debt, date, currency} in millions from the latest quarterly (else annual) balance sheet, or None."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = yf.Ticker(symbol)
        for sheet in (t.quarterly_balance_sheet, t.balance_sheet):
            cash, day = latest(sheet, CASH)
            debt, _ = latest(sheet, DEBT)
            if cash is not None:
                ccy = (t.info or {}).get("financialCurrency") or "INR"
                return {"cash": round(cash / 1e6, 1), "debt": round((debt or 0.0) / 1e6, 1), "date": day, "currency": ccy}
    return None


def apply(c: dict, b: dict) -> dict:
    """The company file with the derived balance and a dated note in its assumptions (replacing any older one)."""
    c = dict(c)
    c["balance"] = {"cash": b["cash"], "debt": b["debt"]}
    note = (f"{NOTE_PREFIX} from Yahoo's balance sheet ({b['date']:%d %b %Y}): cash & short-term investments "
            f"₹{b['cash'] / 10:,.0f} cr − total debt ₹{b['debt'] / 10:,.0f} cr (Yahoo's figure; usually includes leases) – "
            "check against the annual report")
    c["assumptions"] = [a for a in c.get("assumptions", []) if not str(a).startswith((NOTE_PREFIX, OLD_NOTE))] + [note]
    return c


def main():
    ap = argparse.ArgumentParser(description="Fill net cash from Yahoo's balance sheet")
    ap.add_argument("list", help="a list in data/lists, e.g. midcap150")
    ap.add_argument("--all", action="store_true", help="refresh every file, not just the ones without net cash")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = loader.load_config()
    folder = loader.companies_folder(loader.list_folder(args.list))
    done, skipped, failed = [], [], []
    for path in sorted(folder.glob("*.yaml")):
        c = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not args.all and c.get("balance") not in (None, PLACEHOLDER):
            continue
        if c.get("v2") and v2.kind_of(c, cfg) == "financial":
            skipped.append(c["ticker"])
            continue
        try:
            b = balance_from_yahoo(c.get("yahoo") or f"{c['ticker']}.NS")
        except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the run
            failed.append((c["ticker"], str(e)))
            continue
        if b is None or b["currency"] != c.get("currency", "INR"):
            failed.append((c["ticker"], "no balance sheet" if b is None else f"statements in {b['currency']}"))
            continue
        print(f"  {c['ticker']:12} cash {b['cash']:>12,.0f}m  debt {b['debt']:>12,.0f}m  ({b['date']})")
        if not args.dry_run:
            path.write_text(yaml.safe_dump(apply(c, b), sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")
        done.append(c["ticker"])
        time.sleep(0.5)
    print(f"\n{'Would fill' if args.dry_run else 'Filled'} {len(done)}; skipped {len(skipped)} financials; {len(failed)} failed")
    for t, why in failed:
        print(f"  {t}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
