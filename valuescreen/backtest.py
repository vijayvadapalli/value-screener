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
Past performance only; a small number of picks makes any average fragile.
"""
from __future__ import annotations

import datetime as dt

from statistics import median

from . import growth_screen, pricedb, screener
from .v2 import kind_of

INDEX_SYMBOL = {"nifty50": "^NSEI", "midcap150": "NIFTYMIDCAP150.NS"}
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
                   total_a_year=annual(total_ret, held_years), last_fy=eps_known[-1][0], growth_years=s["years"])
        screened.append(row)
        (picks if row["tier"] == "shortlist" else near if row["tier"] == "near miss" else []).append(row)
    avg = lambda rows, k: (sum(r[k] for r in rows if r[k] is not None) / len([r for r in rows if r[k] is not None])  # noqa: E731
                           if any(r[k] is not None for r in rows) else None)
    idx = None
    if index:
        i0, i1 = close_on(con, index, start), close_on(con, index, today)
        idx = i1[0] / i0[0] - 1 if i0 and i1 and (first_date(con, index) or "9999") <= start.isoformat() else None
    picks.sort(key=lambda r: -(r["total_return"] if r["total_return"] is not None else -9))
    return {"start": start, "today": today, "years": held_years, "screened": len(screened), "picks": picks, "near": near,
            "skipped": skipped, "short_history": short_history,
            "picks_price": avg(picks, "price_return"), "picks_total": avg(picks, "total_return"),
            "all_price": avg(screened, "price_return"), "all_total": avg(screened, "total_return"), "index_price": idx,
            "all_total_median": median([r["total_return"] for r in screened if r["total_return"] is not None]) if screened else None,
            "best": picks[0] if picks else None, "worst": picks[-1] if picks else None}


def run(list_name: str, entries: list[dict], companies: dict, cfg: dict, years=(5, 4, 3, 2), today: dt.date | None = None,
        con=None) -> list[dict]:
    """One result per start date, `years` before today (or before the last day with prices)."""
    con = con or pricedb.connect()
    today = today or dt.date.fromisoformat(con.execute("SELECT MAX(date) FROM bars WHERE ticker = ?",
                                                        (INDEX_SYMBOL.get(list_name, "^NSEI"),)).fetchone()[0])
    out = []
    for y in years:
        start = today.replace(year=today.year - y)
        out.append(run_start(entries, companies, cfg, con, start, today, INDEX_SYMBOL.get(list_name)))
    return out


def summary_lines(results: list[dict]) -> list[str]:
    """Plain-text lines for the command line."""
    pct = lambda x: "  –  " if x is None else f"{x*100:+6.1f}%"  # noqa: E731
    lines = []
    for b in results:
        lines.append(f"Since {b['start']:%d %b %Y} ({b['years']:.1f} years): {len(b['picks'])} picks of {b['screened']} screened"
                     + (f" ({b['short_history']} on 4-year growth – EPS data starts FY2017)" if b["short_history"] else ""))
        lines.append(f"   picks       price {pct(b['picks_price'])}   with dividends {pct(b['picks_total'])}")
        lines.append(f"   all screened price {pct(b['all_price'])}   with dividends {pct(b['all_total'])}   median {pct(b['all_total_median'])}")
        lines.append(f"   index       price {pct(b['index_price'])}")
        for r in b["picks"]:
            lines.append(f"     {r['ticker']:12} P/E then {r['pe']:5.1f} · EPS growth {pct(r['eps_cagr_5y'])} / {pct(r['eps_cagr_3y'])} "
                         f"· return {pct(r['total_return'])} ({pct(r['total_a_year'])} a year)")
    return lines

