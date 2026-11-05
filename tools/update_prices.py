"""Fetch the latest closing share prices from Yahoo Finance and save them into data/companies/*.yaml.

    python tools/update_prices.py --dry-run           # show the changes, write nothing
    python tools/update_prices.py                     # update every company file
    python tools/update_prices.py --tickers CCJ,AEM   # update only these
    python tools/update_prices.py --folder nifty50     # a separate company folder, data/nifty50/companies

Only the value, date and source lines of each file's price block change. A company is skipped, and its file left
alone, if Yahoo has no price, quotes a different currency, or the price moved more than MAX_MOVE from the stored one.
Metal spot prices stay in config.yaml; this script does not touch them.
"""
import argparse
import re
import sys
import warnings
from pathlib import Path

import yaml
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import loader  # noqa: E402
MAX_MOVE = 0.5  # a bigger move is more likely a bad quote than a real one, so it needs a look by hand
MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100)}  # London shares are often quoted in pence


def fetch(symbol):
    """Returns (close, date, currency), with minor units such as pence converted, or None if there is no price."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="10d", auto_adjust=False)
    if hist is None or hist.empty:
        return None
    currency = ticker.history_metadata.get("currency")
    currency, divisor = MINOR_UNITS.get(currency, (currency, 1))
    return float(hist["Close"].iloc[-1]) / divisor, str(hist.index[-1].date()), currency


def patch_price(text, value, date, source):
    """Rewrites three lines of the price block, leaving the rest of the file exactly as it was."""
    for key, new in (("value", value), ("date", f"'{date}'"), ("source", source)):
        pattern = rf"(?m)^(price:\n(?:  .*\n)*?  {key}: ).*$"
        text = re.sub(pattern, lambda m: f"{m.group(1)}{new}", text, count=1)
    return text


def update_file(path, wanted, dry_run):
    """Updates one company file. Returns (ticker, status, message), or None if the ticker was not requested."""
    text = path.read_text(encoding="utf-8")
    company = yaml.safe_load(text)
    ticker = company["ticker"]
    if wanted and ticker not in wanted:
        return None
    symbol = company.get("yahoo", ticker)
    old = company["price"]
    try:
        got = fetch(symbol)
    except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the rest
        return ticker, "skipped", f"{symbol}: fetch failed ({e.__class__.__name__})"
    if got is None:
        return ticker, "skipped", f"{symbol}: no price from Yahoo"
    close, date, currency = got
    if currency != old["currency"]:
        return ticker, "skipped", f"{symbol}: Yahoo quotes {currency}, file uses {old['currency']}"
    if str(date) < str(old["date"]):
        return ticker, "skipped", f"{symbol}: Yahoo's {date} is older than the file's {old['date']}"
    move = close / old["value"] - 1
    if abs(move) > MAX_MOVE:
        return ticker, "skipped", f"{symbol}: {old['value']} -> {close:.4f} ({move:+.0%}) looks wrong; check by hand"

    value = round(close, 4)
    source = f"yfinance {symbol}"
    new_text = patch_price(text, value, date, source)
    expected = {**old, "value": value, "date": date, "source": source}
    if yaml.safe_load(new_text)["price"] != expected:
        return ticker, "skipped", "could not edit the price block; update it by hand"
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return ticker, "updated", f"{old['value']} -> {value} {currency} ({move:+.1%}), {old['date']} -> {date}"


def main():
    ap = argparse.ArgumentParser(description="Save the latest share prices into data/companies/*.yaml")
    ap.add_argument("--tickers", help="comma-separated tickers, e.g. CCJ,AEM (default: every company file)")
    ap.add_argument("--folder", help="company folder, e.g. nifty50 for data/nifty50/companies (default: data/companies)")
    ap.add_argument("--dry-run", action="store_true", help="show the changes without writing any file")
    args = ap.parse_args()
    try:
        companies = loader.companies_folder(args.folder)
    except loader.ValidationError as e:
        ap.error(str(e))
    wanted = {t.strip().upper() for t in args.tickers.split(",")} if args.tickers else None

    results = [r for r in (update_file(p, wanted, args.dry_run) for p in sorted(companies.glob("*.yaml"))) if r]
    for ticker, status, message in results:
        print(f"{status:8} {ticker:6} {message}")
    for ticker in sorted((wanted or set()) - {r[0] for r in results}):
        print(f"skipped  {ticker:6} no company file with this ticker")
    updated = sum(r[1] == "updated" for r in results)
    print(f"\n{updated} of {len(results)} {'would be updated (dry run)' if args.dry_run else 'updated'}")
    return 0 if updated else 1


if __name__ == "__main__":
    sys.exit(main())
