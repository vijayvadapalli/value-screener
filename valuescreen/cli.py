"""Command line.

  python -m valuescreen run --all
  python -m valuescreen run --list watchlist
  python -m valuescreen run --tickers AEM,NEM,HL --spot gold=4100,silver=52
  python -m valuescreen run --etf URNM
  python -m valuescreen run --list portfolio --live
  python -m valuescreen validate
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import loader, prices, report
from .engine import etf_lookthrough, ranked, run


def _parse_spot(s):
    out = {}
    for part in (s or "").split(","):
        if part.strip():
            k, v = part.split("=")
            out[k.strip().lower()] = float(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="valuescreen", description="Value vs price screener")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="value companies and write reports")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="every company file")
    g.add_argument("--tickers", help="comma-separated tickers, e.g. AEM,NEM,HL")
    g.add_argument("--list", help="a list in data/lists, e.g. watchlist or portfolio")
    r.add_argument("--etf", action="append", default=[], help="ETF look-through, e.g. URNM (repeatable)")
    r.add_argument("--live", action="store_true", help="fetch live share and metal prices (needs yfinance)")
    r.add_argument("--spot", help="override spot, e.g. gold=4100,silver=52,uranium=95")
    r.add_argument("--asof", help="date for stale checks (default: config as_of, or today with --live)")
    r.add_argument("--out", default=str(loader.ROOT / "output"), help="output folder")
    r.add_argument("--config", help="path to config.yaml")
    sub.add_parser("validate", help="check every company file")
    a = ap.parse_args(argv)

    cfg = loader.load_config(Path(a.config) if getattr(a, "config", None) else None)
    companies = loader.load_companies()
    if a.cmd == "validate":
        print(f"{len(companies)} company files valid: {', '.join(sorted(companies))}")
        return 0

    log = []
    if a.asof:
        cfg["as_of"] = dt.date.fromisoformat(a.asof)
    elif a.live:
        cfg["as_of"] = prices.today()
    etfs = [loader.load_etf(x) for x in a.etf]
    if a.tickers:
        tickers = [t.strip().upper() for t in a.tickers.split(",")]
    elif a.list:
        tickers = loader.load_list(a.list)
    elif a.all or not etfs:
        tickers = sorted(companies)
    else:
        tickers = []
    for e in etfs:  # make sure ETF holdings we have files for are valued
        tickers += [h["ticker"].upper() for h in e["holdings"] if h["ticker"].upper() in companies and h["ticker"].upper() not in tickers]
    missing = [t for t in tickers if t not in companies]
    if missing:
        log.append(f"no company file for: {', '.join(missing)} – skipped (add data/companies/<ticker>.yaml)")
        tickers = [t for t in tickers if t in companies]
    if a.live:
        log += prices.refresh_spot(cfg)
        log += prices.refresh_prices(companies, tickers)
    cfg["spot"].update(_parse_spot(a.spot))

    results = run(companies, tickers, cfg)
    vals, grow = ranked(results)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    report.write_csv(vals, grow, out / "ranked.csv")
    heat = report.make_heatmaps(vals, grow, cfg, out)
    lts = [(e["ticker"], etf_lookthrough(e, results), e) for e in etfs]
    report.write_html(vals, grow, lts, cfg, heat, out / "report.html", log)
    report.append_signals(vals, grow, out / "signals_log.csv", cfg["as_of"])

    # console summary
    for line in log:
        print("·", line)
    print(f"\nValue vs price · {cfg['as_of']} · gold {cfg['spot']['gold']:,.0f} silver {cfg['spot']['silver']:.2f} uranium {cfg['spot']['uranium']:.0f}")
    print(f"{'#':>3} {'TICKER':7} {'PRICE':>10} {'VALUE':>17} {'VAL/PX':>7} {'MoS':>6}  ZONE")
    for rr in vals:
        v = f"{rr['v_low']:,.2f}" + (f"–{rr['v_high']:,.2f}" if abs(rr['v_high'] - rr['v_low']) > 1e-9 else "")
        m_ = rr.get("margin_of_safety")
        mos = "" if m_ is None else ("<-200%" if m_ < -2 else f"{m_*100:+.0f}%")
        print(f"{rr['rank']:>3} {rr['ticker']:7} {rr['price']:>10,.2f} {v:>17} {rr['coverage_lo']*100:>6.0f}% {mos:>6}  {rr['zone']}")
    if grow:
        print(f"\n{'#':>3} {'TICKER':7} {'PRICE':>10} {'NO-GROWTH':>10} {'NEEDS':>9}  ZONE")
        for rr in grow:
            g_ = "" if rr["implied_growth"] is None else f"{rr['implied_growth']*100:+.1f}%"
            print(f"{rr['rank']:>3} {rr['ticker']:7} {rr['price']:>10,.2f} {rr['v0']:>10,.2f} {g_:>9}  {rr['zone']}")
    for name, lt, e in lts:
        if lt.get("ratio_lo"):
            print(f"\n{name}: valued holdings {lt['coverage_weight']:.1f}% of fund · look-through value {lt['ratio_lo']*100:.0f}–{lt['ratio_hi']*100:.0f}% "
                  f"of price → {lt['value_lo']:.2f}–{lt['value_hi']:.2f} vs {e['price']['value']:.2f}")
    print(f"\nReports: {out/'report.html'} · {out/'ranked.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
