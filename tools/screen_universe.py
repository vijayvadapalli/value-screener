"""First-pass screen of a large list from free Yahoo Finance data, before spending effort on quarterly results.

    python tools/make_nse_list.py nifty50                       # once: writes data/lists/nifty50.yaml
    python tools/screen_universe.py nifty50                     # screen every company in the list
    python tools/screen_universe.py nifty50 --promote           # also write draft company files for the shortlist
    python tools/screen_universe.py nifty50 --promote-all       # ... for every valued company, flagged ones included
    python tools/screen_universe.py nifty50 --refresh           # ignore today's cached Yahoo data

Everything for a list stays in its own folder: the list's `folder:` (nifty50) means company files in
data/nifty50/companies and results, cache and backups in output/nifty50, apart from your other companies.

Each company is valued with the same growth model as the tech stocks: no-growth value from its last full fiscal year's
net income and net cash, and the growth the share price already assumes. BUY and WATCH companies are the shortlist.
Banks and other financial companies are skipped, because owner earnings and net cash mean something different there.

This is a rough filter on unverified numbers (annual, up to a year old, total capex not sustaining capex). Drafts written
by --promote say so. Next, for the shortlist only:  python tools/update_results.py --folder nifty50 --tickers X,Y --force
"""
import argparse
import datetime as dt
import json
import logging
import math
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import loader  # noqa: E402
from valuescreen.models import value_company  # noqa: E402
from valuescreen.rules import zone  # noqa: E402

LISTS = ROOT / "data" / "lists"
COMPANIES = loader.companies_folder()  # main() points these at data/<folder>/companies and output/<folder>
OUT = loader.output_folder()
SHORTLIST_ZONES = ("BUY", "WATCH")
FINANCIAL = "Financial Services"
WORKERS = 4  # Yahoo throttles heavy parallel use
SCHEMA = 3  # bump when the cached figures change shape, so old cache files are fetched again
EPS_RATIO_RANGE = (0.5, 2.0)  # a full-year EPS this far from Yahoo's trailing EPS usually means a one-off or corporate action
AMOUNTS = ("net_income", "da", "capex", "ocf", "cash", "debt")  # statement figures that follow the statements' currency
KEYS = {
    "net_income": ("Net Income Common Stockholders", "Net Income"),
    "da": ("Depreciation And Amortization", "Depreciation Amortization Depletion"),
    "capex": ("Capital Expenditure",),
    "ocf": ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
    "debt": ("Total Debt",),
}


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN


def _pick(frame, names, column):
    """The first of `names` that has a figure for the fiscal year in `column`, else None."""
    if frame is None or frame.empty or column not in frame.columns:
        return None
    for name in names:
        if name in frame.index and _num(frame.at[name, column]) is not None:
            return _num(frame.at[name, column])
    return None


def choose_fx(raw, rate):
    """Converts the statements into the price currency, unless Yahoo's currency label looks wrong.

    Yahoo labels some companies' statements as USD (INFY really is) but the same label sits on rupee figures (HCLTECH).
    The label is trusted only when converting brings the year's EPS closer to Yahoo's trailing EPS, which is always
    in the price currency.
    """
    net_income, shares, trailing = raw.get("net_income"), raw.get("shares"), raw.get("trailing_eps")
    if net_income and shares and trailing and net_income > 0 and trailing > 0:
        eps = net_income / shares
        if abs(math.log(eps * rate / trailing)) >= abs(math.log(eps / trailing)):
            return {**raw, "fx": 1.0, "fx_note": f"Yahoo labels the statements {raw['statements_currency']} but the figures "
                                                  f"look like {raw['currency']}, so they were not converted"}
    return {**raw, **{k: raw[k] * rate for k in AMOUNTS if raw.get(k) is not None}, "fx": rate}


def fetch(symbol):
    """Raw Yahoo figures for one company, in the price currency and shares (not millions). {'error': ...} on failure."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="10d", auto_adjust=False)
            income, cash_flow, balance = ticker.financials, ticker.cashflow, ticker.balance_sheet
            quick, info = ticker.fast_info, ticker.info
            currency, shares = quick["currency"], _num(quick["shares"])
            statements_currency = info.get("financialCurrency") or currency
            rate = None
            if statements_currency != currency:
                pair = yf.Ticker(f"{statements_currency}{currency}=X").history(period="5d")
                rate = None if pair is None or pair.empty else float(pair["Close"].iloc[-1])
    except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the run
        return {"error": f"Yahoo lookup failed ({e.__class__.__name__})"}
    if statements_currency != currency and rate is None:
        return {"error": f"statements are in {statements_currency} and there is no {statements_currency}/{currency} rate"}
    if history is None or history.empty:
        return {"error": "no price from Yahoo"}
    if income is None or income.empty:
        return {"error": "no annual statements from Yahoo"}
    column = income.columns[0]
    raw = {"v": SCHEMA, "price": float(history["Close"].iloc[-1]), "price_date": str(history.index[-1].date()),
           "currency": currency, "shares": shares, "period_end": str(column.date()), "fx": 1.0,
           "statements_currency": statements_currency, "trailing_eps": _num(info.get("trailingEps"))}
    for key, names in KEYS.items():
        frame = {"net_income": income, "da": cash_flow, "capex": cash_flow, "ocf": cash_flow}.get(key, balance)
        raw[key] = _pick(frame, names, column)
    return raw if rate is None else choose_fx(raw, rate)


def period_label(end):
    end = dt.date.fromisoformat(end)
    return f"FY{str(end.year)[2:]} ({end.strftime('%b')})"  # year ended March 2026 -> FY26 (Mar)


def build_company(entry, raw):
    """A company dict in the format the valuation models read, from raw Yahoo figures."""
    return {
        "ticker": entry["ticker"], "yahoo": entry["yahoo"], "name": entry["name"], "sector": entry.get("industry", ""),
        "model": "growth", "currency": raw["currency"],
        "period": {"label": period_label(raw["period_end"]), "end": dt.date.fromisoformat(raw["period_end"]), "per_year": 1},
        "earnings": {"net_income": round(raw["net_income"] / 1e6, 3)},
        "shares_m": round(raw["shares"] / 1e6, 6),
        "balance": {"cash": round(raw["cash"] / 1e6, 3), "debt": round((raw["debt"] or 0.0) / 1e6, 3)},
        "price": {"value": round(raw["price"], 4), "currency": raw["currency"], "date": dt.date.fromisoformat(raw["price_date"]),
                  "source": f"yfinance {entry['yahoo']}"},
        "sources": [], "assumptions": [], "notes": [],
    }


def screen_one(entry, raw, cfg):
    """Returns ('row', dict) for a valued company or ('skip', reason)."""
    if raw.get("error"):
        return "skip", raw["error"]
    if entry.get("industry") == FINANCIAL:
        return "skip", "financial company: owner earnings and net cash don't fit; compare P/E and P/B by hand"
    if raw["currency"] != "INR":
        return "skip", f"quoted in {raw['currency']}, not INR"
    for key, label in (("shares", "share count"), ("net_income", "net income"), ("cash", "cash")):
        if raw.get(key) is None:
            return "skip", f"no {label} from Yahoo for the year ended {raw['period_end']}"
    if raw["net_income"] <= 0:
        return "skip", "net income is not positive"
    company = build_company(entry, raw)
    result = value_company(company, cfg)
    result.update(zone(result, company, cfg))
    market_cap = raw["price"] * raw["shares"]
    flag, eps = None, raw["net_income"] / raw["shares"]
    trailing = raw.get("trailing_eps")
    if trailing is not None and (trailing <= 0 or not EPS_RATIO_RANGE[0] <= eps / trailing <= EPS_RATIO_RANGE[1]):
        flag = f"year's EPS {eps:.1f} vs Yahoo trailing EPS {trailing:.1f}: a one-off or corporate action? check the filing"
    note = raw.get("fx_note") or (f"statements converted from {raw['statements_currency']} at {raw['fx']:.2f}"
                                  if raw.get("fx", 1.0) != 1.0 else None)
    fcf = None if raw["ocf"] is None or raw["capex"] is None else raw["ocf"] + raw["capex"]  # Yahoo capex is negative
    return "row", {"entry": entry, "raw": raw, "company": company, "ticker": entry["ticker"], "name": entry["name"],
                   "industry": entry.get("industry", ""), "price": raw["price"], "v0": result["v0"],
                   "implied_growth": result["implied_growth"], "pe": result["pe"], "zone": result["zone"],
                   "fcf_yield": None if fcf is None else fcf / market_cap, "period": company["period"]["label"],
                   "period_end": raw["period_end"], "flag": flag, "note": note}


def load_raw(entries, name, refresh):
    """Yahoo figures for every entry, cached per list and day so a re-run does not fetch again."""
    cache_file = OUT / "screen_cache" / f"{name}-{dt.date.today().isoformat()}.json"
    cache = {} if refresh or not cache_file.exists() else json.loads(cache_file.read_text())
    todo = [e for e in entries if e["ticker"] not in cache or cache[e["ticker"]].get("error") or cache[e["ticker"]].get("v") != SCHEMA]
    if todo:
        print(f"Fetching {len(todo)} companies from Yahoo ({len(entries) - len(todo)} from today's cache)...", flush=True)
        with ThreadPoolExecutor(WORKERS) as pool:
            for entry, raw in zip(todo, pool.map(lambda e: fetch(e["yahoo"]), todo)):
                cache[entry["ticker"]] = raw
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return cache


def shortlist(rows):
    """BUY and WATCH companies, leaving out any whose figures look suspect."""
    return [r for r in rows if r["zone"] in SHORTLIST_ZONES and not r["flag"]]


def draft_file(row, today):
    """The company file text for a screened company, from the Yahoo figures."""
    company = row["company"]
    company["sources"] = [f"Yahoo Finance annual statements via yfinance, fetched {today.isoformat()} (unverified draft)"]
    company["notes"] = [row["note"]] if row["note"] else []
    company["assumptions"] = ([f"CHECK before relying on it: {row['flag']}"] if row["flag"] else []) + [
        f"DRAFT from Yahoo's annual figures ({company['period']['label']}), not checked against the filings",
        "Placeholder: replace with the most recent reported quarter (single-quarter net income, per_year 4), then remove this DRAFT note",
    ]
    company["period"] = {**company["period"], "end": company["period"]["end"].isoformat()}
    company["price"] = {**company["price"], "date": company["price"]["date"].isoformat()}
    return yaml.safe_dump(company, sort_keys=False, allow_unicode=True, width=140)


def promote(rows, today):
    written, kept = [], []
    COMPANIES.mkdir(parents=True, exist_ok=True)
    for row in rows:
        path = COMPANIES / f"{row['ticker'].lower()}.yaml"
        if path.exists():
            kept.append(row["ticker"])
            continue
        path.write_text(draft_file(row, today), encoding="utf-8")
        written.append(row["ticker"])
    return written, kept


def fmt_pct(x):
    return "" if x is None else f"{x * 100:+.1f}%"


def main():
    ap = argparse.ArgumentParser(description="Screen a list from free Yahoo data and shortlist the cheap ones")
    ap.add_argument("list", help="a list in data/lists with a yahoo symbol per entry, e.g. nifty50")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--promote", action="store_true", help="write draft company files for the shortlist (never overwrites)")
    which.add_argument("--promote-all", action="store_true",
                       help="write draft company files for every valued company, flagged ones included (never overwrites)")
    ap.add_argument("--refresh", action="store_true", help="ignore today's cached Yahoo data")
    args = ap.parse_args()

    path = LISTS / f"{args.list.lower()}.yaml"
    if not path.exists():
        sys.exit(f"No list at {path}. For NSE indexes run: python tools/make_nse_list.py {args.list}")
    entries = [e for e in yaml.safe_load(path.read_text(encoding="utf-8"))["tickers"] if isinstance(e, dict) and e.get("yahoo")]
    if not entries:
        sys.exit("This list has no entries with a yahoo symbol.")
    try:
        import yfinance  # noqa: F401, PLC0415
    except ImportError:
        sys.exit("The yfinance package is missing. Run: pip install yfinance")

    global COMPANIES, OUT
    folder = yaml.safe_load(path.read_text(encoding="utf-8")).get("folder") or args.list.lower()
    COMPANIES, OUT = loader.companies_folder(folder), loader.output_folder(folder)
    print(f"Company files: {COMPANIES.relative_to(ROOT)}   Results: {OUT.relative_to(ROOT)}")

    cfg = loader.load_config()
    raw = load_raw(entries, args.list.lower(), args.refresh)
    rows, skipped = [], []
    for entry in entries:
        kind, value = screen_one(entry, raw[entry["ticker"]], cfg)
        (rows if kind == "row" else skipped).append(value if kind == "row" else (entry["ticker"], value))
    rows.sort(key=lambda r: (r["implied_growth"] is None, r["implied_growth"] if r["implied_growth"] is not None else 0))

    print(f"\n{len(rows)} valued, {len(skipped)} skipped, of {len(entries)} in {args.list}\n")
    print(f"{'#':>3} {'TICKER':11} {'PRICE':>9} {'NO-GROWTH':>9} {'NEEDS':>7} {'P/E':>5} {'FCF YLD':>8}  {'DATA':11} ZONE")
    for i, r in enumerate(rows, 1):
        pe = "" if r["pe"] is None else f"{r['pe']:.1f}"
        print(f"{i:>3} {r['ticker']:11} {r['price']:>9,.1f} {r['v0']:>9,.1f} {fmt_pct(r['implied_growth']):>7} {pe:>5} "
              f"{fmt_pct(r['fcf_yield']):>8}  {r['period']:11} {r['zone']}{'  (flagged)' if r['flag'] else ''}")
    flagged = [r for r in rows if r["flag"]]
    if flagged:
        print("\nFlagged, so not shortlisted:")
        for r in flagged:
            print(f"  {r['ticker']:11} {r['flag']}")
    for r in rows:
        if r["note"]:
            print(f"Note: {r['ticker']} {r['note']}")
    if skipped:
        print("\nSkipped:")
        for ticker, reason in skipped:
            print(f"  {ticker:11} {reason}")

    picked = shortlist(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / f"screen_{args.list.lower()}.csv"
    cols = ["ticker", "name", "industry", "price", "v0", "implied_growth", "pe", "fcf_yield", "period_end", "zone"]
    csv_path.write_text("\n".join([",".join(cols)] + [",".join('"%s"' % r[c] if c in ("name", "industry") else str(r[c]) for c in cols)
                                                      for r in rows]) + "\n", encoding="utf-8")
    print(f"\nShortlist ({len(picked)}): {', '.join(r['ticker'] for r in picked) or 'none'}   ·   table: {csv_path}")
    print("Check before trusting it: net income is a full unadjusted year, and a negative FCF yield means capex is eating the earnings.")

    chosen = rows if args.promote_all else picked if args.promote else []
    if chosen:
        written, kept = promote(chosen, dt.date.today())
        if written:
            print(f"\nDraft company files written to {COMPANIES.relative_to(ROOT)} for: {', '.join(written)}")
        if kept:
            print(f"Already had a file, left alone: {', '.join(kept)}")
        print(f"\nNext: python -m valuescreen validate   then   python tools/update_prices.py --folder {folder}")
        print(f"To replace drafts with the latest quarter (each company costs API credit, so pick a few):\n"
              f"  python tools/update_results.py --folder {folder} --tickers {','.join(r['ticker'] for r in picked[:3])} --force --dry-run")
    elif picked:
        print("Add --promote (shortlist) or --promote-all (every valued company) to write draft company files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
