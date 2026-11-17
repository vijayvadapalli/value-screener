"""Pages for the interesting US companies – the growth screen's shortlist and near misses and every green signal of the
S&P 500 / Nasdaq-100 screen. Each page: the screen's verdict and working, the SEC figures behind it, a 10-year EPS
chart, and an interactive price chart with up to 20 years of history and our value lines. Written next to the screen
page as us-screen/<ticker>.html, sharing assets/ (page.write_shared); tools/screen_us.py builds and publishes them.

    interesting(screen_rows) → the tickers that get a page
    build(us_rows, screen_rows, tickers, con, cfg, folder, years) → the pages written
"""
from __future__ import annotations

import logging
import tempfile
import time
import warnings
from pathlib import Path

from . import charts, page, price_chart
from . import style as S
from .html_report import chart_block, e, img, short_action
from .models import dcf_factor

FOLDER = "us-screen"
TIER_PILL = {"shortlist": '<span class="pill green">Shortlist</span>', "near miss": '<span class="pill blue">Near miss</span>'}


def insiders(symbols: list[str]) -> dict[str, float]:
    """{Yahoo symbol: share of the company held by insiders} – only for the companies that get a page (one call each)."""
    import yfinance as yf  # noqa: PLC0415
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    out = {}
    for sym in symbols:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                v = (yf.Ticker(sym).info or {}).get("heldPercentInsiders")
        except Exception:  # noqa: BLE001 - one missing figure must not stop the run
            v = None
        if v is not None:
            out[sym] = float(v)
        time.sleep(0.3)
    return out


def interesting(screen_rows: list[dict]) -> list[str]:
    """Shortlist, near misses and green signals."""
    return [r["ticker"] for r in screen_rows if r["tier"] or r["signal"] == "green"]


def _pct(x, nd=0):
    return "–" if x is None else S.pct(x, nd)


def value_lines_input(r: dict, cfg: dict, rate: float) -> dict:
    """What the growth model's price-chart lines need: the value with no growth, the buy level (the value at the green
    growth limit) and the sell level (at the red one), from the screen's own EPS and net cash."""
    z, eps, nc = cfg["zones"], r.get("eps"), r.get("nc") or 0.0
    if not eps or eps <= 0:
        return {"model": None, "price_ccy": "USD"}
    value = lambda g: eps * dcf_factor(g, cfg, rate) + nc  # noqa: E731
    return {"model": "growth", "price_ccy": "USD", "v0": r.get("v0"), "buy_level": value(z["growth_buy"]),
            "call_level": value(z["growth_sell"]), "growth_buy": z["growth_buy"]}


def company_page(r: dict, sr: dict, chart: dict | None, eps_png, cfg: dict) -> str:
    """One company's page: `r` the US screen row, `sr` its growth-screen row, `chart` the price-chart data."""
    s = cfg["us_growth_screen"]
    why = [{"pe": "P/E", "growth": "growth", "return": "5-yr return"}[m] for m in sr["missed"]] if sr["tier"] != "shortlist" else []
    verdict = TIER_PILL.get(sr["tier"], '<span class="pill grey">Not in the screen</span>')
    pe = "–" if sr["pe"] is None else f"{sr['pe']:.1f}"
    trailing = "–" if sr["pe_trailing"] is None else f"{sr['pe_trailing']:.1f}"
    screen_rows = [
        ("P/E (price minus net cash ÷ EPS used) · trailing", f"{pe} · {trailing}"),
        (f"EPS growth a year, 5 / 3 years (rule ≥ {s['min_eps_cagr']*100:.0f}%)", f"{_pct(sr['eps_cagr_5y'])} / {_pct(sr['eps_cagr_3y'])}"
         + ("" if sr["every_year_positive"] else " · a loss year")),
        ("Growth the price needs (5 years, 15x exit, 10%)", _pct(sr["growth_needed"], 1)),
        (f"Expected return a year over {s['years']} years (rule ≥ {s['min_return']*100:.0f}%)",
         _pct(sr["expected_return"], 1) + ("" if sr["assumed_growth"] is None else f" at {sr['assumed_growth']*100:.0f}%/yr growth")),
        ("Insider ownership", "–" if sr["promoters"] is None else f"{sr['promoters']*100:.1f}%"),
        ("Misses", ", ".join(why) or "–"), ("Guards", ", ".join(sr["guards"]) or "all pass"), ("Flags", ", ".join(sr["flags"]) or "–"),
    ]
    figures = [
        ("Price", f"${r['price']:,.2f} ({r.get('price_date', '')})"),
        ("EPS used", f"${r['eps']:,.2f} – {e(r.get('basis', ''))}" if r.get("eps") is not None else "–"),
        ("Net cash per share", "–" if r.get("nc") is None else f"${r['nc']:,.2f}"),
        ("Value with no growth", "–" if r.get("v0") is None else f"${r['v0']:,.2f}"),
        ("Return on equity · cash conversion (5 yrs)", f"{_pct(r.get('roe'))} · {_pct(r.get('cash_conversion'))}"),
        ("Free-cash-flow yield · debt ÷ EBITDA", f"{_pct(r.get('fcf_yield'), 1)} · "
         + ("–" if r.get("debt_ebitda") is None else f"{r['debt_ebitda']:.1f}×")),
        ("Shares over 3 years · profit-vs-price grade", f"{_pct(r.get('share_change_3y'))} · {r.get('grade', 'n/m')}"),
        ("Market value", "–" if r.get("market_value_bn") is None else f"${r['market_value_bn']:,.1f}bn"),
    ]
    table = lambda rows: "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)  # noqa: E731
    flags = " ".join(f"[{e(f)}]" for f in r.get("flags", []))
    edgar = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r['cik']}&type=10-K" if r.get("cik") else ""
    links = " · ".join(x for x in (f'<a href="{edgar}" target="_blank" rel="noopener">SEC filings</a>' if edgar else "",
                                   f'<a href="https://finance.yahoo.com/quote/{e(r["yahoo"])}" target="_blank" rel="noopener">Yahoo</a>') if x)
    return f"""
<section class="company" id="c-{e(r['ticker'])}">
<nav class="crumbs"><a href="../us-screen.html#screen">↑ Screen</a></nav>
<div class="head"><h2>{e(r['ticker'])} <span>{e(r['name'])}</span></h2><span class="pill big {r['signal']}">{e(short_action(r['action']))}</span></div>
<p class="meta">{e(r.get('sector', ''))} · {e(r.get('industry') or '')} · {e(', '.join(r.get('indexes') or []))} · figures from {e(r.get('source', 'SEC'))} filings
<span class="late">{flags}</span></p>
<h3>Growth at a value price – {verdict}</h3><table class="kv">{table(screen_rows)}</table>
{chart_block(r['ticker'], chart)}
<div class="grid2"><div>{img(eps_png, 'EPS by year')}</div><div><h3>Key figures</h3><table class="kv">{table(figures)}</table></div></div>
<p class="small">EPS by year: diluted, from the SEC filings, each year put on today's share basis (splits). The price chart
shows our value lines: the value with no growth, the buy level (the price at {cfg['zones']['growth_buy']*100:.0f}% growth a year) and
the sell zone (25%). Sources: {links}.</p>
</section>
<footer>Prices in US dollars.</footer>
"""


def build(us_rows: list[dict], screen_rows: list[dict], tickers: list[str], con, cfg: dict, folder: Path, years: int,
          rate: float) -> list[Path]:
    """Writes folder/us-screen/<ticker>.html for each ticker and folder/assets/; `con` is the price-history database."""
    by_t = {r["ticker"]: r for r in us_rows}
    screen = {r["ticker"]: r for r in screen_rows}
    out = folder / FOLDER
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.html"):   # companies that are no longer interesting
        old.unlink()
    page.write_shared(folder / "assets")
    written = []
    with tempfile.TemporaryDirectory() as tmp, charts.resolution(100):
        for t in tickers:
            r, sr = by_t[t], screen[t]
            chart = price_chart.payload(con, r["yahoo"], value_lines_input(r, cfg, rate), {"period": {}}, long_years=years) if con else None
            if chart:
                chart["max_range"] = True
            eps_png = charts.eps_history({"eps_annual": r.get("eps_annual") or [], "eps_years": [y[:4] for y in r.get("eps_years") or []],
                                          "price_ccy": "USD"}, Path(tmp) / f"{t}_eps.png")
            html = page.document(f"{e(t)} – {e(r['name'])} · US screen", "", company_page(r, sr, chart, eps_png, cfg),
                                 scripts=page.shared_scripts("../assets/", charts=bool(chart)), head=page.shared_style("../assets/"))
            path = out / f"{t}.html"
            path.write_text(html, encoding="utf-8")
            written.append(path)
    return written
