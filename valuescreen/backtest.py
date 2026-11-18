"""How the growth screen's rules would have done: pick stocks on a date in the past with only what was known then, and
see what they returned since.

    python -m valuescreen backtest --list midcap150 --years 5     # starts 5, 4, 3 and 2 years ago

For each start date:
  - The stocks: today's members of the list (the index then is not in the data – survivorship bias, see the note),
    leaving out the stocks added by hand, those without a price on that day (listed later) and the price-only markets.
  - Known then: the yearly EPS of every fiscal year whose results were out (60 days after the March year-end, the
    listing deadline), the price that day, and the promoter holding of the last quarter before it where the data
    reaches that far (8 quarters). The latest yearly EPS stands in for the last twelve months (the quarterly EPS of
    years ago is not in the files); no net cash; cash conversion and bad loans are not checked (not in the data then).
  - The same rules: growth_screen.judge with the thresholds of config.yaml growth_screen. When the EPS history then is
    one year short of 5-year growth (it starts at FY2017), growth and the hold are measured over 4 years – labelled.
  - Since then: each pick's price return and total return (dividends reinvested – Yahoo's adjusted close), the equal-
    weighted average, the same for every stock screened (a fairer benchmark), and the index's price return (Yahoo has
    no total-return index: an index's dividends add about 1–1.5% a year).
The US version (run_us – the S&P 500 + Nasdaq-100 screen and the tech list, us_growth_screen rules) rebuilds each
company exactly as filed by the start date: only the SEC figures with a `filed` date on or before it (later restatements
ignored), the share count of then, and the price of then on the share basis of then (today's split-adjusted close times
the splits since). Returns are price only (the stored US closes carry no dividends – about 1.5% a year for the S&P 500),
against the S&P 500 (^GSPC) or the Nasdaq-100 (^NDX). Foreign filers are left out (their Yahoo figures are today's).

Each run also gives the growth of 1 since the earliest start with picks – picks, all screened and the index, equal-
weighted buy and hold, weekly – for the report's chart (curve()).
Past performance only; a small number of picks makes any average fragile.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
from statistics import median

from . import growth_screen, pricedb, screener
from .v2 import kind_of

INDEX_SYMBOL = {"nifty50": "^NSEI", "midcap150": "NIFTYMIDCAP150.NS", "us": "^GSPC", "tech": "^NDX"}
RESULTS_LAG_DAYS = 60      # annual results are out within 60 days of the March year-end


def fiscal_end(label: str) -> dt.date | None:
    """'Mar 2021' (or 'Mar 2021 (S)') → 2021-03-31."""
    try:
        return screener.month_end(screener.clean_label(label))
    except (ValueError, KeyError):
        return None


def known_eps(v2: dict, start: dt.date) -> list[tuple[str, float]]:
    """[(fiscal year, EPS)] of the years whose results were out on `start`, oldest first."""
    out = []
    for label, eps in zip(v2.get("years") or [], v2.get("eps_annual") or []):
        end = fiscal_end(label)
        if end and eps is not None and end + dt.timedelta(days=RESULTS_LAG_DAYS) <= start:
            out.append((screener.clean_label(label), float(eps)))
    return out


def promoters_then(v2: dict, start: dt.date) -> float | None:
    sh = v2.get("shareholding") or {}
    pairs = [(fiscal_end(q), p) for q, p in zip(sh.get("quarters") or [], sh.get("promoters") or [])]
    known = [p for end, p in pairs if end and p is not None and end + dt.timedelta(days=21) <= start]
    return known[-1] if known else None


def close_on(con, symbol: str, day: dt.date):
    """(close, adjusted close, date) of the last trading day on or before `day`, or None."""
    row = con.execute("SELECT close, adj_close, date FROM bars WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                      (symbol, day.isoformat())).fetchone()
    return row if row and row[0] else None


def first_date(con, symbol: str) -> str | None:
    row = con.execute("SELECT MIN(date) FROM bars WHERE ticker = ?", (symbol,)).fetchone()
    return row[0] if row else None


def annual(r, years):
    return (1 + r) ** (1 / years) - 1 if r is not None and years > 0 and r > -1 else None


def run_start(entries: list[dict], companies: dict, cfg: dict, con, start: dt.date, today: dt.date, index: str | None) -> dict:
    """The rules applied on `start` and the returns since. Returns the picks and the benchmarks."""
    base = cfg["growth_screen"]
    held_years = (today - start).days / 365.25
    screened, picks, near, skipped = [], [], [], {"not listed then": [], "no EPS known then": []}
    short_history = 0
    for e in entries:
        c = companies.get(e["ticker"])
        if c is None or e.get("market") or e.get("extra"):
            continue
        sym = c.get("yahoo") or e.get("yahoo") or e["ticker"]
        first = first_date(con, sym)
        then, now = close_on(con, sym, start), close_on(con, sym, today)
        if not then or not now or not first or first > (start - dt.timedelta(days=10)).isoformat():
            skipped["not listed then"].append(e["ticker"])
            continue
        eps_known = known_eps(c.get("v2") or {}, start)
        if not eps_known:
            skipped["no EPS known then"].append(e["ticker"])
            continue
        s = dict(base)
        if len(eps_known) == base["years"]:   # one year short: 4-year growth and hold (data starts FY2017)
            s["years"] = base["years"] - 1
            short_history += 1
        eps = eps_known[-1][1]
        price = then[0]
        x = {"ticker": e["ticker"], "name": c.get("name", e["ticker"]), "price": price, "price_ccy": "INR", "eps": eps, "nc": 0.0,
             "pe": price / eps if eps > 0 else None, "eps_ttm": eps, "eps_annual": [v for _, v in eps_known],
             "growth_needed": None, "cash_conversion": None, "stale": False, "bad_loans": False, "history_break": None,
             "cyclical": kind_of(c, cfg) == "cyclical", "signal": "", "action": "", "owners": promoters_then(c.get("v2") or {}, start),
             "flags": []}
        row = growth_screen.judge(x, s)
        price_ret = now[0] / then[0] - 1
        total_ret = now[1] / then[1] - 1 if then[1] and now[1] else None
        row.update(start_price=price, today_price=now[0], price_return=price_ret, total_return=total_ret,
                   total_a_year=annual(total_ret, held_years), last_fy=eps_known[-1][0], growth_years=s["years"], symbol=sym)
        screened.append(row)
        (picks if row["tier"] == "shortlist" else near if row["tier"] == "near miss" else []).append(row)
    return _result(start, today, screened, picks, near, skipped, short_history, index_return(con, index, start, today),
                   dividends=True, rules="growth_screen", index=index)


def index_return(con, index, start, today):
    """The index's price return from `start` to `today` (pricedb), or None."""
    if not index:
        return None
    i0, i1 = close_on(con, index, start), close_on(con, index, today)
    return i1[0] / i0[0] - 1 if i0 and i1 and (first_date(con, index) or "9999") <= start.isoformat() else None


def _avg(rows, k):
    vals = [r[k] for r in rows if r.get(k) is not None]
    return sum(vals) / len(vals) if vals else None


def _result(start, today, screened, picks, near, skipped, short_history, idx, dividends, rules, index):
    """One start date's result. `ret` names the return the comparison uses: with dividends where the prices have them
    (India), price only otherwise (US)."""
    ret = "total_return" if dividends else "price_return"
    picks.sort(key=lambda r: -(r[ret] if r[ret] is not None else -9))
    vals = [r[ret] for r in screened if r[ret] is not None]
    return {"start": start, "today": today, "years": (today - start).days / 365.25, "screened": len(screened), "picks": picks,
            "near": near, "skipped": skipped, "short_history": short_history, "dividends": dividends, "ret": ret,
            "rules": rules, "index": index, "all_rows": screened,
            "picks_price": _avg(picks, "price_return"), "picks_total": _avg(picks, "total_return"),
            "all_price": _avg(screened, "price_return"), "all_total": _avg(screened, "total_return"), "index_price": idx,
            "picks_ret": _avg(picks, ret), "all_ret": _avg(screened, ret), "all_ret_median": median(vals) if vals else None,
            "all_total_median": median([r["total_return"] for r in screened if r.get("total_return") is not None])
            if any(r.get("total_return") is not None for r in screened) else None,
            "best": picks[0] if picks else None, "worst": picks[-1] if picks else None}


def with_filters(b: dict, s: dict, f: dict) -> dict:
    """One start date's result with the settings panel's default switches (growth_screen.filters), as screen.js
    backtestAll does: cyclicals out of the picks and of all screened, government-owned and low promoter holding out of
    the picks (a holding not known then is not held against a stock). `all_rows` keeps everyone – the page's panel
    re-picks from them when a switch is turned off."""
    if not any(f.values()):
        return b
    keep = lambda r: not (f["cyc"] and r.get("cyclical")) and not growth_screen.filter_guards(  # noqa: E731
        r, f, s.get("min_promoter", 0.0), known_only=True)
    screened = [r for r in b["all_rows"] if not (f["cyc"] and r.get("cyclical"))]
    out = _result(b["start"], b["today"], screened, [r for r in b["picks"] if keep(r)], [r for r in b["near"] if keep(r)],
                  b["skipped"], b["short_history"], b["index_price"], b["dividends"], b["rules"], b["index"])
    out["all_rows"] = b["all_rows"]
    out["screened_rows"] = screened
    return out


def run(list_name: str, entries: list[dict], companies: dict, cfg: dict, years=(5, 4, 3, 2), today: dt.date | None = None,
        con=None) -> list[dict]:
    """One result per start date, `years` before today (or before the last day with prices)."""
    con = con or pricedb.connect()
    today = today or dt.date.fromisoformat(con.execute("SELECT MAX(date) FROM bars WHERE ticker = ?",
                                                        (INDEX_SYMBOL.get(list_name, "^NSEI"),)).fetchone()[0])
    out = []
    f = growth_screen.filters(cfg["growth_screen"])
    for y in years:
        start = today.replace(year=today.year - y)
        out.append(with_filters(run_start(entries, companies, cfg, con, start, today, INDEX_SYMBOL.get(list_name)),
                                cfg["growth_screen"], f))
    _add_curve(out, lambda sym, since: con.execute("SELECT date, adj_close FROM bars WHERE ticker = ? AND date >= ? AND adj_close "
                                                   "IS NOT NULL ORDER BY date", (sym, since)).fetchall(), con)
    return out


# ---- the chart: growth of 1 since the earliest start with picks

def value_on(series, day: str):
    """The last value on or before `day` in [(date, value)] sorted by date, or None."""
    i = bisect.bisect_right(series, (day, math.inf)) - 1
    return series[i][1] if i >= 0 else None


def curve(start: dt.date, today: dt.date, picks: list[str], screened: list[str], index: str | None, series, con,
          step: int = 5) -> dict | None:
    """Growth of 1 from `start`: the picks and all screened equal-weighted, buy and hold (the mean of each stock's value
    ÷ its value at the start), and the index – on every `step`-th trading day of the index, plus the last.
    `series(symbol, since)` gives a stock's [(date, value)]; the index comes from pricedb (`con`)."""
    if not index or not screened:
        return None
    days = [d for (d,) in con.execute("SELECT date FROM bars WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
                                      (index, start.isoformat(), today.isoformat()))]
    if len(days) < 2:
        return None
    days = days[::step] + ([days[-1]] if (len(days) - 1) % step else [])
    idx = con.execute("SELECT date, close FROM bars WHERE ticker = ? AND date <= ? ORDER BY date", (index, today.isoformat())).fetchall()
    since = (start - dt.timedelta(days=10)).isoformat()
    cache = {}

    def rel(sym):
        if sym not in cache:
            ser = series(sym, since)
            base = value_on(ser, start.isoformat())
            cache[sym] = (ser, base) if base else None
        return cache[sym]

    def mean_of(symbols, day):
        vals = [value_on(ser, day) / base for ser, base in filter(None, map(rel, symbols)) if value_on(ser, day)]
        return sum(vals) / len(vals) if vals else None
    i0 = value_on(idx, start.isoformat())
    return {"start": start, "days": days, "picks": [mean_of(picks, d) for d in days], "all": [mean_of(screened, d) for d in days],
            "index": [value_on(idx, d) / i0 if i0 else None for d in days], "n_picks": len(picks), "n_all": len(screened)}


def _add_curve(results, series, con):
    """The chart's curve on the earliest start with picks, else the earliest start (results[i]["curve"])."""
    by_start = sorted(results, key=lambda b: b["start"])
    first = next((b for b in by_start if b["picks"]), by_start[0] if by_start else None)
    if first:
        first["curve"] = curve(first["start"], first["today"], [r["symbol"] for r in first["picks"]],
                               [r["symbol"] for r in first.get("screened_rows", first["all_rows"])], first["index"], series, con)


# ---- the US screen and the tech list: rebuilt exactly as filed by the start date

def prices_as_of(rows: list[tuple[str, float]], splits: list[tuple[str, float]], start: dt.date) -> dict | None:
    """What us_screen.evaluate_sec needs to know of the price on `start`, on the share basis of then. `rows` are the
    stored closes (split-adjusted to today), `splits` [(date, ratio)]. None if the stock has no close within 10 days
    before `start` (listed later)."""
    day = start.isoformat()
    i = bisect.bisect_right(rows, (day, math.inf)) - 1
    if i < 0 or rows[0][0] > (start - dt.timedelta(days=10)).isoformat():
        return None
    after = math.prod(r for d, r in splits if d > day)   # today's shares per share of then
    between = lambda since: [r for d, r in splits if since < d <= day]  # noqa: E731 - oldest first

    def on(when):
        v = value_on(rows, min(when, day))
        return v * after if v else None
    year_ago = value_on(rows, (start - dt.timedelta(days=365)).isoformat())
    return {"price": rows[i][1] * after, "date": rows[i][0], "change_1y": rows[i][1] / year_ago - 1 if year_ago else None,
            "on": on, "split_since": lambda since: math.prod(between(since)), "splits_since": between}


def run_us_start(entries: list[dict], facts_con, cfg: dict, start: dt.date, today: dt.date, index: str | None, pcon,
                 closes: dict, splits: dict) -> dict:
    """The US growth screen on `start` with the SEC figures filed by then, and the price return since.
    `closes`/`splits`: {yahoo symbol: [(date, value)]} from the facts database."""
    from . import factsdb, us_screen  # noqa: PLC0415
    from .us_fundamentals import problem, summarize  # noqa: PLC0415
    screened, picks, near = [], [], []
    skipped = {"not listed then": [], "no SEC figures then": [], "not valued then": []}
    for e in entries:
        if e.get("foreign"):
            continue
        rows = closes.get(e["yahoo"]) or []
        px = prices_as_of(rows, splits.get(e["yahoo"]) or [], start)
        now = value_on(rows, today.isoformat())
        if not px or not now:
            skipped["not listed then"].append(e["ticker"])
            continue
        facts = factsdb.load_facts(facts_con, e["cik"], filed_by=start.isoformat())
        try:
            summary = summarize(facts, start) if "us-gaap" in facts["facts"] else None
            why = problem(summary, start) if summary else "no SEC figures"
        except Exception:  # noqa: BLE001 - one odd filer must not stop the run
            why = "SEC figures unreadable"
        if why:
            skipped["no SEC figures then"].append(e["ticker"])
            continue
        r = us_screen.evaluate_sec(e, summary, px, cfg)
        if r.get("signal") not in ("green", "blue", "red") or r.get("eps") is None:
            skipped["not valued then"].append(e["ticker"])
            continue
        row = growth_screen.evaluate_us(r, cfg)
        then = value_on(rows, start.isoformat())
        price_ret = now / then - 1
        row.update(start_price=px["price"], today_price=now, price_return=price_ret, total_return=None,
                   total_a_year=None, price_a_year=annual(price_ret, (today - start).days / 365.25),
                   last_fy=f"{summary['ttm_end']:%b %Y}" if summary.get("ttm_end") else "–",
                   growth_years=cfg["us_growth_screen"]["years"], symbol=e["yahoo"])
        screened.append(row)
        (picks if row["tier"] == "shortlist" else near if row["tier"] == "near miss" else []).append(row)
    return _result(start, today, screened, picks, near, skipped, 0, index_return(pcon, index, start, today),
                   dividends=False, rules="us_growth_screen", index=index)


def run_us(entries: list[dict], facts_con, cfg: dict, index: str, years=(5, 4, 3, 2), today: dt.date | None = None,
           pcon=None) -> list[dict]:
    """One result per start date for US companies (factsdb.companies entries), `years` before the index's last day."""
    pcon = pcon or pricedb.connect()
    today = today or dt.date.fromisoformat(pcon.execute("SELECT MAX(date) FROM bars WHERE ticker = ?", (index,)).fetchone()[0])
    wanted = {e["yahoo"] for e in entries}
    closes, splits = {}, {}
    for t, d, c in facts_con.execute("SELECT ticker, date, close FROM prices ORDER BY ticker, date"):
        if t in wanted:
            closes.setdefault(t, []).append((d, c))
    for t, d, r in facts_con.execute("SELECT ticker, date, ratio FROM splits ORDER BY ticker, date"):
        if t in wanted:
            splits.setdefault(t, []).append((d, r))
    out = [run_us_start(entries, facts_con, cfg, today.replace(year=today.year - y), today, index, pcon, closes, splits)
           for y in years]
    _add_curve(out, lambda sym, since: [x for x in closes.get(sym, []) if x[0] >= since], pcon)
    return out


def summary_lines(results: list[dict]) -> list[str]:
    """Plain-text lines for the command line."""
    pct = lambda x: "  –  " if x is None else f"{x*100:+6.1f}%"  # noqa: E731
    lines = []
    for b in results:
        lines.append(f"Since {b['start']:%d %b %Y} ({b['years']:.1f} years): {len(b['picks'])} picks of {b['screened']} screened"
                     + (f" ({b['short_history']} on 4-year growth – EPS data starts FY2017)" if b["short_history"] else ""))
        lines.append(f"   picks       price {pct(b['picks_price'])}   with dividends {pct(b['picks_total'])}")
        lines.append(f"   all screened price {pct(b['all_price'])}   with dividends {pct(b['all_total'])}   median {pct(b['all_ret_median'])}")
        lines.append(f"   index       price {pct(b['index_price'])}")
        for r in b["picks"]:
            lines.append(f"     {r['ticker']:12} P/E then {r['pe']:5.1f} · EPS growth {pct(r['eps_cagr_5y'])} / {pct(r['eps_cagr_3y'])} "
                         f"· return {pct(r[b['ret']])} ({pct(annual(r[b['ret']], b['years']))} a year)")
    return lines

