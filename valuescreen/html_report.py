"""The combined report as one HTML file: value vs price and profit growth vs price growth, with links to navigate.

Top: method, legend and one summary table – click a column to sort, filter by signal or grade, search by name; every
ticker links to its company section. Each company section has the headline, the "how to read" cards, the valuation
band, charts, key figures, the calculation, the profit-vs-price comparison, notes and linked sources, plus links to the
summary and to the previous and next company. Then ETF look-throughs, cross-company heatmaps and the run log.

A single self-contained file (charts embedded), so it opens offline and can be shared as it is. The words come from
wording.py and profit_vs_price.py, the charts from charts.py.
"""
from __future__ import annotations

import base64
import html
import re
import tempfile
from pathlib import Path

from . import charts
from . import profit_vs_price as pvp
from . import style as S
from .pdf import list_title
from .wording import (MODEL_LABEL, calc_steps, day, headline, key_figures, kpi_cards, money, price_date,
                      worked_example)

HTML_DPI = 150
SIGNAL_ORDER = {"green": 0, "blue": 1, "red": 2}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "n/m": 4}
URL_RE = re.compile(r"\b((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|gov|in|org|net|io|ca|uk|au)(?:/[^\s,;)]*)?)", re.I)


def e(x):
    return html.escape(str(x), quote=True)


def markup(text: str) -> str:
    """reportlab paragraph mark-up (used by wording.py) → HTML."""
    def font(m):
        attrs = dict(re.findall(r"(\w+)='([^']*)'", m.group(0)))
        style = []
        if "color" in attrs:
            style.append(f"color:{attrs['color']}")
        if "size" in attrs:
            style.append(f"font-size:{float(attrs['size']) / 7.3:.2f}em")
        if "Bold" in attrs.get("name", ""):
            style.append("font-weight:600")
        return f"<span style=\"{';'.join(style)}\">"
    text = re.sub(r"<font[^>]*>", font, text)
    return text.replace("</font>", "</span>")


def link_urls(text: str) -> str:
    """Escapes text and turns web addresses into links."""
    out, last = [], 0
    for m in URL_RE.finditer(text):
        url = m.group(1).rstrip(".")
        out += [e(text[last:m.start()]), f'<a href="{e(url if url.startswith("http") else "https://" + url)}" target="_blank" '
                                        f'rel="noopener">{e(url)}</a>']
        last = m.start() + len(url)
    return "".join(out) + e(text[last:])


def img(path, alt):
    if not path:
        return ""
    return f'<img src="data:image/png;base64,{base64.b64encode(Path(path).read_bytes()).decode()}" alt="{e(alt)}">'


def pct(x, nd=0):
    return "–" if x is None else S.pct(x, nd)


# ------------------------------------------------------------------------------------------------- summary table
def _value_cell(r):
    ccy, m = r["price_ccy"], r["model"]
    if m in ("producer", "cashflow") and (r.get("oe") or 0) > 0:
        return f"{money(r['v_low'], ccy)}–{money(r['v_high'], ccy)}", f"{r['mult_lo']}–{r['mult_hi']}x"
    if m in ("developer", "physical"):
        return money(r["nav"], ccy), "NAV"
    if m == "leases":
        return f"{money(r['v_low'], ccy, 0)}–{money(r['v_high'], ccy, 0)}", "cautious–fair"
    if m == "growth":
        return money(r["v0"], ccy), "no growth"
    return "–", "not valued"


def _assumes_cell(r):
    """What the price already assumes: the metal price at 15x, the growth needed, or the metal at which NAV = price."""
    if r["model"] == "growth":
        g = r.get("implied_growth")
        return (pct(g, 1) + "/yr" if g is not None else "–"), g
    if r.get("implied_metal_hi"):
        metal = r.get("primary_metal", "")
        return f"{metal} {r['implied_metal_hi']:,.0f}", None
    if r["model"] == "leases" and r.get("irr") is not None:
        return f"{r['irr']*100:.1f}% return", None
    return "–", None


def _buy_cell(r):
    ccy = r["price_ccy"]
    if r.get("buy_level") is None:
        return "–"
    if r.get("add_level") is not None:
        return f"<span class=nw>start ≤ {money(r['buy_level'], ccy)}</span><br><small>add ≤ {money(r['add_level'], ccy)}</small>"
    return f"<span class=nw>≤ {money(r['buy_level'], ccy)}</span>"


def _num(x):
    return "" if x is None else f"{x:.6g}"


def summary_row(r, p, previous):
    t = r["ticker"]
    value, basis = _value_cell(r)
    assumes, assumes_v = _assumes_cell(r)
    prev = previous.get(t, {})
    prev_mos = f"<br><small>({pct(prev['margin_of_safety'])})</small>" if prev.get("margin_of_safety") is not None else ""
    grade = p["grade"] if p else "n/m"
    flags = " ".join(f"[{e(f)}]" for f in r.get("flags", []))
    text = f"{t} {r['name']} {r.get('sector', '')}".lower()
    late = "late" if (r.get("price_undated") or (r.get("price_age_days") or 0) > 7) else ""
    return f"""<tr data-signal="{r['signal']}" data-grade="{e(grade)}" data-text="{e(text)}">
<td data-v="{e(r['display_ticker'])}"><a href="#c-{e(t)}"><b>{e(r['display_ticker'])}</b></a><br><small>{e(r['name'])}</small></td>
<td data-v="{_num(r['price'])}">{money(r['price'], r['price_ccy'])}<br><small class="{late}">{price_date(r)}</small></td>
<td data-v="{_num(r.get('v_low'))}"><span class="nw">{value}</span><br><small>{basis}</small></td>
<td data-v="{_num(r.get('margin_of_safety'))}" class="{'pos' if (r.get('margin_of_safety') or -1) >= 0 else 'neg'}">{pct(r.get('margin_of_safety'))}{prev_mos}</td>
<td data-v="{_num(r.get('buy_level'))}">{_buy_cell(r)}</td>
<td data-v="{SIGNAL_ORDER[r['signal']]}"><span class="pill {r['signal']}">{e(r['action'])}</span></td>
<td data-v="{_num(assumes_v)}">{assumes}</td>
<td data-v="{e(r.get('tier') or '')}" class="c">{e(r.get('tier') or '–')}</td>
<td data-v="{GRADE_ORDER[grade]}" class="c grade g{grade.replace('/', '')}">{e(grade)}</td>
<td data-v="{_num(p and p['pe_change'])}">{pct(p and p['pe_change'])}</td>
<td data-v="{_num(p and p['profit_growth'])}">{pct(p and p['profit_growth'])}</td>
<td data-v="{_num(p and p['price_growth'])}">{pct(p and p['price_growth'])}</td>
<td class="flags">{flags}</td></tr>"""


SUMMARY_HEAD = """<tr><th>Ticker</th><th>Price</th><th>Value</th><th>Margin of safety</th><th>Buy level</th><th>Signal</th>
<th>Price assumes</th><th>Tier</th><th>Grade</th><th>P/E change</th><th>Profit /yr</th><th>Price /yr</th><th>Flags</th></tr>"""


# ------------------------------------------------------------------------------------------------- company sections
def _cards(r):
    out = []
    for label, value, caption, colour in kpi_cards(r):
        out.append(f'<div class="card" style="border-top-color:{colour}"><div class="lbl">{e(label)}</div>'
                   f'<div class="val">{markup(value)}</div><div class="cap">{markup(caption)}</div></div>')
    return '<div class="cards">' + "".join(out) + "</div>"


def _key_figures(r):
    rows = "".join(f"<tr class=\"{'b' if bold else ''}\"><td>{markup(k)}</td><td>{markup(v)}</td></tr>" for k, v, bold in key_figures(r))
    return f'<table class="kv">{rows}</table>'


def _pvp_block(p):
    if not p:
        return '<p class="muted">No profit-vs-price figures for this company (none fetched, or the list was run with --no-profit).</p>'
    if p["grade"] == "n/m" and p.get("profit_growth") is None and p.get("sales_growth") is None:
        return f'<div class="pvp"><div class="bigrade gnm">n/m</div><div><p>{pvp.comment(p)}</p></div></div>'
    ccy = p["report_ccy"]
    unit = "cr" if p.get("source") == "screener" else "m"
    amount = lambda x: pvp._amount(x, ccy, unit)  # noqa: E731
    rows = [("Sales growth a year", pct(p["sales_growth"])),
            ("Profit growth a year" + (" (EPS)" if p.get("source") == "yahoo" else ""), pct(p["profit_growth"])),
            ("Net profit then → now", f"{amount(p.get('profit_then'))} → {amount(p.get('profit_now'))}"),
            ("Share price growth a year", pct(p["price_growth"])),
            ("Share price, last year", pct(p.get("price_change_1y"))),
            ("P/E change over the period", pct(p["pe_change"])),
            ("P/E now", "–" if not p.get("pe_now") else f"{p['pe_now']:.1f}"),
            ("Return on equity", "–" if p.get("roe") is None else f"{p['roe']*100:.0f}%"),
            ("Period", f"{e(p.get('base_label') or '?')} → {e(p.get('latest_label') or '?')} ({p['years']:.1f} years)")]
    table = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    source = p.get("page") or ""
    src = f' · <a href="{e(source)}" target="_blank" rel="noopener">Screener page</a>' if source else ""
    return (f'<div class="pvp"><div class="bigrade g{p["grade"].replace("/", "")}">{e(p["grade"])}</div><div>'
            f'<p>{pvp.comment(p)}</p><table class="kv">{table}</table>'
            f'<p class="muted">Source: {"Screener.in" if p.get("source") == "screener" else "Yahoo Finance statements"}{src}</p></div></div>')


def company_section(r, c, cfg, p, neighbours, chart_dir, tech):
    t = r["ticker"]
    prev_t, next_t = neighbours
    nav = ['<a href="#summary">↑ Summary</a>']
    if prev_t:
        nav.append(f'<a href="#c-{e(prev_t)}">← {e(prev_t)}</a>')
    if next_t:
        nav.append(f'<a href="#c-{e(next_t)}">{e(next_t)} →</a>')
    meta = [MODEL_LABEL.get(r["model"], r["model"])] + ([f"tier {r['tier']}"] if r.get("tier") else [])
    reported = f", reported {day(r['period_reported'])}" if r.get("period_reported") else ""
    meta += [f"results {e(r['period'])} (to {day(r['period_end'])}{reported})", f"price {price_date(r)} · {e(r.get('price_source', ''))}"]
    flags = " ".join(f"[{e(f)}]" for f in r.get("flags", []))
    band = charts.band(r, chart_dir / f"{t}_band.png")
    curve = charts.curve(r, c, cfg, chart_dir / f"{t}_curve.png")
    heat = charts.heatmap(r, c, cfg, chart_dir / f"{t}_heat.png")
    extra = charts.eps_history(r, chart_dir / f"{t}_eps.png") if r.get("v2") else (
        charts.bridge(r, chart_dir / f"{t}_bridge.png") if r["model"] == "leases" else None)
    steps = "".join(f"<li>{markup(x)}</li>" for x in calc_steps(r, c))
    example = worked_example(r, c)
    example_html = f'<div class="callout" style="border-left-color:{S.SIGNAL["blue"]}">{markup(example)}</div>' if example else ""
    tech_html = f'<p class="muted"><b>Before buying</b> (200-day average, RSI, MACD): {e(tech["note"])}</p>' if tech and tech.get("note") else ""
    notes = ([f"STALE: {r['stale_reason']}"] if r.get("stale_reason") else []) + list(c.get("assumptions", [])) + list(c.get("notes", []))
    if r.get("signal_caps"):
        notes.append("Signal capped at blue: " + ", ".join(r["signal_caps"]) + ".")
    notes_html = "".join(f"<li>{e(x)}</li>" for x in notes) or "<li>none</li>"
    sources_html = "".join(f"<li>{link_urls(str(x))}</li>" for x in c.get("sources", []))
    return f"""<section class="company" id="c-{e(t)}">
<nav class="crumbs">{' · '.join(nav)}</nav>
<div class="head"><h2>{e(r['display_ticker'])} <span>{e(r['name'])}</span></h2><span class="pill big {r['signal']}">{e(r['action'])}</span></div>
<p class="meta">{' · '.join(meta)} <span class="late">{flags}</span></p>
{_cards(r)}
<div class="callout" style="border-left-color:{S.SIGNAL[r['signal']]}">{markup(headline(r, cfg))}</div>
{img(band, 'valuation band')}
<div class="grid2"><div>{img(curve, 'curve')}</div><div><h3>Key figures</h3>{_key_figures(r)}</div></div>
<div class="grid2"><div>{img(heat, 'heatmap')}{img(extra, 'history')}</div>
<div><h3>How the value is calculated</h3><ol>{steps}</ol>{example_html}{tech_html}</div></div>
<h3>Profit growth vs price growth</h3>{_pvp_block(p)}
<div class="grid2"><div><h3>Assumptions and data notes</h3><ul class="small">{notes_html}</ul></div>
<div><h3>Sources</h3><ul class="small">{sources_html}</ul></div></div>
</section>"""


# ------------------------------------------------------------------------------------------------- page
CSS = f"""
:root{{--bg:#fff;--ink:{S.INK};--ink2:{S.INK2};--muted:{S.MUTED};--line:{S.LINE};--soft:{S.SOFT};--card:#fff;
--green:{S.SIGNAL['green']};--blue:{S.SIGNAL['blue']};--red:{S.SIGNAL['red']};--price:{S.PRICE};--late:#B7791F;
--gA:{pvp.GRADE_COLOUR['A']};--gB:{pvp.GRADE_COLOUR['B']};--gC:{pvp.GRADE_COLOUR['C']};--gD:{pvp.GRADE_COLOUR['D']};
--tg:{S.TINT['green'][2]};--tb:{S.TINT['blue'][2]};--tr:{S.TINT['red'][2]}}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#121417;--ink:#ECEEF2;--ink2:#B4BAC5;--muted:#868D99;
--line:#2A2E35;--soft:#1B1E23;--card:#171A1E;--tg:#16302A;--tb:#192640;--tr:#3A1E1D}}}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,-apple-system,"Segoe UI",system-ui,sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:28px;margin:4px 0 2px;letter-spacing:-.01em}} h2{{font-size:22px;margin:0}} h2 span{{color:var(--ink2);font-weight:500}}
h3{{font-size:14px;margin:18px 0 6px}} small,.muted{{color:var(--muted)}} .small{{font-size:12.5px;color:var(--ink2)}}
a{{color:var(--blue);text-decoration:none}} a:hover{{text-decoration:underline}}
.sub{{color:var(--ink2);margin:0 0 10px}} .method{{color:var(--ink2);font-size:13px;max-width:1000px}}
.toc{{display:flex;flex-wrap:wrap;gap:6px 12px;margin:10px 0;font-size:13px}}
.controls{{position:sticky;top:0;z-index:5;background:var(--bg);padding:8px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;
border-bottom:1px solid var(--line)}}
.controls button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:14px;padding:3px 11px;cursor:pointer;font:inherit;font-size:12.5px}}
.controls button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.controls input{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:14px;padding:4px 11px;font:inherit;font-size:13px;min-width:180px}}
.controls .lab{{color:var(--muted);font-size:12px;margin-left:6px}}
@media (max-width:1000px){{.wrap{{overflow-x:auto}} table.sum th{{position:static}}}}
table.sum{{border-collapse:separate;border-spacing:0 2px;width:100%;font-size:13px;margin-top:6px}}
table.sum th{{position:sticky;top:46px;background:var(--soft);color:var(--ink2);font-weight:600;font-size:12px;text-align:left;padding:7px 8px;
cursor:pointer;white-space:nowrap;border-bottom:1px solid var(--ink2)}}
table.sum th:after{{content:" ↕";color:var(--muted);font-weight:400}} table.sum th.asc:after{{content:" ↑"}} table.sum th.desc:after{{content:" ↓"}}
table.sum td{{padding:6px 7px;vertical-align:middle}} table.sum td small{{white-space:nowrap}} .nw{{white-space:nowrap}}
tr[data-signal=green] td{{background:var(--tg)}} tr[data-signal=blue] td{{background:var(--tb)}} tr[data-signal=red] td{{background:var(--tr)}}
tr[data-signal=green] td:first-child{{box-shadow:inset 3px 0 var(--green)}} tr[data-signal=blue] td:first-child{{box-shadow:inset 3px 0 var(--blue)}}
tr[data-signal=red] td:first-child{{box-shadow:inset 3px 0 var(--red)}}
td.c{{text-align:center}} .pos{{color:var(--green);font-weight:600}} .neg{{color:var(--red);font-weight:600}} .late{{color:var(--late)}}
td.flags{{color:var(--muted);font-size:11.5px;max-width:240px}}
.pill{{display:inline-block;padding:2px 10px;border-radius:10px;color:#fff;font-weight:600;font-size:12px;white-space:nowrap}}
.pill.big{{font-size:14px;padding:4px 16px;border-radius:14px}}
.pill.green{{background:var(--green)}} .pill.blue{{background:var(--blue)}} .pill.red{{background:var(--red)}}
.grade{{font-weight:700;font-size:16px}} .gA{{color:var(--gA)}} .gB{{color:var(--gB)}} .gC{{color:var(--gC)}} .gD{{color:var(--gD)}} .gnm{{color:var(--muted)}}
.company{{border-top:1px solid var(--line);margin-top:36px;padding-top:14px;scroll-margin-top:10px}}
.crumbs{{font-size:12.5px;margin-bottom:8px}} .head{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
.meta{{color:var(--ink2);font-size:12.5px;margin:4px 0 10px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}}
.card{{background:var(--soft);border-top:3px solid;padding:9px 11px 11px}} .card .lbl{{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}}
.card .val{{font-size:21px;font-weight:600;margin:2px 0}} .card .cap{{font-size:11.5px;color:var(--ink2)}}
.callout{{background:var(--soft);border-left:3px solid;padding:9px 13px;margin:10px 0}}
.grid2{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start}}
@media (max-width:820px){{.grid2{{grid-template-columns:1fr}}}}
img{{max-width:100%;height:auto;display:block;margin:6px 0;border-radius:4px;background:#fff}}
table.kv{{border-collapse:collapse;width:100%;font-size:13px}} table.kv td{{padding:4px 0;border-bottom:1px solid var(--line)}}
table.kv td:last-child{{text-align:right}} table.kv tr.b td{{font-weight:600}}
ol{{padding-left:20px;margin:6px 0}} ol li{{margin:3px 0}}
.pvp{{display:flex;gap:18px;align-items:flex-start}} .pvp>div:last-child{{flex:1}} .pvp p{{margin:0 0 6px}}
.bigrade{{font-size:44px;font-weight:700;line-height:1;min-width:56px;text-align:center}}
footer{{color:var(--muted);font-size:12px;margin-top:40px}}
"""

JS = """
const rows = () => [...document.querySelectorAll('#sum tbody tr')];
let sig = 'all', grd = 'all';
function apply() {
  const q = document.getElementById('q').value.toLowerCase();
  let n = 0;
  rows().forEach(r => {
    const ok = (sig === 'all' || r.dataset.signal === sig) && (grd === 'all' || r.dataset.grade === grd)
               && (!q || r.dataset.text.includes(q));
    r.style.display = ok ? '' : 'none'; if (ok) n++;
  });
  document.getElementById('count').textContent = n + ' shown';
}
document.querySelectorAll('[data-sig]').forEach(b => b.onclick = () => {
  sig = b.dataset.sig; document.querySelectorAll('[data-sig]').forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.querySelectorAll('[data-grd]').forEach(b => b.onclick = () => {
  grd = b.dataset.grd; document.querySelectorAll('[data-grd]').forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.getElementById('q').oninput = apply;
document.querySelectorAll('#sum th').forEach((th, i) => th.onclick = () => {
  const asc = !th.classList.contains('asc');
  document.querySelectorAll('#sum th').forEach(x => x.classList.remove('asc', 'desc'));
  th.classList.add(asc ? 'asc' : 'desc');
  const key = r => { const v = r.children[i].dataset.v ?? ''; const n = parseFloat(v); return v === '' ? null : isNaN(n) ? v : n; };
  const body = document.querySelector('#sum tbody');
  rows().sort((a, b) => { const x = key(a), y = key(b);
    if (x === null) return 1; if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(r => body.appendChild(r));
});
apply();
"""


def build(results: dict, companies: dict, cfg: dict, profit_rows: list[dict], path: Path, title: str,
          previous: dict | None = None, tech: dict | None = None, lookthroughs=(), heatmaps=(None, None), log_lines=()):
    previous, tech = previous or {}, tech or {}
    profit = {p["ticker"]: p for p in profit_rows}
    ordered = sorted(results.values(), key=lambda r: r["display_ticker"])
    tickers = [r["ticker"] for r in ordered]
    sp = cfg["spot"]
    counts = {s: sum(1 for r in ordered if r["signal"] == s) for s in ("green", "blue", "red")}
    grades = {g: sum(1 for t in tickers if profit.get(t, {}).get("grade", "n/m") == g) for g in GRADE_ORDER}
    with tempfile.TemporaryDirectory() as tmp, charts.resolution(HTML_DPI):
        sections = [company_section(r, companies[r["ticker"]], cfg, profit.get(r["ticker"]),
                                    (tickers[i - 1] if i else None, tickers[i + 1] if i + 1 < len(tickers) else None),
                                    Path(tmp), tech.get(r["ticker"])) for i, r in enumerate(ordered)]
    toc = " ".join(f'<a href="#c-{e(t)}">{e(results[t]["display_ticker"])}</a>' for t in tickers)
    etf_html = ""
    for name, lt, etf in lookthroughs:
        body = "".join(f"<tr><td>{e(h['ticker'])}</td><td>{e(h.get('name', ''))}</td><td>{h['weight']:.2f}%</td><td>"
                       + (f"{h['coverage_lo']*100:.0f}–{h['coverage_hi']*100:.0f}%" if h["valued"] else "not valued") + "</td></tr>"
                       for h in lt["rows"])
        head = (f"Valued holdings cover <b>{lt['coverage_weight']:.1f}%</b> of the fund; look-through value ≈ "
                f"<b>{lt['ratio_lo']*100:.0f}–{lt['ratio_hi']*100:.0f}%</b> of the price." if lt.get("ratio_lo") else "No holdings valued.")
        etf_html += (f'<section class="company" id="etf-{e(name)}"><h2>ETF look-through – {e(name)}</h2><p>{head}</p>'
                     f'<table class="kv"><tr><td><b>Holding</b></td><td><b>Name</b></td><td><b>Weight</b></td><td><b>Value ÷ price</b></td></tr>{body}</table></section>')
    heat_html = "".join(img(h, "heatmap") for h in heatmaps if h)
    if heat_html:
        heat_html = f'<section class="company" id="heatmaps"><h2>Scenario heatmaps – every company</h2>{heat_html}</section>'
    log = "".join(f"<li>{e(x)}</li>" for x in log_lines) or "<li>stored prices</li>"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} – value vs price</title><style>{CSS}</style></head><body><main>
<h1 id="summary">{e(title)} – value vs price</h1>
<p class="sub">{len(ordered)} companies · run {day(cfg['as_of'])} · spot gold ${sp['gold']:,.0f}, silver ${sp['silver']:.2f}, copper ${sp['copper']:.2f},
uranium ${sp['uranium']:.2f} · <span class="pos">{counts['green']} green</span>, {counts['blue']} blue, <span class="neg">{counts['red']} red</span>
· grades {' · '.join(f'{g} {n}' for g, n in grades.items() if n)}</p>
<p class="method"><b>Value vs price.</b> Value comes from the latest reported numbers only (no targets, no forecasts) and is compared
with today's price: owner earnings at today's metal prices × 12 / 15 / 25 + net cash for producers and royalties, NAV for developers
and physical holders, and for growth companies the yearly growth the price needs (5 years, 15x exit, 10% US / 12% India).
<b>Profit vs price.</b> Growth in profit and in the share price over about three years; the grade says whether the P/E fell
(A ≤ −25%, B ≤ 0) or rose (C ≤ +33%, D above). Click a ticker for the full working; click a column to sort.</p>
<nav class="toc">Companies: {toc}{' · <a href="#heatmaps">Heatmaps</a>' if heat_html else ''}</nav>
<div class="controls">
<span class="lab">Signal</span><button class="on" data-sig="all">All</button><button data-sig="green">Green</button>
<button data-sig="blue">Blue</button><button data-sig="red">Red</button>
<span class="lab">Grade</span><button class="on" data-grd="all">All</button>{''.join(f'<button data-grd="{g}">{g}</button>' for g in GRADE_ORDER)}
<input id="q" type="search" placeholder="Search ticker or name"><span class="lab" id="count"></span></div>
<div class="wrap"><table class="sum" id="sum"><thead>{SUMMARY_HEAD}</thead><tbody>
{''.join(summary_row(r, profit.get(r['ticker']), previous) for r in ordered)}</tbody></table></div>
{''.join(sections)}{etf_html}{heat_html}
<section class="company"><h2>Run log</h2><ul class="small">{log}</ul></section>
<footer>Educational framework, not investment advice. Previous run's figures in (brackets). Prices in each exchange's currency;
sales and profits as the company reports them.</footer>
</main><script>{JS}</script></body></html>"""
    path.write_text(page, encoding="utf-8")
    return path


def file_name(list_name: str | None, as_of) -> str:
    return f"{list_title(list_name).replace(' ', '_')}_Value_vs_Price_{as_of:%d%b%Y}.html"
