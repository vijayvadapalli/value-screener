"""Quick screen of a large list of miners from Yahoo's figures – which ones deserve a full company file.

For each company, from the latest twelve months (or latest year) as Yahoo reports them:
- Producer or not: revenue below 2% of the market value means a developer or explorer. Those have no earnings to
  value, so the screen shows their net cash as a share of the price instead ("not valued", like UEC).
- Value per share = net profit per share × 12 / 15 / 25 + net cash per share. Owner earnings are taken as net profit,
  i.e. sustaining capex assumed equal to depreciation, until the company file has the real figures.
- Margin of safety at 12x, price ÷ operating cash flow, free-cash-flow yield (after all capex), EV / EBITDA,
  price ÷ book, net cash as a share of the price, and the profit-vs-price grade.
- Signal: green = at least 20% below the 12x value; blue = at or below the 15x value, or between 15x and 25x; red =
  at or above 25x, or no positive earnings. Metals are NOT re-priced to today's spot here: profits are at the period's
  own prices, which is why a shortlisted company gets a full company file before any decision.

Shortlist: green producers (at least 20% below the 12x value) with positive free cash flow and a grade other than D.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

import yaml

from . import page
from . import profit_vs_price as pvp
from . import screening
from . import style as S
from .wording import money

PRODUCER_REVENUE_SHARE = 0.02   # revenue below this share of market value → developer / explorer
PHYSICAL = re.compile(r"physical|yellow cake|bullion|uranium trust", re.I)   # hold the metal: "profits" are revaluations
GREY = S.MUTED


def _rate(fx):
    return f"{fx:,.0f}" if fx >= 100 else f"{fx:.4g}"


def evaluate(raw: dict, entry: dict) -> dict:
    """One row of the screen from the Yahoo figures (growth_data.yahoo_record) and the list entry."""
    r = {"ticker": entry["ticker"], "yahoo": entry.get("yahoo", entry["ticker"]), "name": raw.get("name") or entry.get("name"),
         "metals": entry.get("metals", []), "etfs": entry.get("etfs", []), "currency": raw.get("currency"),
         "price": raw.get("price"), "price_date": raw.get("price_date"), "price_change_1y": raw.get("price_change_1y"),
         "report_ccy": raw.get("report_ccy"), "period": raw.get("ttm_label"), "flags": []}
    price, shares, fx = raw.get("price"), raw.get("shares"), raw.get("fx")
    if not price or not shares or not fx:
        return dict(r, stage="no data", signal="grey", action="No data", flags=["missing price, shares or FX rate"])
    k = fx / shares                                  # statements' money → per share in the price currency
    mv = price * shares
    r["market_value_usd"] = mv * raw["usd"] / 1e9 if raw.get("usd") else None
    revenue = raw["sales_now"] * fx if raw.get("sales_now") is not None else None   # in the price currency
    profit = raw.get("profit_now")
    cash, debt = raw.get("cash") or 0.0, raw.get("debt") or 0.0
    r["net_cash_ps"] = nc = (cash - debt) * k
    r["net_cash_share"] = nc / price
    if raw.get("report_ccy") != raw.get("currency"):
        r["flags"].append(f"{raw['report_ccy']} statements converted at {_rate(fx)}")
    if r["period"] and r["period"].startswith("FY"):
        r["flags"].append("latest year, not the last 12 months")
    if PHYSICAL.search(r["name"] or ""):
        return dict(r, stage="physical holder", signal="grey", action="Not valued")
    if not revenue or revenue < PRODUCER_REVENUE_SHARE * mv:
        return dict(r, stage="developer / explorer", signal="grey", action="Not valued")
    r["stage"] = "producer"
    if profit is None:
        return dict(r, signal="grey", action="No data", flags=r["flags"] + ["no net profit figure"])
    eps = r["eps"] = profit * k
    r.update(v12=12 * eps + nc, v15=15 * eps + nc, v25=25 * eps + nc)
    r["mos"] = 1 - price / r["v12"] if r["v12"] > 0 else None
    ocf, capex, ebitda = raw.get("ocf_ttm"), raw.get("capex_ttm"), raw.get("ebitda")
    r["p_ocf"] = price / (ocf * k) if ocf and ocf > 0 else None
    r["fcf_yield"] = (ocf + (capex or 0.0)) * k / price if ocf is not None else None   # Yahoo shows capex as a negative
    r["ev_ebitda"] = (mv + (debt - cash) * fx) / (ebitda * fx) if ebitda and ebitda > 0 else None
    r["pb"] = price / (raw["book_value_ps"] * fx) if raw.get("book_value_ps") and raw["book_value_ps"] > 0 else None
    if ocf is None:
        r["flags"].append("no operating cash flow")
    elif r["fcf_yield"] is not None and r["fcf_yield"] < 0:
        r["flags"].append("capex above operating cash flow")
    if ebitda and ebitda > 0 and debt / ebitda > 3:
        r["flags"].append("debt > 3× EBITDA")
    band = screening.multiple_band(price, eps, r["v12"], r["v25"])
    label = {"BUY": "Cheap", "SELL": "Expensive", "NO EARNINGS": "No earnings"}.get(band)
    r.update(signal=screening.colour(band), action=label or ("Fair" if price <= r["v15"] else "Watch"))
    return r


def with_grades(rows: list[dict], raw: dict) -> list[dict]:
    """Adds the profit-vs-price grade (A–D, n/m) to each row."""
    for r in rows:
        p = pvp.evaluate(raw[r["ticker"]]) if r["stage"] == "producer" else {"grade": "n/m", "pe_change": None}
        r["grade"], r["pe_change"] = p["grade"], p["pe_change"]
    return rows


def shortlist(rows: list[dict]) -> list[dict]:
    """Producers at least 20% below their 12x value, with positive free cash flow and a grade other than D."""
    return [r for r in rows if r["stage"] == "producer" and r["signal"] == "green" and (r.get("fcf_yield") or 0) > 0
            and r.get("grade") != "D"]


def sort_key(r):
    """Producers by margin of safety (best first), then developers by net cash share, then the rest."""
    order = {"producer": 0, "developer / explorer": 1, "physical holder": 2}.get(r["stage"], 3)
    if order == 0:
        return (0, -(r.get("mos") if r.get("mos") is not None else -99))
    return (order, -(r.get("net_cash_share") or -99))


# ------------------------------------------------------------------------------------------------- draft company files
def draft_file(r: dict, raw: dict, today: dt.date) -> dict:
    """A producer company file from the Yahoo figures, money already in the price currency, marked DRAFT for the
    AI updater (tools/update_results.py) to replace with the latest reported quarter."""
    fx = raw["fx"]
    m = lambda x: None if x is None else round(x * fx / 1e6, 3)  # noqa: E731 - to millions of the price currency
    converted = f" (converted from {raw['report_ccy']} at {_rate(fx)})" if raw["report_ccy"] != raw["currency"] else ""
    return {
        "ticker": r["ticker"], "yahoo": r["yahoo"], "name": r["name"], "sector": (r["metals"] or ["metals"])[0],
        "model": "producer", "currency": raw["currency"],
        "period": {"label": raw.get("ttm_label") or "latest", "end": raw.get("ttm_end") or today.isoformat(), "per_year": 1},
        "earnings": {"net_income": m(raw["profit_now"])},
        "shares_m": round(raw["shares"] / 1e6, 3),
        "balance": {"cash": m(raw.get("cash") or 0.0), "debt": m(raw.get("debt") or 0.0)},
        "price": {"value": round(r["price"], 4), "currency": raw["currency"], "date": r["price_date"], "source": f"yfinance {r['yahoo']}"},
        "sources": [f"Yahoo Finance statements via yfinance, fetched {today.isoformat()} (unverified draft){converted}"],
        "assumptions": [
            f"DRAFT from Yahoo's figures ({raw.get('ttm_label') or 'latest'}), not checked against the filings",
            "Placeholder: replace with the most recent reported quarter (adjusted net income, D&A, sustaining capex, metal sold, "
            "realised prices and AISC), then remove this DRAFT note",
            "Until then owner earnings = net profit (sustaining capex assumed equal to depreciation) and metals are not re-priced"],
        "notes": [f"In {', '.join(r['etfs'])}"],
    }


def write_drafts(rows: list[dict], raw: dict, folder: Path, today: dt.date) -> tuple[list[str], list[str]]:
    """Writes a draft for each row that has no company file yet. Returns (written, already there)."""
    folder.mkdir(parents=True, exist_ok=True)
    written, kept = [], []
    for r in rows:
        path = folder / f"{r['ticker'].lower()}.yaml"
        if path.exists():
            kept.append(r["ticker"])
            continue
        path.write_text(yaml.safe_dump(draft_file(r, raw[r["ticker"]], today), sort_keys=False, allow_unicode=True, width=140),
                        encoding="utf-8")
        written.append(r["ticker"])
    return written, kept


# ------------------------------------------------------------------------------------------------- the HTML report
def _e(x):
    return html.escape(str(x), quote=True)


def _num(x):
    return "" if x is None else f"{x:.6g}"


def _pct(x, nd=0):
    return "–" if x is None else S.pct(x, nd)


def _x(x):
    return "–" if x is None else f"{x:.1f}x"


def _row(r, in_files):
    ccy = r.get("currency") or ""
    value = "–" if r.get("v12") is None else f"{money(r['v12'], ccy)}–{money(r['v15'], ccy)}"
    mos_class = "pos" if (r.get("mos") or -1) >= 0 else "neg"
    star = (f' <span class="tag held">{_e(r["in_list"])}</span>' if r.get("in_list") else
            ' <span class="tag">in your files</span>' if r["ticker"] in in_files else "")
    flags = " ".join(f"[{_e(f)}]" for f in r["flags"])
    text = f"{r['ticker']} {r['name']} {' '.join(r['metals'])} {' '.join(r['etfs'])}".lower()
    grade = r.get("grade", "n/m")
    return f"""<tr data-signal="{r['signal']}" data-held="{'yes' if r.get('in_list') else 'no'}" data-metal="{_e(' '.join(r['metals']))}" data-stage="{_e(r['stage'])}" data-text="{_e(text)}">
<td data-v="{_e(r['ticker'])}"><a href="https://finance.yahoo.com/quote/{_e(r['yahoo'])}" target="_blank" rel="noopener"><b>{_e(r['ticker'])}</b></a>{star}<br><small>{_e(r['name'])}</small>{f'<br><span class="flags">{flags}</span>' if flags else ''}</td>
<td data-v="{ {'green': 0, 'blue': 1, 'red': 2}.get(r['signal'], 3)}"><span class="pill {r['signal']}">{_e(r['action'])}</span></td>
<td data-v="{_num(r.get('mos'))}" class="{mos_class}">{_pct(r.get('mos'))}</td>
<td data-v="{_e(' '.join(r['metals']))}">{_e(', '.join(r['metals']))}<br><small>{_e(' '.join(r['etfs']))}</small></td>
<td data-v="{_e(r['stage'])}">{_e(r['stage'])}<br><small>{_e(r.get('period') or '')}</small></td>
<td data-v="{_num(r.get('price'))}"><span class="nw">{money(r.get('price'), ccy)}</span><br><small>{_e(r.get('price_date') or '')}</small></td>
<td data-v="{_num(r.get('market_value_usd'))}">{'–' if r.get('market_value_usd') is None else f"${r['market_value_usd']:,.1f}bn"}</td>
<td data-v="{_num(r.get('v12'))}"><span class="nw">{value}</span></td>
<td data-v="{_num(r.get('p_ocf'))}">{_x(r.get('p_ocf'))}</td>
<td data-v="{_num(r.get('fcf_yield'))}">{_pct(r.get('fcf_yield'), 1)}</td>
<td data-v="{_num(r.get('ev_ebitda'))}">{_x(r.get('ev_ebitda'))}</td>
<td data-v="{_num(r.get('pb'))}">{'–' if r.get('pb') is None else f"{r['pb']:.1f}"}</td>
<td data-v="{_num(r.get('net_cash_share'))}">{_pct(r.get('net_cash_share'))}</td>
<td data-v="{'ABCDn'.index(grade[0])}" class="c grade g{grade.replace('/', '')}">{_e(grade)}</td>
<td data-v="{_num(r.get('price_change_1y'))}">{_pct(r.get('price_change_1y'))}</td></tr>"""


HEAD = """<tr><th>Ticker</th><th>Signal</th><th>Margin of safety</th><th>Metal / ETFs</th><th>Stage</th><th>Price</th><th>Mkt value</th>
<th>Value 12x–15x</th><th>Price ÷ op. cash</th><th>FCF yield</th><th>EV / EBITDA</th><th>P/B</th><th>Net cash ÷ price</th><th>Grade</th>
<th>1 yr</th></tr>"""

def build(rows: list[dict], path: Path, title: str, as_of: dt.date, etfs: list[str], in_files: set, missing: list[str]):
    metals = sorted({m for r in rows for m in r["metals"]})
    counts = {s: sum(1 for r in rows if r["signal"] == s) for s in ("green", "blue", "red", "grey")}
    short = shortlist(rows)
    short_html = ", ".join(f'<b>{_e(r["ticker"])}</b> ({_pct(r["mos"])}, {r.get("grade", "n/m")})' for r in short) or "none"
    def buttons(key, values):
        return f'<button class="on" data-k="{key}" data-v="all">All</button>' + "".join(
            f'<button data-k="{key}" data-v="{_e(v)}">{_e(label)}</button>' for v, label in values)
    body = f"""
<h1>{_e(title)} – quick screen</h1>
<p class="sub">{len(rows)} companies from {_e(', '.join(e for e in etfs if not e.endswith(' list')))}
{f"plus {sum(1 for r in rows if any(e.endswith(' list') for e in r['etfs']))} from your {next(e for r in rows for e in r['etfs'] if e.endswith(' list'))} not in them" if any(e.endswith(' list') for r in rows for e in r['etfs']) else ''} · run {as_of:%d %b %Y} · <span class="pos">{counts['green']} cheap</span>,
{counts['blue']} fair or watch, <span class="neg">{counts['red']} expensive or loss-making</span>, {counts['grey']} not valued (developers, explorers, physical holders, no data)</p>
<p class="method"><b>Signals:</b> Cheap = at least 20% below the 12x value · Fair = at or below the 15x value · Watch = between
15x and 25x · Expensive = at or above 25x, or no positive earnings · Not valued = developers, explorers, physical holders.<br>
<b>How it works.</b> Yahoo's latest twelve months (or latest year). Value = net profit per share × 12 / 15 + net cash
per share – owner earnings taken as net profit (sustaining capex assumed equal to depreciation) and metals <b>not</b> re-priced to
today's spot. Margin of safety at 12x; green = at least 20% below the 12x value. Companies with revenue under 2% of their market value
are developers or explorers and are not valued (net cash ÷ price instead). This is a filter, not a verdict: a shortlisted company gets
a full company file (metal sold, realised prices, AISC) before any decision. Click a ticker for its Yahoo page; click a column to sort.</p>
<div class="short"><b>Shortlist</b> (producers at least 20% below their 12x value, positive free cash flow, grade not D): {short_html}<br>
<small>Next: <code>python tools/screen_miners.py --promote</code> writes draft company files for these to data/miners/companies, then
<code>python tools/update_results.py --folder miners --tickers … --force</code> fills in the reported quarter, and
<code>python -m valuescreen run --list miners</code> values them properly.</small></div>
<div class="controls"><span class="lab">Signal</span>{buttons('signal', [('green', 'Cheap'), ('blue', 'Fair / watch'), ('red', 'Expensive'), ('grey', 'Not valued')])}
<span class="lab">Metal</span>{buttons('metal', [(m, m.title()) for m in metals])}
<span class="lab">Stage</span>{buttons('stage', [('producer', 'Producers'), ('developer / explorer', 'Developers'), ('physical holder', 'Physical')])}
<span class="lab">List</span>{buttons('held', [('yes', next((r['in_list'].title() + ' list' for r in rows if r.get('in_list')), 'Your list'))])}
<input id="q" type="search" placeholder="Search ticker, name, ETF"><span class="lab" id="count"></span></div>
<div class="wrap"><table class="sum" id="sum"><thead>{HEAD}</thead><tbody>{''.join(_row(r, in_files) for r in rows)}</tbody></table></div>
<p class="small">No figures from Yahoo for: {_e(', '.join(missing)) or 'none'}.</p>
<footer>Prices in each exchange's currency; values converted from the statements' currency where it differs (flagged). Market value in
US$. Educational framework, not investment advice.</footer>
"""
    html_page = page.document(f"{_e(title)} – quick screen", page.report_css() + page.asset("screen-miners.css"), body,
                              scripts=f"<script>{page.asset('screen-miners.js')}</script>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_page, encoding="utf-8")
    return path


def tickers_in_files(folders) -> set:
    """Tickers and Yahoo symbols that already have a company file in any of these folders."""
    found = set()
    for folder in folders:
        for f in Path(folder).glob("*.yaml"):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            found |= {str(d.get("ticker", "")).upper(), str(d.get("yahoo", "")).upper()}
            found |= {re.sub(r"\.(TO|V|AX|L)$", "", str(d.get("yahoo", "")).upper())}
    return found - {""}
