"""Command line.

  python -m valuescreen run --all
  python -m valuescreen run --list watchlist
  python -m valuescreen run --tickers AEM,NEM,HL --spot gold=4100,silver=52
  python -m valuescreen run --etf URNM
  python -m valuescreen run --list core --live
  python -m valuescreen run --list core --technicals   # also 200-day average, RSI and MACD (needs yfinance)
  python -m valuescreen run --list nifty50          # a list with `folder: nifty50` uses data/nifty50/companies
  python -m valuescreen run --folder nifty50 --all  # the same folder without a list
  python -m valuescreen validate                    # every company folder

Each run writes to output/ (or output/<folder>), which git ignores:
  <List>_Value_vs_Price_<date>.html    the report – value and profit vs price, markets, charts, linked, sortable
  ranked.csv, signals_log.csv (one line per company per run), runs.json (previous figures shown in brackets),
  heatmaps and the profit-vs-price cache.
and copies the report to reports/<list>.html (core.html, ...) – the only reports git tracks and GitHub Pages publishes.
Profit-vs-price figures are fetched from Yahoo or Screener.in and cached per day; --no-profit skips them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import growth_data, growth_screen, history, html_report, loader, longterm, markets, price_chart, pricedb, prices, report
from . import buy_zone, price_cases, research, resource_screen, technicals
from . import profit_vs_price as pvp
from .wording import list_title
from .engine import etf_lookthrough, ranked, run


def _parser():
    ap = argparse.ArgumentParser(prog="valuescreen", description="Value vs price screener")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="value companies and write reports")
    which = r.add_mutually_exclusive_group()
    which.add_argument("--all", action="store_true", help="every company file")
    which.add_argument("--tickers", help="comma-separated tickers, e.g. AEM,NEM,HL")
    which.add_argument("--list", help="a list in data/lists, e.g. core or watchlist")
    r.add_argument("--folder", help="company folder: data/<folder>/companies, results in output/<folder> "
                                    "(default: the list's own `folder:`, else data/companies and output/)")
    r.add_argument("--etf", action="append", default=[], help="ETF look-through, e.g. URNM (repeatable)")
    r.add_argument("--live", action="store_true", help="fetch live share and metal prices (needs yfinance)")
    r.add_argument("--technicals", action="store_true", help="price vs 200-day average, RSI and MACD (needs yfinance)")
    r.add_argument("--spot", help="override spot, e.g. gold=4100,silver=52,uranium=95")
    r.add_argument("--asof", help="date for stale checks (default: config as_of, or today with --live)")
    r.add_argument("--out", help="folder for the dated reports and working files (default: output/ or output/<folder>); "
                                 "nothing is copied to reports/")
    r.add_argument("--config", help="path to config.yaml")
    r.add_argument("--no-profit", action="store_true", help="skip the profit-vs-price figures (no Yahoo / Screener.in calls)")
    sub.add_parser("validate", help="check every company file")
    b = sub.add_parser("backtest", help="how the growth screen's rules did: picks on a past date, returns since")
    b.add_argument("--list", required=True, help="a list with the growth screen (midcap150, nifty50, tech) or us (the S&P 500 + Nasdaq-100 screen)")
    b.add_argument("--years", type=int, default=5, help="the earliest start, in years before today (default 5; then every year to 2)")
    return ap


def _parse_spot(text):
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            metal, value = part.split("=")
            out[metal.strip().lower()] = float(value)
    return out


def _validate():
    for label, path in loader.company_folders().items():
        found = loader.load_companies(path)
        print(f"{len(found)} company files valid in {label}: {', '.join(sorted(found))}")
    return 0


def _pick_tickers(a, companies, etfs, folder, log):
    if a.tickers:
        tickers = [t.strip().upper() for t in a.tickers.split(",")]
    elif a.list:   # markets (commodities, indices, ETFs shown price-only) have no company file and are not valued
        tickers = [x["ticker"] for x in loader.load_list_entries(a.list) if not markets.is_market(x)]
    elif a.all or not etfs:
        tickers = sorted(companies)
    else:
        tickers = []
    for etf in etfs:  # value the ETF holdings we have files for
        tickers += [h["ticker"].upper() for h in etf["holdings"]
                    if h["ticker"].upper() in companies and h["ticker"].upper() not in tickers]
    missing = [t for t in tickers if t not in companies]
    if missing:
        where = loader.companies_folder(folder).relative_to(loader.ROOT)
        log.append(f"no company file for: {', '.join(missing)} – skipped (add {where}/<ticker>.yaml)")
    return [t for t in tickers if t in companies]


def _technicals(tickers, companies, log):
    found = {}
    for t in tickers:
        closes = technicals.fetch(companies[t]["yahoo"])
        if closes:
            found[t] = technicals.read(closes)
    missing = [t for t in tickers if t not in found]
    if missing:
        log.append(f"no price history for: {', '.join(missing)}")
    return found


def _price_charts(tickers, companies, results, log, years=None):
    """Chart data for each company from output/prices.sqlite (tools/update_history.py); {} when there is none. A list
    with `history_years:` above 10 gets that much monthly history and a Max button."""
    if not pricedb.DB.exists():
        log.append("no price charts: run python tools/update_history.py to download the price history")
        return {}
    con = pricedb.connect()
    weeks = research.load_weeks()   # private captures: only their plain support / resistance prices reach a public chart
    out, missing, old = {}, [], []
    for t in tickers:
        symbol = companies[t].get("yahoo") or t
        last = pricedb.last_date(con, symbol)
        if last is None:
            missing.append(symbol)
            continue
        if (dt.date.today() - dt.date.fromisoformat(last)).days > 5:
            old.append(f"{symbol} {last}")
        long = {"long_years": years} if years and years > price_chart.LONG_YEARS else {}
        p = price_chart.payload(con, symbol, results[t], companies[t], watched=research.public_levels(weeks, t, symbol), **long)
        if p:
            if long:
                p["max_range"] = True
            out[t] = p
    if missing:
        log.append("no price history for " + ", ".join(missing) + " – python tools/update_history.py --tickers " + ",".join(missing))
    if old:
        log.append("price history not updated recently: " + ", ".join(old) + " – run python tools/update_history.py")
    return out


METAL_SYMBOLS = {"gold": "GC=F", "silver": "SI=F", "copper": "HG=F", "oil": "CL=F"}


def _metal_growth(metal):
    """For the resource screen: a function years → the yearly change of `metal`'s price over that many years, from the
    price history (futures) or, for uranium, Cameco's month-end spot series; None where there is no series."""
    if metal == "uranium":
        points = [(d[:10], v) for d, v in longterm.series("uranium_spot")]
    elif metal in METAL_SYMBOLS and pricedb.DB.exists():
        points = [(b["date"], b["close"]) for b in pricedb.bars(pricedb.connect(), METAL_SYMBOLS[metal])]
    else:
        points = []

    def growth(years):
        if not points or not years:
            return None
        last_day, last = points[-1]
        start = (dt.date.fromisoformat(last_day) - dt.timedelta(days=round(365.25 * years))).isoformat()
        then = [v for d, v in points if d <= start]
        return (last / then[-1]) ** (1 / years) - 1 if then and then[-1] > 0 else None
    return growth


def _backtest(list_name, companies, cfg, settings, log):
    """The growth screen's rules on past dates (list setting `backtest: [5, 4, 3, 2]`), for the report."""
    years = settings.get("backtest")
    if not years or not pricedb.DB.exists():
        return []
    from . import backtest  # noqa: PLC0415
    if settings.get("screen") == "us-growth":   # US companies: rebuilt from the SEC figures filed by each start date
        from . import factsdb  # noqa: PLC0415
        db = loader.output_folder("us") / "us_facts.sqlite"
        if not db.exists():
            return []
        con = factsdb.connect(db)
        wanted = {x["ticker"] for x in loader.load_list_entries(list_name)}
        entries = [x for x in factsdb.companies(con) if x["ticker"] in wanted]
        results = backtest.run_us(entries, con, cfg, backtest.INDEX_SYMBOL.get(list_name, "^GSPC"), years=tuple(years))
    else:
        results = backtest.run(list_name, loader.load_list_entries(list_name), companies, cfg, years=tuple(years))
    log.append("backtest: " + " · ".join(f"since {b['start']:%b %Y} {len(b['picks'])} picks" for b in results))
    return results


def _us_growth_rows(results, companies, cfg, live, log):
    """The growth screen with the US rules for a list of US companies (the tech list): the list's own valuation, with
    the EPS history from the SEC figures the US screen keeps (output/us/us_facts.sqlite)."""
    from . import factsdb, us_pages, us_screen  # noqa: PLC0415
    db = loader.output_folder("us") / "us_facts.sqlite"
    if not db.exists():
        log.append("growth screen skipped: no SEC figures yet – run python tools/screen_us.py once")
        return [], {}
    con = factsdb.connect(db)
    wanted = {t for t, r in results.items() if r["model"] == "growth"}
    entries = [e for e in factsdb.companies(con) if e["ticker"] in wanted and not e["foreign"]]
    us_rows, _ = us_screen.rows_from_db(con, entries, cfg, dt.date.today(), loader.output_folder("us") / "screen_cache",
                                        log=lambda *_: None)
    by_t = {r["ticker"]: r for r in us_rows}
    if live and by_t:   # insider ownership from Yahoo, one call per company
        held = us_pages.insiders([companies[t].get("yahoo") or t for t in by_t])
        for t, r in by_t.items():
            r["insiders"] = held.get(companies[t].get("yahoo") or t)
    rows = sorted((growth_screen.evaluate_tech(results[t], by_t.get(t), cfg) for t in wanted), key=growth_screen.sort_key)
    return rows, {"key": "us_growth_screen", "owners": "Insiders", "tail": us_screen.US_SCREEN_TAIL.split(" The shortlist")[0]}


def _profit_rows(a, tickers, companies, results, folder, out, log):
    """Profit-vs-price rows for the run's companies; figures cached per day in output/<folder>/profit_vs_price_cache/."""
    entries = loader.load_list_entries(a.list) if a.list else [{"ticker": t} for t in tickers]
    entries = [x for x in entries if x["ticker"] in results]
    if a.list and loader.list_settings(a.list).get("profit") == "local":   # from the company files and price history
        con = pricedb.connect() if pricedb.DB.exists() else None
        raw = growth_data.collect_local(entries, companies, con)
        log.append(f"profit vs price: {len(raw)} of {len(entries)} from the company files and price history (no downloads)")
        return pvp.rows(entries, raw, results, companies)
    cache = out / "profit_vs_price_cache" / f"{a.list or folder or 'all'}-{dt.date.today().isoformat()}.json"
    raw = growth_data.collect(entries, companies, folder, cache, log=log.append)
    return pvp.rows(entries, raw, results, companies)


def _print_summary(cfg, vals, grow, lookthroughs, log, files):
    for line in log:
        print("·", line)
    sp = cfg["spot"]
    print(f"\nValue vs price · {cfg['as_of']} · gold {sp['gold']:,.0f} silver {sp['silver']:.2f} uranium {sp['uranium']:.0f}")
    print(f"{'#':>3} {'TICKER':7} {'PRICE':>10} {'VALUE':>17} {'VAL/PX':>7} {'MoS':>6}  {'SIGNAL':6} ZONE")
    for r in vals:
        if r["v_low"] is None:
            value = "not valued"
        else:
            value = f"{r['v_low']:,.2f}" + (f"–{r['v_high']:,.2f}" if abs(r["v_high"] - r["v_low"]) > 1e-9 else "")
        m = r.get("margin_of_safety")
        mos = "" if m is None else "<-200%" if m < -2 else f"{m*100:+.0f}%"
        print(f"{r['rank']:>3} {r['ticker']:7} {r['price']:>10,.2f} {value:>17} {r['coverage_lo']*100:>6.0f}% {mos:>6}  "
              f"{r['signal']:6} {r['zone']}")
    if grow:
        print(f"\n{'#':>3} {'TICKER':11} {'PRICE':>10} {'NO-GROWTH':>10} {'NEEDS':>9}  {'SIGNAL':6} ZONE")
        for r in grow:
            g = "" if r["implied_growth"] is None else f"{r['implied_growth']*100:+.1f}%"
            print(f"{r['rank']:>3} {r['ticker']:11} {r['price']:>10,.2f} {r['v0']:>10,.2f} {g:>9}  {r['signal']:6} {r['zone']}")
    for name, lt, etf in lookthroughs:
        if lt.get("ratio_lo"):
            print(f"\n{name}: valued holdings {lt['coverage_weight']:.1f}% of fund · look-through value "
                  f"{lt['ratio_lo']*100:.0f}–{lt['ratio_hi']*100:.0f}% of price → {lt['value_lo']:.2f}–{lt['value_hi']:.2f} "
                  f"vs {etf['price']['value']:.2f}")
    print("\nReports: " + " · ".join(str(f) for f in files))


def main(argv=None):
    a = _parser().parse_args(argv)
    if a.cmd == "validate":
        return _validate()
    if a.cmd == "backtest":
        from . import backtest  # noqa: PLC0415
        cfg = loader.with_screen_rules(loader.load_config(), a.list if a.list != "us" else None)
        years = tuple(range(a.years, 1, -1))
        if a.list == "us":   # the whole S&P 500 + Nasdaq-100 screen
            from . import factsdb  # noqa: PLC0415
            con = factsdb.connect(loader.output_folder("us") / "us_facts.sqlite")
            results = backtest.run_us(factsdb.companies(con), con, cfg, backtest.INDEX_SYMBOL["us"], years=years)
        else:
            companies = loader.load_companies(loader.companies_folder(loader.list_folder(a.list)))
            results = _backtest(a.list, companies, cfg, dict(loader.list_settings(a.list), backtest=list(years)), [])
        print("\n".join(backtest.summary_lines(results)))
        print("\nToday's members only (survivorship bias). Past performance only.")
        return 0
    cfg = loader.with_screen_rules(loader.load_config(Path(a.config) if a.config else None), a.list)
    folder = a.folder or (loader.list_folder(a.list) if a.list else None)
    companies = loader.load_companies(loader.companies_folder(folder))
    log = []
    if a.asof:
        cfg["as_of"] = dt.date.fromisoformat(a.asof)
    elif a.live:
        cfg["as_of"] = prices.today()
    etfs = [loader.load_etf(x) for x in a.etf]
    tickers = _pick_tickers(a, companies, etfs, folder, log)
    if a.live:
        log += prices.refresh_spot(cfg)
        log += prices.refresh_prices(companies, tickers)
    cfg["spot"].update(_parse_spot(a.spot))

    results = run(companies, tickers, cfg)
    if a.list and loader.list_settings(a.list).get("price_cases"):
        price_cases.attach(results, companies, cfg)
    vals, grow = ranked(results)
    out = Path(a.out) if a.out else loader.output_folder(folder)
    out.mkdir(parents=True, exist_ok=True)
    runs = out / "runs.json"
    previous = history.previous(runs, cfg["as_of"])
    if previous:
        log.append(f"previous figures in brackets are from the run of {previous['_date']}")
    tech = _technicals(tickers, companies, log) if a.technicals else {}
    pcharts = _price_charts(tickers, companies, results, log,
                            loader.list_settings(a.list).get("history_years") if a.list else None)

    screen = loader.list_settings(a.list).get("screen") if a.list else None
    screen_rows, screen_style = [], {}
    if screen == "growth":
        extras = {x["ticker"]: x["extra"] for x in loader.load_list_entries(a.list) if x.get("extra")}
        screen_rows = growth_screen.rows(results, companies, cfg, extras)
        lst = loader.list_settings(a.list)
        if lst.get("screen_panel"):   # the settings panel; on a multi-page list its links go straight to the company pages
            screen_style = {"panel": True, "list_name": list_title(a.list), "title": lst.get("screen_title")}
            if lst.get("layout") == "pages":
                screen_style["href"] = lambda t, d=a.list: f"{d}/{t}.html"
    elif screen == "us-growth":
        screen_rows, screen_style = _us_growth_rows(results, companies, cfg, a.live, log)
        if screen_rows and loader.list_settings(a.list).get("screen_panel"):
            screen_style["panel"] = True
    market_rows = markets.rows([x for x in loader.load_list_entries(a.list) if markets.is_market(x)], log.append) if a.list else []
    profit_rows = [] if a.no_profit else _profit_rows(a, tickers, companies, results, folder, out, log)
    resource_rows = (resource_screen.rows(results, {p["ticker"]: p for p in profit_rows}, _metal_growth, cfg)
                     if screen == "resource" else [])
    shown = (growth_screen.apply_filters(screen_rows, cfg[screen_style.get("key", "growth_screen")])   # as the page shows it
             if screen_rows else [])
    for label, rs in (("growth screen", shown), ("resource screen", resource_rows)):
        if rs:
            n = {t: sum(1 for r in rs if r["tier"] == t) for t in ("shortlist", "near miss")}
            log.append(f"{label}: {n['shortlist']} shortlisted, {n['near miss']} near misses of {len(rs)}")
    lookthroughs = [(e["ticker"], etf_lookthrough(e, results), e) for e in etfs]
    report.write_csv(vals, grow, out / "ranked.csv")
    report.append_signals(vals, grow, out / "signals_log.csv", cfg["as_of"])
    name = a.list or folder
    title = list_title(name)
    settings = loader.list_settings(a.list) if a.list else {}
    files = []
    bz_rows, decisions, private_page = None, [], None
    if settings.get("buy_zone") and results:   # buy-zone and review lists with the decision log (buy_zone.py)
        bz_rows = buy_zone.rows(results, pcharts, cfg)
        decisions = buy_zone.load_decisions(name)
        buy, review = buy_zone.split(bz_rows)
        log.append(f"buy zone: {len(buy)} now ({', '.join(r['ticker'] for r in buy) or 'none'}), {len(review)} to review; "
                   f"{len(decisions)} decisions in the log, {sum(d['public'] for d in decisions)} public")
        if not pcharts:
            log.append("buy zone: no price charts, so no support or RSI – run python tools/update_history.py")
        private_page = buy_zone.write_private(bz_rows, decisions, cfg, title, name,   # never published
                                              out=Path(a.out) / "private" if a.out else None)
    if results:
        extras = html_report.ReportExtras(previous=previous or {}, tech=tech, lookthroughs=lookthroughs,
                                          heatmaps=report.make_heatmaps(vals, grow, cfg, out), log_lines=log,
                                          price_charts=pcharts, market_rows=market_rows, screen_rows=screen_rows,
                                          screen_style=screen_style, resource_rows=resource_rows,
                                          hide_spot=bool(settings.get("hide_spot")),
                                          backtest=_backtest(a.list, companies, cfg, settings, log),
                                          index_name={"nifty50": "Nifty 50", "midcap150": "Nifty Midcap 150", "tech": "Nasdaq-100"}.get(a.list or "", "Index"),
                                          chart_dpi=settings.get("chart_dpi"),
                                          pages=name if settings.get("layout") == "pages" else None,
                                          buy_zone=bz_rows, decisions=decisions)
        files.append(html_report.build(results, companies, cfg, profit_rows, out / html_report.file_name(name, cfg["as_of"]), title,
                                       extras))
    if not a.out:   # the latest report, under a fixed name, for git and GitHub Pages
        for f in list(files):
            files.append(loader.publish(f, name, ".html"))
        if settings.get("layout") == "pages" and results:   # the company pages and the files they share
            files.append(loader.publish_dir(out / name, name))
            files.append(loader.publish_dir(out / "assets", "assets"))
    files.append(out / "ranked.csv")
    if private_page:
        files.append(private_page)
    history.save(runs, cfg["as_of"], results)
    _print_summary(cfg, vals, grow, lookthroughs, log, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
