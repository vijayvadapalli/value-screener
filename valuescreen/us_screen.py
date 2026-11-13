"""Quick screen of the S&P 500 and Nasdaq-100 – the same reverse-DCF test as the tech and Nifty reports, on official data.

For each company (SEC filings; Yahoo for the few foreign filers):
- Earnings per share = the last twelve months' net income ÷ shares outstanding, with the playbook's sector rules:
  financials = average of that and book value × 5-year return on equity, no net cash; energy and materials (cyclicals)
  = average of that and the 5-year average; real estate is not valued (its earnings are distorted by depreciation).
- Value with no growth, and the yearly growth the price needs (5 years, 15x exit, discounted at 10%).
- Signal: green ≤ 5% a year, blue 5–25%, red ≥ 25% or no positive earnings; cheap cyclicals and cash conversion below
  70% are capped at blue.
- Quality: free-cash-flow yield, return on equity, 5-year cash conversion, share count change over 3 years (buybacks
  below zero, dilution above), debt ÷ EBITDA; and the profit-vs-price grade (EPS growth vs price growth, about 3 years).
Shortlist: green, grade A or B, cash conversion at least 70% (or a financial), and no red flags.
"""
from __future__ import annotations

import datetime as dt
import html
import math
import statistics
from pathlib import Path

from scipy.optimize import brentq

from . import profit_vs_price as pvp
from . import style as S
from .html_report import CSS as BASE_CSS
from .models import dcf_factor
from .wording import money

CYCLICAL = {"Energy", "Materials"}
FINANCIAL = {"Financials"}
NOT_VALUED = {"Real Estate"}
RATE = 0.10


def _growth_needed(eps, nc, price, cfg):
    if eps is None or eps <= 0:
        return None
    try:
        return brentq(lambda g: eps * dcf_factor(g, cfg, RATE) + nc - price, -0.6, 2.0)
    except ValueError:
        return None


def _signal(r, cfg):
    z = cfg["zones"]
    g = r.get("implied_growth")
    if r["sector"] in NOT_VALUED:
        return "grey", "Not valued"
    if g is None:
        return "red", "No earnings"
    if g >= z["growth_sell"]:
        return "red", "Expensive"
    if g <= z["growth_buy"]:
        caps = (["cyclical"] if r["sector"] in CYCLICAL else []) + (["cash conversion"] if r.get("low_cash") else [])
        if caps:
            r["caps"] = caps
            return "blue", "Cheap – capped"
        return "green", "Cheap"
    return "blue", "Watch" if g <= z["growth_watch"] else "Hold"


def finish(r: dict, eps_ttm, eps_5y, bvps, roe_5y, nc, cfg):
    """Common part: the sector rule, value, growth needed, signal."""
    price = r["price"]
    eps = eps_ttm
    if r["sector"] in FINANCIAL and bvps and roe_5y is not None and eps_ttm is not None:
        eps, nc = (eps_ttm + bvps * roe_5y) / 2, 0.0
        r["pb"], r["fair_pb"] = price / bvps, roe_5y * dcf_factor(0.0, cfg, RATE)
        r["basis"] = "financial: average of 12-month EPS and book value × 5-year ROE, no net cash"
    elif r["sector"] in CYCLICAL and eps_5y is not None and eps_ttm is not None:
        eps = (eps_ttm + eps_5y) / 2
        r["basis"] = "cyclical: average of 12-month and 5-year average EPS"
    else:
        r["basis"] = "12-month EPS"
    r["eps"] = eps
    r["nc"] = nc
    r["v0"] = eps * dcf_factor(0.0, cfg, RATE) + nc if eps is not None else None
    r["mos"] = 1 - price / r["v0"] if r.get("v0") and r["v0"] > 0 else None
    r["implied_growth"] = _growth_needed(eps, nc, price, cfg)
    r["pe"] = price / eps_ttm if eps_ttm and eps_ttm > 0 else None
    r["signal"], r["action"] = _signal(r, cfg)
    return r


def split_multiplier(shares_then, shares_now, factor):
    """The SEC data sometimes restates old per-share figures for a later split and sometimes not. If multiplying the old
    share count by the split factor brings it closer to today's count, the old figure is pre-split: return the factor
    (old per-share figures are divided by it). Otherwise it was already restated: return 1."""
    if factor == 1 or not shares_then or not shares_now:
        return factor if not shares_then else 1.0 if factor == 1 else factor
    return factor if abs(math.log(shares_now / (shares_then * factor))) < abs(math.log(shares_now / shares_then)) else 1.0


def _ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def evaluate_sec(entry: dict, s: dict, px: dict, cfg: dict) -> dict:
    """One row from the SEC summary (us_fundamentals.summarize) and prices: {"price", "date", "change_1y", "on(day)",
    "split_since(day)"}."""
    r = {**{k: entry[k] for k in ("ticker", "yahoo", "name", "sector", "industry", "indexes", "cik")}, "source": "SEC",
         "price": px["price"], "price_date": px["date"], "price_change_1y": px.get("change_1y"), "flags": []}
    shares, ttm, bal = s["shares"], s["ttm"], s["balance"]
    if not shares or not px["price"]:
        return dict(r, signal="grey", action="No data", flags=["no share count or price"])
    r["market_value_bn"] = px["price"] * shares / 1e9
    ni = ttm.get("net_income")
    eps_ttm = ni / shares if ni is not None else None
    annual = s["annual"]
    years = sorted(annual)
    eps_hist = [annual[y]["net_income"] / shares for y in years[-5:] if annual[y].get("net_income") is not None]
    roes = [_ratio(annual[y]["net_income"], annual[y]["equity"]) for y in years[-5:]]
    roes = [x for x in roes if x is not None]
    cfo = [annual[y]["ocf"] for y in years[-5:] if annual[y].get("ocf") is not None and annual[y].get("net_income")]
    prof = [annual[y]["net_income"] for y in years[-5:] if annual[y].get("ocf") is not None and annual[y].get("net_income")]
    r["cash_conversion"] = sum(cfo) / sum(prof) if prof and sum(prof) > 0 else None
    r["low_cash"] = r["sector"] not in FINANCIAL and r["cash_conversion"] is not None and r["cash_conversion"] < 0.70
    if ttm.get("ocf") is not None:
        r["fcf_yield"] = (ttm["ocf"] - (ttm.get("capex") or 0)) / (px["price"] * shares)
    r["roe"] = _ratio(ni, bal.get("equity"))
    ebitda = (ttm.get("operating_income") or 0) + (ttm.get("d_and_a") or 0) if ttm.get("operating_income") is not None else None
    r["debt_ebitda"] = _ratio(bal["debt"], ebitda) if ebitda and ebitda > 0 else None
    old = [y for y in years if s["ttm_end"] and (s["ttm_end"] - y).days >= 2.5 * 365 and annual[y].get("shares")]
    if old:
        raw = annual[old[-1]]["shares"]
        then = raw * split_multiplier(raw, shares, px["split_since"](old[-1].isoformat()))
        r["share_change_3y"] = shares / then - 1
    nc = (bal["cash_and_st"] - bal["debt"]) / shares
    bvps = bal["equity"] / shares if bal.get("equity") else None
    finish(r, eps_ttm, sum(eps_hist) / len(eps_hist) if eps_hist else None, bvps,
           sum(roes) / len(roes) if roes else None, nc, cfg)
    # profit vs price: diluted EPS about three years back (split-adjusted) against the last twelve months
    eps_y = {y: annual[y]["eps"] for y in years if annual[y].get("eps") is not None}
    base = [y for y in eps_y if s["ttm_end"] and (s["ttm_end"] - y).days >= 1.5 * 365]
    if base and eps_ttm is not None:
        target = min(base, key=lambda y: abs((s["ttm_end"] - y).days - 3 * 365.25))
        if eps_y[target] <= 0:
            later = [y for y in base if y > target and eps_y[y] > 0]
            target = min(later) if later else target
        mult = split_multiplier(annual[target].get("shares"), shares, px["split_since"](target.isoformat()))
        p = pvp.evaluate({"source": "sec", "years": (s["ttm_end"] - target).days / 365.25, "price": px["price"],
                          "eps_then": eps_y[target] / mult, "eps_now": eps_ttm,
                          "price_then": px["on"](target.isoformat())})
        r["grade"], r["pe_change"] = p["grade"], p["pe_change"]
    r.setdefault("grade", "n/m")
    if not s["ttm_complete"]:
        r["flags"].append("latest year, not the last 12 months")
    if r.get("debt_ebitda") and r["debt_ebitda"] > 3:
        r["flags"].append("debt > 3× EBITDA")
    if r.get("share_change_3y") is not None and r["share_change_3y"] > 0.10:
        r["flags"].append(f"shares +{r['share_change_3y']*100:.0f}% in 3 years")
    if r["low_cash"]:
        r["flags"].append(f"cash conversion {r['cash_conversion']*100:.0f}%")
    last_year = annual[years[-1]].get("net_income") if years else None
    avg5 = sum(eps_hist) / len(eps_hist) * shares if eps_hist else None
    if ni and last_year and avg5 and last_year > 0 and avg5 > 0 and ni > 2 * last_year and ni > 2 * avg5:
        r["flags"].append(f"profit ×{ni / last_year:.1f} on last year – one-off? check the filing")
    return r


def evaluate_yahoo(entry: dict, raw: dict, cfg: dict) -> dict:
    """Foreign filers (ASML, Arm, PDD …): the same test on Yahoo's figures."""
    r = {**{k: entry[k] for k in ("ticker", "yahoo", "name", "sector", "industry", "indexes", "cik")}, "source": "Yahoo",
         "price": raw.get("price"), "price_date": raw.get("price_date"), "price_change_1y": raw.get("price_change_1y"),
         "flags": [f"Yahoo figures – {entry['why']}" if entry.get("why") else "foreign filer – Yahoo figures"]}
    price, shares, fx = raw.get("price"), raw.get("shares"), raw.get("fx")
    if not price or not shares or not fx:
        return dict(r, signal="grey", action="No data")
    k = fx / shares
    r["market_value_bn"] = price * shares * (raw.get("usd") or 1) / 1e9
    eps = raw["profit_now"] * k if raw.get("profit_now") is not None else None
    nc = ((raw.get("cash") or 0) - (raw.get("debt") or 0)) * k
    if raw.get("ocf_ttm") is not None:
        r["fcf_yield"] = (raw["ocf_ttm"] + (raw.get("capex_ttm") or 0)) * k / price
    r["roe"] = raw.get("roe")
    finish(r, eps, None, None, None, nc, cfg)
    p = pvp.evaluate(raw)
    r["grade"], r["pe_change"] = p["grade"], p["pe_change"]
    return r


def shortlist(rows):
    """Green, grade A or B, healthy cash conversion, no red flags – one line per company (share classes such as GOOG and
    GOOGL share a CIK)."""
    seen = set()
    return [r for r in rows if r.get("signal") == "green" and r.get("grade") in ("A", "B")
            and not (r.get("cik") and (r["cik"] in seen or seen.add(r["cik"])))
            and (r["sector"] in FINANCIAL or (r.get("cash_conversion") or 0) >= 0.70 or r["source"] == "Yahoo")
            and not any(f.startswith(("debt", "shares +", "profit ×")) for f in r["flags"])]


def sort_key(r):
    g = r.get("implied_growth")
    return (g is None, g if g is not None else 0)


# ------------------------------------------------------------------------------------------------- report
def _e(x):
    return html.escape(str(x), quote=True)


def _num(x):
    return "" if x is None else f"{x:.6g}"


def _pct(x, nd=0):
    return "–" if x is None else S.pct(x, nd)


def _row(r, in_files):
    star = ' <span class="tag">in your files</span>' if r["ticker"] in in_files else ""
    flags = " ".join(f"[{_e(f)}]" for f in r["flags"])
    edgar = (f' · <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r["cik"]}&type=10-Q" target="_blank" '
             f'rel="noopener">filings</a>' if r.get("cik") else "")
    text = f"{r['ticker']} {r['name']} {r['sector']} {r.get('industry') or ''}".lower()
    g = r.get("implied_growth")
    grade = r.get("grade", "n/m")
    quality = (f"P/B {r['pb']:.1f} · fair {r['fair_pb']:.1f}" if r.get("pb") is not None and r.get("fair_pb") is not None
               else "–" if r.get("cash_conversion") is None else f"cash {r['cash_conversion']*100:.0f}%")
    return f"""<tr data-signal="{r.get('signal', 'grey')}" data-sector="{_e(r['sector'])}" data-index="{_e(' '.join(r['indexes']))}" data-text="{_e(text)}">
<td data-v="{_e(r['ticker'])}"><a href="https://finance.yahoo.com/quote/{_e(r['yahoo'])}" target="_blank" rel="noopener"><b>{_e(r['ticker'])}</b></a>{star}{edgar}<br><small>{_e(r['name'])}</small>{f'<br><span class="flags">{flags}</span>' if flags else ''}</td>
<td data-v="{ {'green': 0, 'blue': 1, 'red': 2}.get(r.get('signal'), 3)}"><span class="pill {r.get('signal', 'grey')}">{_e(r.get('action', ''))}</span></td>
<td data-v="{_num(g)}"><b>{'–' if g is None else S.pct(g, 1) + '/yr'}</b></td>
<td data-v="{_e(r['sector'])}">{_e(r['sector'])}<br><small>{_e(' · '.join(i.replace('Nasdaq-100', 'NDX') for i in r['indexes']))}</small></td>
<td data-v="{_num(r.get('price'))}">{money(r.get('price'), 'USD')}<br><small>{_e(r.get('price_date') or '')}</small></td>
<td data-v="{_num(r.get('market_value_bn'))}">{'–' if r.get('market_value_bn') is None else f"${r['market_value_bn']:,.0f}bn"}</td>
<td data-v="{_num(r.get('v0'))}">{money(r.get('v0'), 'USD')}<br><small>MoS {_pct(r.get('mos'))}</small></td>
<td data-v="{_num(r.get('pe'))}">{'–' if not r.get('pe') else f"{r['pe']:.1f}"}</td>
<td data-v="{_num(r.get('fcf_yield'))}">{_pct(r.get('fcf_yield'), 1)}</td>
<td data-v="{_num(r.get('roe'))}">{_pct(r.get('roe'), 0)}</td>
<td data-v="{_num(r.get('cash_conversion') if r.get('pb') is None else r.get('pb'))}">{quality}</td>
<td data-v="{_num(r.get('share_change_3y'))}">{_pct(r.get('share_change_3y'))}</td>
<td data-v="{_num(r.get('debt_ebitda'))}">{'–' if r.get('debt_ebitda') is None else f"{r['debt_ebitda']:.1f}x"}</td>
<td data-v="{'ABCDn'.index(grade[0])}" class="c grade g{grade.replace('/', '')}">{_e(grade)}</td>
<td data-v="{_num(r.get('price_change_1y'))}">{_pct(r.get('price_change_1y'))}</td></tr>"""


HEAD = """<tr><th>Ticker</th><th>Signal</th><th>Growth needed</th><th>Sector / index</th><th>Price</th><th>Mkt value</th>
<th>No-growth value</th><th>P/E</th><th>FCF yield</th><th>ROE</th><th>Quality</th><th>Shares 3 yrs</th><th>Debt / EBITDA</th>
<th>Grade</th><th>1 yr</th></tr>"""

JS = """
const rows = () => [...document.querySelectorAll('#sum tbody tr')];
const pick = {signal: 'all', sector: 'all', index: 'all'};
function apply() {
  const q = document.getElementById('q').value.toLowerCase(); let n = 0;
  rows().forEach(r => {
    const ok = (pick.signal === 'all' || r.dataset.signal === pick.signal) && (pick.sector === 'all' || r.dataset.sector === pick.sector)
            && (pick.index === 'all' || r.dataset.index.includes(pick.index)) && (!q || r.dataset.text.includes(q));
    r.style.display = ok ? '' : 'none'; if (ok) n++; });
  document.getElementById('count').textContent = n + ' shown';
}
document.querySelectorAll('[data-k]').forEach(b => b.onclick = () => {
  pick[b.dataset.k] = b.dataset.v;
  document.querySelectorAll(`[data-k="${b.dataset.k}"]`).forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.getElementById('q').oninput = apply;
document.querySelectorAll('#sum th').forEach((th, i) => th.onclick = () => {
  const asc = !th.classList.contains('asc');
  document.querySelectorAll('#sum th').forEach(x => x.classList.remove('asc', 'desc')); th.classList.add(asc ? 'asc' : 'desc');
  const key = r => { const v = r.children[i].dataset.v ?? ''; const n = parseFloat(v); return v === '' ? null : isNaN(n) ? v : n; };
  const body = document.querySelector('#sum tbody');
  rows().sort((a, b) => { const x = key(a), y = key(b); if (x === null) return 1; if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(r => body.appendChild(r)); });
apply();
"""
CSS = BASE_CSS + """
main{max-width:1640px} .pill.grey{background:var(--muted)} .flags{font-size:11px;color:var(--muted)}
.tag{font-size:10.5px;background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:0 6px;color:var(--ink2)}
table.sum td{white-space:nowrap} table.sum td:first-child{white-space:normal;min-width:200px}
.short{background:var(--soft);border-left:3px solid var(--green);padding:9px 13px;margin:10px 0;font-size:13.5px}
table.sectors{border-collapse:collapse;font-size:13px;margin:6px 0 14px} table.sectors td,table.sectors th{padding:4px 12px;text-align:right;
border-bottom:1px solid var(--line)} table.sectors td:first-child,table.sectors th:first-child{text-align:left}
"""


def sector_table(rows):
    """Median growth needed by sector – where the market is cheap or stretched."""
    out = []
    for sector in sorted({r["sector"] for r in rows if r["sector"]}):
        gs = [r["implied_growth"] for r in rows if r["sector"] == sector and r.get("implied_growth") is not None]
        n = sum(1 for r in rows if r["sector"] == sector)
        green = sum(1 for r in rows if r["sector"] == sector and r.get("signal") == "green")
        med = statistics.median(gs) if gs else None
        out.append((med if med is not None else 9, f"<tr><td>{_e(sector)}</td><td>{n}</td><td>{'–' if med is None else S.pct(med, 1)}</td>"
                                                   f"<td>{green}</td></tr>"))
    body = "".join(row for _, row in sorted(out))
    return (f'<table class="sectors"><tr><th>Sector</th><th>Companies</th><th>Median growth needed</th><th>Cheap (green)</th></tr>'
            f"{body}</table>")


def build(rows, path: Path, as_of: dt.date, in_files: set, notes: list[str], cfg: dict):
    counts = {s: sum(1 for r in rows if r.get("signal") == s) for s in ("green", "blue", "red", "grey")}
    short = shortlist(rows)
    short_html = ", ".join(f'<b>{_e(r["ticker"])}</b> ({S.pct(r["implied_growth"], 1)}, {r["grade"]})' for r in short) or "none"
    sectors = sorted({r["sector"] for r in rows if r["sector"]})

    def buttons(key, values):
        return f'<button class="on" data-k="{key}" data-v="all">All</button>' + "".join(
            f'<button data-k="{key}" data-v="{_e(v)}">{_e(label)}</button>' for v, label in values)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>US large caps – quick screen</title><style>{CSS}</style></head><body><main>
<h1>S&amp;P 500 and Nasdaq-100 – quick screen</h1>
<p class="sub">{len(rows)} companies · run {as_of:%d %b %Y} · <span class="pos">{counts['green']} cheap</span>, {counts['blue']} watch / hold,
<span class="neg">{counts['red']} expensive or loss-making</span>, {counts['grey']} not valued</p>
<p class="method"><b>How it works.</b> Official figures from each company's SEC filings (Yahoo for the few foreign filers): the last
twelve months' net income ÷ shares, plus net cash. Value with no growth = EPS × {dcf_factor(0.0, cfg, RATE):.1f} + net cash;
<b>growth needed</b> = the yearly growth for 5 years (15x exit, 10% return) that makes the value equal the price.
Green ≤ 5% a year, blue 5–25%, red ≥ 25% or no earnings. Financials use book value × 5-year ROE (no net cash), energy and materials
average the 12-month and 5-year EPS and are capped at blue, real estate is not valued, and cash conversion below 70% caps at blue.
Grade = profit growth vs price growth over about 3 years (A = P/E fell 25%+ … D = rose a third+). A filter, not a verdict.</p>
<div class="short"><b>Shortlist</b> (green, grade A or B, cash conversion ≥ 70%, no debt, dilution or one-off flags): {short_html}</div>
<h3>By sector</h3>{sector_table(rows)}
<div class="controls"><span class="lab">Signal</span>{buttons('signal', [('green', 'Cheap'), ('blue', 'Watch / hold'), ('red', 'Expensive'), ('grey', 'Not valued')])}
<span class="lab">Index</span>{buttons('index', [('S&P 500', 'S&P 500'), ('Nasdaq-100', 'Nasdaq-100')])}
<span class="lab">Sector</span>{buttons('sector', [(s, s) for s in sectors])}
<input id="q" type="search" placeholder="Search ticker, name, industry"><span class="lab" id="count"></span></div>
<div class="wrap"><table class="sum" id="sum"><thead>{HEAD}</thead><tbody>{''.join(_row(r, in_files) for r in rows)}</tbody></table></div>
<ul class="small">{''.join(f'<li>{_e(n)}</li>' for n in notes)}</ul>
<footer>Prices in US$ from Yahoo; fundamentals from SEC EDGAR company facts. Educational framework, not investment advice.</footer>
</main><script>{JS}</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
