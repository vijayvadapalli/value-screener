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
import json
import re
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import charts, kinds, page, price_chart
from . import growth_screen as G
from . import profit_vs_price as pvp
from . import style as S
from .wording import (GROWTH_NOTE, RULES_NOTE, list_title, calc_steps, day, headline, key_figures, kpi_cards, money, npa_summary, price_date,
                      worked_example)

HTML_DPI = 150
SIGNAL_ORDER = {"green": 0, "blue": 1, "red": 2}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "n/m": 4}
URL_RE = re.compile(r"\b((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|gov|in|org|net|io|ca|uk|au)(?:/[^\s,;)]*)?)", re.I)


def e(x):
    return html.escape(str(x), quote=True)


def markup(text: str) -> str:
    """The paragraph mark-up wording.py writes (<b>, <br/>, <font>) → HTML."""
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
    return kinds.of(r["model"]).value_cell(r)


def _assumes_cell(r):
    """What the price already assumes: the metal price at 15x, the growth needed, or the metal at which NAV = price."""
    return kinds.of(r["model"]).assumes_cell(r)


def _buy_cell(r):
    ccy = r["price_ccy"]
    if r.get("buy_level") is None:
        return "–"
    if r.get("add_level") is not None:
        return f"<span class=nw>start ≤ {money(r['buy_level'], ccy)}</span><br><small>add ≤ {money(r['add_level'], ccy)}</small>"
    return f"<span class=nw>≤ {money(r['buy_level'], ccy)}</span>"


def _num(x):
    return "" if x is None else f"{x:.6g}"


def short_action(action: str) -> str:
    """The pill's word: 'Buy – start (≤ 15x)' → 'Buy', 'Watch / hold' → 'Watch'; the full text goes in the hover card."""
    word = action.split(" – ")[0]
    return {"Watch / hold": "Watch", "No valid value": "No value"}.get(word, word)


def _signal_cell(r, cfg):
    """A short pill; hovering (or tapping) it shows the full action, the headline sentence, any cap and the flags."""
    lines = ([f"<b>{e(r['action'])}</b>"] if r["action"] != short_action(r["action"]) else []) + [markup(headline(r, cfg))]
    if r.get("signal_caps"):
        lines.append("Capped at blue: " + e(", ".join(r["signal_caps"])) + ".")
    if r.get("flags"):
        lines.append("Flags: " + e(", ".join(r["flags"])))
    tip = "".join(f"<span>{x}</span>" for x in lines)
    return (f'<span class="pill {r["signal"]} hastip" tabindex="0">{e(short_action(r["action"]))}'
            f'<span class="tip" role="tooltip">{tip}</span></span>')


def summary_row(r, p, previous, cfg):
    t = r["ticker"]
    value, basis = _value_cell(r)
    assumes, assumes_v = _assumes_cell(r)
    prev = previous.get(t, {})
    prev_mos = f"<br><small>({pct(prev['margin_of_safety'])})</small>" if prev.get("margin_of_safety") is not None else ""
    grade = p["grade"] if p else "n/m"
    flags = " ".join(f"[{e(f)}]" for f in r.get("flags", []))
    if npa_summary(r):
        flags += ("<br>" if flags else "") + f"<small>{e(npa_summary(r))}</small>"
    text = f"{t} {r['name']} {r.get('sector', '')}".lower()
    late = "late" if (r.get("price_undated") or (r.get("price_age_days") or 0) > 7) else ""
    return f"""<tr data-signal="{r['signal']}" data-grade="{e(grade)}" data-text="{e(text)}">
<td data-v="{e(r['display_ticker'])}"><a href="#c-{e(t)}"><b>{e(r['display_ticker'])}</b></a><br><small>{e(r['name'])}</small></td>
<td data-v="{_num(r['price'])}">{money(r['price'], r['price_ccy'])}<br><small class="{late}">{price_date(r)}</small></td>
<td data-v="{_num(r.get('v_low'))}"><span class="nw">{value}</span><br><small>{basis}</small></td>
<td data-v="{_num(r.get('margin_of_safety'))}" class="{'pos' if (r.get('margin_of_safety') or -1) >= 0 else 'neg'}">{pct(r.get('margin_of_safety'))}{prev_mos}</td>
<td data-v="{_num(r.get('buy_level'))}">{_buy_cell(r)}</td>
<td data-v="{SIGNAL_ORDER[r['signal']]}" class="sig">{_signal_cell(r, cfg)}</td>
<td data-v="{_num(assumes_v)}">{assumes}</td>
<td data-v="{e(r.get('tier') or '')}" class="c">{e(r.get('tier') or '–')}</td>
<td data-v="{GRADE_ORDER[grade]}" class="c grade g{grade.replace('/', '')}">{e(grade)}</td>
<td data-v="{_num(p and p['pe_change'])}">{pct(p and p['pe_change'])}</td>
<td data-v="{_num(p and p['profit_growth'])}">{pct(p and p['profit_growth'])}</td>
<td data-v="{_num(p and p['price_growth'])}">{pct(p and p['price_growth'])}</td>
<td data-v="{_num(p and p.get('roe'))}">{pct(p and p.get('roe'))}</td>
<td class="flags">{flags}</td></tr>"""


HEADERS = [
    ("Ticker", "Click a ticker to jump to the company's full section"),
    ("Price", "Last closing share price and its date (orange = more than 7 days old)"),
    ("Value", "What a share is worth from the latest results; the line below says how it was valued"),
    ("Margin of safety", "How far the price is below the value: 30% = paying 70 for something worth 100. Last run in (brackets)"),
    ("Buy level", "The price at which the signal turns green"),
    ("Signal", "Green = buy, blue = watch / hold, red = expensive or no value. Hover a signal for the reason"),
    ("Price assumes", "Growth stocks: the yearly profit growth the price needs. Miners: the metal price the share price implies"),
    ("Tier", "How much the business is trusted, A = best"),
    ("Grade", "Profits vs share price over about 3 years: A = profits outran the price, D = the price ran ahead"),
    ("P/E change", "How the price-to-earnings ratio moved over the period; drives the grade"),
    ("Profit /yr", "Yearly profit growth over the period"),
    ("Price /yr", "Yearly share price growth over the period"),
    ("ROE", "Return on equity: profit as a % of the shareholders' money in the business. 15–20%+ is good, under 10% weak"),
    ("Flags", "Things to check yourself: stale data, one-offs, cyclicals and more"),
]
SUMMARY_HEAD = "<tr>" + "".join(f'<th title="{e(tip)}">{e(name)}</th>' for name, tip in HEADERS) + "</tr>"


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


def _price_cases(r):
    """The value at the metal prices in config `price_cases:` (price_cases.py) – one table per metal; empty if none."""
    tables = r.get("price_cases") or []
    if not tables:
        return ""
    ccy, price = r["price_ccy"], r["price"]
    out = []
    for t in tables:
        unit = "lb" if t["metal"] in ("uranium", "copper") else "oz"
        if t["kind"] == "multiples":
            heads = [f"{r['mult_lo']}x", f"{r['mult_hi']}x", f"{r['sell_multiple']}x sell"]
        else:
            heads = ["NAV / share", "Price ÷ NAV"]
        head = f'<tr><th>{e(t["metal"].title())} (US$/{unit})</th>' + "".join(f"<th>{h}</th>" for h in heads) + "</tr>"
        body = []
        for row in t["rows"]:
            p = f"{row['price']:,.0f}" if row["price"] >= 100 else f"{row['price']:,.2f}"
            label = f"{p} <small class=\"muted\">today's spot</small>" if row["spot"] else p
            cells = [f'<td class="{"pos" if v >= price else ""}">{money(v, ccy)}</td>' for v in row["values"]]
            if t["kind"] == "nav":
                nav = row["values"][0]
                cells.append(f"<td>{price / nav:.2f}x</td>" if nav > 0 else "<td>–</td>")
            body.append(f'<tr class="{"b" if row["spot"] else ""}"><td>{label}</td>{"".join(cells)}</tr>')
        out.append(f'<table class="mk pcase">{head}{"".join(body)}</table>')
        if t.get("note"):
            out.append(f'<p class="muted small">{e(t["note"])}</p>')
    return ('<h3>Price cases <small class="muted">– assumption, not reported</small></h3>' + "".join(out)
            + f'<p class="muted small">Value per share if the metal price held at each case, the company\'s own model re-run '
              f'with that one metal moved and everything else at spot. Green: at or above today\'s price '
              f'({money(price, ccy)}). Not a forecast: it shows what you would have to believe about the metal price.</p>')


def _times(x):
    return "–" if x is None else f"{x:.1f}x"


def _forward(r):
    """Owner earnings for coming years from the company's own estimates (forward.py), with every line, the checks
    against reported results and consensus, and analyst consensus as a reference row. Empty if the file has none."""
    years, cons = r.get("forward") or [], r.get("consensus") or []
    if not years:
        return ""
    ccy, price = r["price_ccy"], r["price"]
    lo, hi, sell = r["mult_lo"], r["mult_hi"], r["sell_multiple"]
    head = (f"<tr><th>Year</th><th>Owner earnings / share</th><th>{lo}x</th><th>{hi}x</th><th>{sell}x sell</th>"
            f"<th>Price ÷ earnings</th></tr>")
    rows = [f'<tr class="b"><td>Trailing (reported)</td><td>{money(r["oe"], ccy)}</td>'
            + "".join(f"<td>{money(v, ccy)}</td>" for v in (r["v_low"], r["v_high"], r["v_sell"]))
            + f'<td>{_times(r.get("pe"))}</td></tr>']
    for y in years:
        cells = "".join(f'<td class="{"pos" if v >= price else ""}">{money(v, ccy)}</td>' for v in y["values"])
        rows.append(f'<tr><td>{y["year"]} <small class="muted">company estimates</small></td><td>{money(y["oe_ps"], ccy)}</td>'
                    f'{cells}<td>{_times(y["pe"])}</td></tr>')
    for x in cons:
        rng = f", range {x['low']:,.2f}–{x['high']:,.2f}" if x.get("low") is not None else ""
        rows.append(f'<tr><td>{x["year"]} <small class="muted">analyst consensus EPS</small></td>'
                    f'<td>{money(x["eps_pc"], ccy)}</td><td colspan="3"><small class="muted">{x.get("currency", "")} '
                    f'{x["eps"]:,.2f} a share, {x.get("analysts", "?")} analysts{rng} – {e(x.get("source", ""))}, '
                    f'{e(str(x.get("date", "")))}. Adjusted EPS, not owner earnings: reference only</small></td>'
                    f'<td>{_times(x["pe"])}</td></tr>')
    detail = []
    for y in years:
        items = "".join(f'<tr><td>{e(x["name"])}{"" if x["taxed"] else " <small class=muted>(after tax)</small>"}</td>'
                        f'<td>{x["amount"]:,.0f}</td></tr>' for x in y["lines"])
        items += (f'<tr class="b"><td>Pre-tax total</td><td>{y["pre_tax"]:,.0f}</td></tr>'
                  f'<tr><td>Tax on the pre-tax total</td><td>{y["tax"]:,.0f}</td></tr>')
        detail.append(f'<details><summary>{y["year"]}: owner earnings {y["oe_m"]:,.0f}m ({e(r.get("currency", ""))}) – '
                      f'{e(y["basis"])}</summary><table class="kv">{items}<tr class="b"><td>Owner earnings</td>'
                      f'<td>{y["oe_m"]:,.0f}</td></tr></table></details>')
    checks = "".join(f"<li>{e(x)}</li>" for x in r.get("forward_checks", []))
    return (f'<h3>Forward – the company\'s own estimates <small class="muted">– assumption, not reported</small></h3>'
            f'<table class="mk pcase fwd">{head}{"".join(rows)}</table>{"".join(detail)}'
            + (f'<p class="muted small"><b>Checks</b></p><ul class="small">{checks}</ul>' if checks else "")
            + '<p class="muted small">Built line by line from the company\'s outlook, capital plan and contract table '
              '(sources in the assumptions below). The headline value stays on reported results. Green: at or above '
              'today\'s price.</p>')


def _pvp_block(p):
    if not p:
        return '<p class="muted">No profit-vs-price figures for this company (none fetched, or the list was run with --no-profit).</p>'
    if p["grade"] == "n/m" and p.get("profit_growth") is None and p.get("sales_growth") is None:
        return f'<div class="pvp"><div class="bigrade gnm">n/m</div><div><p>{pvp.comment(p)}</p></div></div>'
    ccy = p["report_ccy"]
    unit = "cr" if p.get("source") == "screener" else "m"
    amount = lambda x: pvp._amount(x, ccy, unit)  # noqa: E731
    local = p.get("source") == "v2"
    then_now = (("EPS then → now", f"{S.money(p['eps_then'], ccy, 2)} → {S.money(p['eps_now'], ccy, 2)}") if local else
                ("Net profit then → now", f"{amount(p.get('profit_then'))} → {amount(p.get('profit_now'))}"))
    rows = [*([] if local else [("Sales growth a year", pct(p["sales_growth"]))]),
            ("Profit growth a year" + (" (EPS)" if p.get("source") in ("yahoo", "v2") else ""), pct(p["profit_growth"])),
            then_now,
            ("Share price growth a year", pct(p["price_growth"])),
            ("Share price, last year", pct(p.get("price_change_1y"))),
            ("P/E change over the period", pct(p["pe_change"])),
            ("P/E now", "–" if not p.get("pe_now") else f"{p['pe_now']:.1f}"),
            ("Return on equity" + (" (5-year average)" if local else ""), "–" if p.get("roe") is None else f"{p['roe']*100:.0f}%"),
            ("Period", f"{e(p.get('base_label') or '?')} → {e(p.get('latest_label') or '?')} ({p['years']:.1f} years)")]
    table = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    source = p.get("page") or ""
    src = f' · <a href="{e(source)}" target="_blank" rel="noopener">Screener page</a>' if source else ""
    return (f'<div class="pvp"><div class="bigrade g{p["grade"].replace("/", "")}">{e(p["grade"])}</div><div>'
            f'<p>{pvp.comment(p)}</p><table class="kv">{table}</table>'
            f'<p class="muted">Source: {pvp.SOURCE_LABEL.get(p.get("source"), "Yahoo Finance statements")}{src}</p></div></div>')


SCREENER_RE = re.compile(r"https?://(?:www\.)?screener\.in/company/[^\s,;)]+", re.I)


def screener_url(c: dict) -> str | None:
    """The company's Screener.in page: the one named in its sources, else built from the NSE / BSE ticker; None for
    companies not listed in India."""
    for s in c.get("sources", []):
        m = SCREENER_RE.search(str(s))
        if m:
            return m.group(0).rstrip(".")
    if str(c.get("yahoo", "")).upper().endswith((".NS", ".BO")):
        return f"https://www.screener.in/company/{c['ticker']}/consolidated/"
    return None


def company_section(r, c, cfg, p, neighbours, chart_dir, tech, pchart=None):
    t = r["ticker"]
    prev_t, next_t = neighbours
    nav = ['<a href="#summary">↑ Summary</a>']
    if prev_t:
        nav.append(f'<a href="#c-{e(prev_t)}">← {e(prev_t)}</a>')
    if next_t:
        nav.append(f'<a href="#c-{e(next_t)}">{e(next_t)} →</a>')
    meta = [kinds.of(r["model"]).label] + ([f"tier {r['tier']}"] if r.get("tier") else [])
    reported = f", reported {day(r['period_reported'])}" if r.get("period_reported") else ""
    meta += [f"results {e(r['period'])} (to {day(r['period_end'])}{reported})", f"price {price_date(r)} · {e(r.get('price_source', ''))}"]
    if url := screener_url(c):
        meta.append(f'<a href="{e(url)}" target="_blank" rel="noopener">Screener.in page – full financials ↗</a>')
    flags = " ".join(f"[{e(f)}]" for f in r.get("flags", []))
    band = charts.band(r, chart_dir / f"{t}_band.png")
    curve = charts.curve(r, c, cfg, chart_dir / f"{t}_curve.png")
    heat = charts.heatmap(r, c, cfg, chart_dir / f"{t}_heat.png")
    extra = charts.eps_history(r, chart_dir / f"{t}_eps.png") if r.get("v2") else charts.extra(r, chart_dir / f"{t}_bridge.png")
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
{chart_block(t, pchart)}
{img(band, 'valuation band')}
<div class="grid2"><div>{img(curve, 'curve')}</div><div><h3>Key figures</h3>{_key_figures(r)}{_price_cases(r)}</div></div>
{_forward(r)}
<div class="grid2"><div>{img(heat, 'heatmap')}{img(extra, 'history')}</div>
<div><h3>How the value is calculated</h3><ol>{steps}</ol>{example_html}{tech_html}</div></div>
<h3>Profit growth vs price growth</h3>{_pvp_block(p)}
<div class="grid2"><div><h3>Assumptions and data notes</h3><ul class="small">{notes_html}</ul></div>
<div><h3>Sources</h3><ul class="small">{sources_html}</ul></div></div>
</section>"""


def chart_block(t: str, p: dict | None) -> str:
    """The interactive price chart (Lightweight Charts) with its data, or nothing when there is no price history."""
    if not p:
        return ""
    data = json.dumps(p, separators=(",", ":")).replace("</", "<\\/")
    values_tip = " · ".join(f"{v['label']} {v['price']:,.2f}" for v in p["values"]) or "no value lines"
    note = "" if p["same_currency"] else f" · chart in {e(p['currency'])}, valuation in another currency – value lines left off"
    key = (f'<i style="border-color:{price_chart.SMA_COLOURS[20]}"></i>SMA 20 <i style="border-color:{price_chart.SMA_COLOURS[50]};border-top-width:3px"></i>SMA 50 '
           f'<i style="border-color:{price_chart.SMA_COLOURS[200]};border-top-width:4px"></i>SMA 200</span><span>buttons: '
           f'<i style="border-color:{price_chart.LIGHT_GREEN};border-top-width:3px"></i>15x value / buy · <i style="border-color:{price_chart.DARK_GREEN};border-top-width:3px"></i>12x value / NAV · '
           '<i style="border-color:var(--red);border-top-width:3px"></i>25x sell zone · <i style="border-color:var(--green)"></i>support · '
           '<i style="border-color:var(--red)"></i>resistance (auto)</span><span><i style="border-color:#4299E1"></i><i style="border-color:#B794F4">'
           '</i>trend lines (auto) · E results · D dividend · S split')
    return f"""<div class="pc" id="pc-{e(t)}" data-pc="pcd-{e(t)}">
<div class="pc-bar"><button data-iv="D">D</button><button data-iv="W">W</button><button data-iv="M">M</button><span class="sep"></span>
{''.join(f'<button data-rg="{x}">{x}</button>' for x in ('6M', '1Y', '3Y', '5Y', '10Y') + (('Max',) if p.get('mode') == 'research' or p.get('max_range') else ()))}<span class="sep"></span>
<button data-ma title="20-, 50- and 200-day averages and the automatic trend lines">Averages &amp; trends</button>
<button data-pat title="Chart patterns drawn in the report (shown on the monthly view)">Patterns</button>
<button data-val title="{e(values_tip)}">Value lines</button>
<button data-sr title="The nearest support below and resistance above the price (found automatically)">Support / resistance</button>
<button data-lv title="Every support and resistance level found, not just the nearest">All levels</button>
<button data-wl title="Support (teal) and resistance (orange) levels being watched">{e(p.get("watched_label", "Watched levels"))}</button>
<button data-vol title="Show daily volume under the price">Volume</button><span class="pc-legend"></span></div>
<div class="pc-rsi"></div><div class="pc-main"></div>
<div class="pc-key"><span>{key}</span></div>
<p class="pc-cap"><b>Price</b> ({e(p['symbol'])}, {e(p['currency'] or '')}): {e(price_chart.caption(p))}{note}</p>
{f'<p class="pc-cap"><b>Value lines</b>: {e(values_tip)}</p>' if p["values"] else ""}
<script type="application/json" id="pcd-{e(t)}">{data}</script></div>"""


# ------------------------------------------------------------------------------------------------- summary extras
def legend_html(rows) -> str:
    """Signal colours, then what the tint strength means: tiers for a tiered list, otherwise market value."""
    tiered = any(r.get("tier") for r in rows)
    shades = (["Tier A · large, low-cost, royalties", "Tier B · mid-tier / higher cost", "Tier C · juniors, developers"] if tiered
              else ["≥ $100bn (tech ≥ $200bn)", "$30–100bn", "$10–30bn", "< $10bn"])
    chips = [f'<span class="chip" style="background:{S.SIGNAL[k]};color:#fff">{e(t)}</span>'
             for k, t in (("green", "Green · buy / start a position"), ("blue", "Watch / hold"), ("red", "Red · expensive or no valid value"))]
    chips += [f'<span class="chip" style="background:{S.TINT["blue"][i]};color:{S.INK}">{e(t)}</span>' for i, t in enumerate(shades)]
    return '<div class="legend">' + "".join(chips) + "</div>"


def _quality_html(r) -> str:
    if r.get("pb") is not None and r.get("fair_pb") is not None:
        label = "P/ABV" if (r.get("asset_quality") or {}).get("bad_loans_ps") else "P/B"
        npa = npa_summary(r).replace(" gross · ", " / ").replace(" net", "")
        return f"{label} {r['pb']:.1f}<br><small>fair {r['fair_pb']:.1f}{' · ' + e(npa) if npa else ''}</small>"
    if r.get("cash_conversion") is not None:
        cc = r["cash_conversion"]
        return f'<span class="{"neg" if cc < 0.7 else ""}">cash {cc*100:.0f}%</span>'
    if r.get("fcf_ps") is not None and r.get("price"):
        return f"FCF {r['fcf_ps'] / r['price'] * 100:.1f}%"
    return "–"


def growth_table_html(rows, previous, heading: bool = True) -> str:
    """Growth companies: value with no growth, at 10% and 20% a year, the growth the price needs, and quality.
    `heading` False: the page's tab already names it."""
    head = ["Ticker", "Price", "No growth", "@ 10%/yr", "@ 20%/yr", "Growth needed", "MoS", "P/E", "Quality", "Mkt value", "Signal", "Buy price"]
    body = []
    for r in rows:
        ccy, g = r["price_ccy"], r.get("implied_growth")
        before = previous.get(r["ticker"], {}).get("implied_growth")
        mv = r.get("market_value_usd_bn")
        mos = r.get("margin_of_safety")
        pe_txt = f"{r['pe']:.1f}" if r.get("pe") else "–"
        body.append(
            f'<tr data-signal="{r["signal"]}"><td><a href="#c-{e(r["ticker"])}"><b>{e(r["display_ticker"])}</b></a><br><small>{e(r["name"])}</small></td>'
            f'<td class="nw">{money(r["price"], ccy)}</td><td class="nw">{money(r["v0"], ccy)}</td><td class="nw">{money(r.get("v10"), ccy)}</td>'
            f'<td class="nw">{money(r.get("v20"), ccy)}</td>'
            f'<td class="nw"><b>{pct(g, 1) if g is not None else "–"}</b>{f"<br><small>({pct(before, 1)})</small>" if before is not None else ""}</td>'
            f'<td class="nw {"pos" if (mos or -1) > 0 else "neg"}">{pct(mos) if mos is not None else "–"}</td>'
            f'<td>{pe_txt}</td><td>{_quality_html(r)}</td>'
            f'<td class="nw">{"–" if mv is None else (f"${mv:,.0f}bn" if mv >= 10 else f"${mv:,.1f}bn")}</td>'
            f'<td class="sig"><span class="pill {r["signal"]}">{e(short_action(r["action"]))}</span></td>'
            f'<td class="nw">{money(r.get("buy_level"), ccy) if r.get("buy_level") else "–"}</td></tr>')
    return ((f'<h3 id="growth">Growth companies – reverse DCF</h3>' if heading else "") + '<div class="wrap"><table class="sum gt"><thead><tr>'
            + "".join(f"<th>{e(h)}</th>" for h in head) + f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
            f'<p class="small">{GROWTH_NOTE}</p>')


# ------------------------------------------------------------------------------------------------- page
MARKETS_NOTE = ("Price only – commodities, an index and ETFs have no earnings, so they are not valued. Daily prices from Yahoo "
                "(futures for gold, silver and oil); uranium is Cameco's month-end spot price, so it has no daily figures. "
                "vs 50-day / 200-day = price against that moving average.")


def markets_html(rows: list[dict]) -> str:
    """The Markets section: one table of price facts, then a chart for each."""
    if not rows:
        return ""

    def num(x, nd=1):
        return "–" if x is None else f"{x:,.{nd}f}"

    def signed(x):
        return "–" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{pct(x, 1)}</span>'

    body = "".join(
        f'<tr><td><a href="#m-{e(r["ticker"])}"><b>{e(r["ticker"])}</b></a></td><td>{e(r["name"])}</td>'
        f'<td>{num(r["price"], 2)} <span class="small">{e(r["unit"] or r["currency"] or "")}</span></td><td>{e(r["date"])}</td>'
        f'<td>{signed(r["chg_1w"])}</td><td>{signed(r["chg_1m"])}</td><td>{signed(r["chg_1y"])}</td>'
        f'<td>{signed(r["vs50"])}</td><td>{signed(r["vs200"])}</td><td>{num(r["rsi"], 0)}</td>'
        f'<td>{num(r["low52"], 2)}–{num(r["high52"], 2)}</td></tr>' for r in rows)
    head = "".join(f"<th>{h}</th>" for h in ("Market", "Name", "Price", "Date", "1 week", "1 month", "1 year", "vs 50-day",
                                             "vs 200-day", "RSI", "52-week range"))
    charts_ = "".join(f'<h3 id="m-{e(r["ticker"])}">{e(r["ticker"])} – {e(r["name"])}</h3>'
                      + (f'<p class="small">{e(r["note"])}</p>' if r["note"] else "") + chart_block(f"M-{r['ticker']}", r["chart"])
                      for r in rows)
    return (f'<section class="company" id="markets"><h2>Markets – price only, not valued</h2><p class="notes">{MARKETS_NOTE}</p>'
            f'<div class="wrap"><table class="mk"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{charts_}</section>')


INDIA_SCREEN_TAIL = "Flags: promoter holding falling; pledged shares are not in the data yet."


PILL_STYLE = {"cyclical": "background:#B7791F", "state-owned": "background:#5A6474"}
PILL_FLAGS = tuple(PILL_STYLE)


def screen_quality(r: dict) -> str:
    """The growth screen's Quality cell: for banks and NBFCs the 5-year ROE over P/B (or P/ABV) against the fair
    multiple and their NPA (_quality_html); for the rest cash conversion. The ROE is the one behind the fair multiple
    (fair P/B = 5-year ROE × the no-growth multiple)."""
    src = r.get("quality_src") or {}
    if not src:
        return "–"
    roe = (src["fair_pb"] / src["no_growth_multiple"]
           if src.get("pb") is not None and src.get("fair_pb") is not None and src.get("no_growth_multiple") else None)
    return (f"ROE {roe*100:.0f}%<br>" if roe is not None else "") + _quality_html(src)


def screen_pills(r: dict) -> str:
    """[cyclical] and [state-owned] as pills on shortlist and near-miss rows, where they matter most."""
    if not r.get("tier"):
        return ""
    on = [f for f in PILL_FLAGS if f in r["flags"]]
    return "".join(f'<br><span class="pill" style="{PILL_STYLE[f]};font-size:11px;padding:1px 8px">{f}</span>' for f in on)


SLIDERS = [   # (setting, label, step, min, max) – the panel's sliders; percentages in %
    ("pe", "Max P/E", 0.5, 5, 40), ("growth", "Min EPS growth", 1, 0, 40), ("ret", "Min 5-yr return", 0.5, 0, 25),
    ("years", "Holding years", 1, 1, 10), ("exit", "Exit multiple", 1, 5, 30), ("promoters", "Min promoters", 1, 0, 90)]
PCT_SETTINGS = ("growth", "ret", "promoters")


def screen_panel(rows: list[dict], s: dict, href, market: str = "india", list_name: str = "Midcap 150",
                 title: str | None = None) -> str:
    """The settings panel, folded under 'Change the rules', and the data assets/screen.js needs: every row's figures
    and the default rules. The panel stays hidden without JavaScript, and the table the server wrote stays as it is. `market` "us" leaves out
    the India-only rules (promoters, government-owned, Midcap 150 only) – insiders are shown, never a rule."""
    india = market == "india"
    rules = {"pe": s["max_pe"], "growth": s["min_eps_cagr"], "ret": s["min_return"], "years": s["years"], "exit": s["exit_multiple"],
             "haircut": s["growth_haircut"], "cap": s["max_assumed_growth"], "promoters": s.get("min_promoter", 0.0),
             "pe0": s["max_pe"], "growth0": s["min_eps_cagr"], "near_pe": s["near_max_pe"], "near_growth": s["near_min_eps_cagr"],
             **G.filters(s, rows), "all": False,
             "bounds": {k: [lo / 100, hi / 100] if k in PCT_SETTINGS else [lo, hi] for k, _, _, lo, hi in SLIDERS}}
    if not india:
        rules["market"] = market
    data = [{"ticker": r["ticker"], "name": r["name"], "link": href(r["ticker"]), "price": r["price"], "eps": r["eps"], "nc": r["nc"],
             "pe": r["pe"], "pe_trailing": r["pe_trailing"], "c5": r["eps_cagr_5y"], "c3": r["eps_cagr_3y"],
             "pos": r["every_year_positive"], "guards": r["guards"], "promoters": r["promoters"], "pledged": r.get("pledged"),
             "state_owned": r.get("state_owned", False), "cyclical": r.get("cyclical", False), "extra": r.get("extra"),
             "signal": r["signal"], "action": r["action"], "growth_needed": r["growth_needed"], "flags": r["flags"],
             "quality": screen_quality(r)} for r in rows]
    slider = lambda k, label, step, lo, hi: (f'<label>{label} <b data-out="{k}"></b>'  # noqa: E731
                                            f'<input type="range" data-k="{k}" step="{step}" min="{lo}" max="{hi}"></label>')
    box = lambda k, label: f'<label class="cb"><input type="checkbox" data-k="{k}">{label}</label>'  # noqa: E731
    has_extra = any(r.get("extra") for r in rows)
    sliders = "".join(slider(*x) for x in SLIDERS if india or x[0] != "promoters")
    boxes = ((box("prule", "Promoter rule") + box("psu", "Exclude government-owned") + (box("mid", f"{e(list_name)} only") if has_extra else ""))
             if india else "") + box("cyc", "Exclude cyclicals") + box("all", "Show all")
    reset = "Reset to Dr. Gupta's rules" if india and not title else "Reset to the default rules"   # a list's own rules: not his
    return (f'''<style>#screen .panel{{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:end;background:var(--soft);border:1px solid var(--line);
border-radius:8px;padding:10px 12px;margin:8px 0}} #screen .panel label{{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}}
#screen .panel label b{{color:var(--ink);font-variant-numeric:tabular-nums}} #screen .panel input[type=range]{{width:130px;margin:4px 0 0;accent-color:#2F64CF}}
#screen .panel label.cb{{flex-direction:row;align-items:center;gap:5px}} #screen .panel button{{font:inherit;padding:5px 10px;border-radius:6px;
border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}}</style>
<details class="tweak" hidden open><summary>Change the rules</summary><div class="panel">{sliders}
{boxes}
<button type="button" data-reset>{reset}</button>{"<small>Pledged shares: not in the data yet.</small>" if india else ""}</div></details>
<script type="application/json" id="screen-data">{_js(data)}</script><script type="application/json" id="screen-rules">{_js(rules)}</script>''')


def _compact(x):
    """Numbers to 9 significant digits – far finer than any threshold or anything shown, half the size."""
    if isinstance(x, float):
        return float(f"{x:.9g}")
    if isinstance(x, dict):
        return {k: _compact(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_compact(v) for v in x]
    return x


def _js(x) -> str:
    """JSON safe inside a <script> element, numbers compacted."""
    return json.dumps(_compact(x), separators=(",", ":")).replace("</", "<\\/")


def growth_screen_html(rows: list[dict], cfg: dict, key: str = "growth_screen", owners: str = "Promoters",
                       tail: str | None = None, href=None, panel: bool = False, after: str = "",
                       list_name: str = "Midcap 150", title: str | None = None) -> str:
    """The growth-at-a-value-price screen (growth_screen.py): shortlist and near misses, then everyone else folded away.
    `key` picks the thresholds (growth_screen for India, us_growth_screen for the US), `owners` names the ownership
    column, `tail` closes the explanation, `href(ticker)` gives a company's link (None: no link), `after` goes at the
    end of the section (the answer box). The tables show the panel's default switches (growth_screen.apply_filters);
    the panel gets every row."""
    if not rows:
        return ""
    s = cfg[key]
    every, rows = rows, G.apply_filters(rows, s)
    href = href or (lambda t: f"#c-{t}")
    if tail is None:
        tail = INDIA_SCREEN_TAIL.format(min_promoter=s["min_promoter"] * 100)

    def p(x, nd=0):
        return "–" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x*100:+.{nd}f}%</span>'

    def row(r):
        tier = {"shortlist": '<span class="pill green">Shortlist</span>', "near miss": '<span class="pill blue">Near miss</span>'}.get(r["tier"], "")
        why = [{"pe": "P/E", "growth": "growth", "return": "5-yr return"}[m] for m in r["missed"]] if r["tier"] != "shortlist" else []
        notes = ("misses: " + ", ".join(why) if why else "") + (" · " if why and r["guards"] else "") + ", ".join(r["guards"])
        flags = " ".join(f"[{e(f)}]" for f in r["flags"] if not (r["tier"] and f in PILL_FLAGS))   # pills instead
        pe = "–" if r["pe"] is None else f"{r['pe']:.1f}"
        trailing = "" if r["pe_trailing"] is None else f"<br><small>trailing {r['pe_trailing']:.1f}</small>"
        assumed = "" if r["assumed_growth"] is None else f"<br><small>at {r['assumed_growth']*100:.0f}%/yr growth</small>"
        prom = "–" if r["promoters"] is None else f"{r['promoters']*100:.0f}%"
        link = href(r["ticker"])
        name = f'<a href="{e(link)}"><b>{e(r["ticker"])}</b></a>' if link else f'<b>{e(r["ticker"])}</b>'
        return (f'<tr><td>{name}<br><small>{e(r["name"])}</small>{screen_pills(r)}'
                f'{"<br><small class=late>" + flags + "</small>" if flags else ""}</td><td>{tier}</td>'
                f'<td data-v="{_num(r["pe"])}">{pe}{trailing}</td><td>{screen_quality(r)}</td>'
                f'<td>{p(r["eps_cagr_5y"])} / {p(r["eps_cagr_3y"])}'
                f'{"" if r["every_year_positive"] else "<br><small class=neg>a loss year</small>"}</td>'
                f'<td>{p(r["growth_needed"], 1)}</td><td>{p(r["expected_return"], 1)}{assumed}</td><td>{prom}</td>'
                f'<td><span class="pill {r["signal"]}">{e(short_action(r["action"]))}</span></td><td><small>{e(notes)}</small></td></tr>')

    head = ("<thead><tr><th>Company</th><th>Screen</th><th>P/E</th><th>Quality</th><th>EPS growth 5 / 3 yrs</th><th>Price needs</th>"
            f"<th>{return_label(s)}</th><th>{e(owners)}</th><th>Signal</th><th>Why not</th></tr></thead>")
    short = [r for r in rows if r["tier"] == "shortlist"]
    near = [r for r in rows if r["tier"] == "near miss"]
    others = [r for r in rows if r["tier"] != "shortlist"]   # near misses first, then the rest, best first
    table = lambda rs: f'<div class="wrap"><table class="sum">{head}<tbody>{"".join(row(r) for r in rs)}</tbody></table></div>'  # noqa: E731
    tables = ((table(short) if short else NO_PASS.format("today"))
              + near_line_html(near, href)
              + (f'<details><summary>Near misses and the other {len(others) - len(near)}, in full</summary>{table(others)}</details>'
                 if others else ""))
    market = "us" if key == "us_growth_screen" else "india"
    heading = (f'<h2>Screen – {len(short)} shortlisted, {len(near)} near miss{"" if len(near) == 1 else "es"} of {len(rows)}'
               f'{left_out_html(every, G.filters(s, every))}</h2>')
    funnel = f'<p class="funnel">{funnel_text(funnel_steps(every, s))}</p>{GUARDS_LINE}'
    if panel:   # the settings panel (open, can be folded), the funnel and assets/screen.js
        return (f'<section class="company" id="screen">{heading}{rules_html(s, tail, market, list_name, every)}{screen_panel(every, s, href, market, list_name, title)}{funnel}'
                f'<div class="screen-tables">{tables}</div>{after}'
                f'<script>{page.asset("screen.js")}</script></section>')
    return f'<section class="company" id="screen">{heading}{rules_html(s, tail, market, list_name, every)}{funnel}{tables}{after}</section>'


GROWTH_INTRO = ("<b>How much growth today's price already assumes</b> (a reverse DCF): the value with no growth and at 10% "
                "and 20% a year, and the yearly growth the price needs – the lower it is, the less has to go right.")
GUARDS_LINE = ('<p class="notes">Before the rules apply, stocks are dropped for weak cash conversion, one-off or demerger '
               'profits, or bad-loan warnings.</p>')


def return_label(s: dict) -> str:
    """The return column's header with how the return is worked out; the numbers carry data-r so screen.js keeps them
    in step with the sliders."""
    cut = "halved" if s["growth_haircut"] == 0.5 else f"× {s['growth_haircut']:g}"
    return (f'<span data-r="years">{s["years"]}</span>-yr return a year<br><small>past growth {cut}, sold at '
            f'<span data-r="exit">{s["exit_multiple"]:g}x</span></small>')


NO_PASS = '<p class="nopass">No company passes all five rules {}.</p>'   # screen.js writes the same, "with these settings"


def left_out_html(rows: list[dict], f: dict) -> str:
    """Why the screen counts fewer companies than the page header: who the switches leave out (screen.js leftOut writes
    the same), e.g. ' <span>· 2 added by hand left out</span>'."""
    extra = sum(1 for r in rows if f["mid"] and r.get("extra"))
    cyc = sum(1 for r in rows if not (f["mid"] and r.get("extra")) and f["cyc"] and r.get("cyclical"))
    parts = ([f"{extra} added by hand"] if extra else []) + ([f"{cyc} cyclical{'s' if cyc > 1 else ''}"] if cyc else [])
    return f' <span>· {" and ".join(parts)} left out</span>' if parts else ""


def rules_html(s: dict, tail: str, market: str = "us", list_name: str = "Midcap 150", rows: list[dict] | None = None) -> str:
    """The growth screen's five rules in plain words, folded under a one-line summary. India: Dr. Gupta's five – mid
    cap (the list's own members), cheap, growing, promoters, a 5-year hold; clean books and current results are the
    guards before them (GUARDS_LINE). The US has no promoter group: cheap, growing, profitable, worth holding, clean
    books. The numbers carry data-r so assets/screen.js shows the panel's settings – in the summary too – and a
    switched-off rule says so (data-off)."""
    v = {k: f'<b data-r="{k}">{text}</b>' for k, text in (
        ("pe", f"{s['max_pe']:g}"), ("growth", f"{s['min_eps_cagr']*100:.0f}%"), ("ret", f"{s['min_return']*100:.0f}%"),
        ("years", f"{s['years']}"), ("exit", f"{s['exit_multiple']:g}x"), ("near_pe", f"{s['near_max_pe']:g}"),
        ("near_growth", f"{s['near_min_eps_cagr']*100:.0f}%"), ("promoters", f"{s.get('min_promoter', 0)*100:.0f}%"))}
    cheap = (f'<li><b>Cheap.</b> The P/E is {v["pe"]} or less (the price less net cash, divided by the earnings per share '
             'the valuation uses).</li>')
    hold = (f'<li><b>Worth holding.</b> At least {v["ret"]} a year expected over a {v["years"]}-year hold, if growth slows to '
            f'half its past rate (at most {s["max_assumed_growth"]*100:.0f}%) and the shares are sold at {v["exit"]} earnings. '
            'Dividends are not counted.</li>')
    near = (f'<p class="notes"><b>Near miss</b> = one rule short: a P/E up to {v["near_pe"]} with growth met, growth down to '
            f'{v["near_growth"]} with the P/E met, or only the return short. {tail}</p></details>')
    if market == "india":
        f = G.filters(s, rows)
        off = lambda k: f'<span data-off="{k}"{" hidden" if f[k] else ""}> – switched off below</span>'  # noqa: E731
        no_data = rows and not any(r.get("promoters") is not None for r in rows)
        extras = any(r.get("extra") for r in rows or [])   # without stocks added by hand the membership rule has no switch
        prom = "" if no_data else f' · promoters ≥ {v["promoters"]}'
        member = "Mid cap" if "midcap" in list_name.lower().replace(" ", "") else "In the index"
        return (
            f'<details class="rules"><summary>The five rules <small>· {e(list_name)} · P/E ≤ {v["pe"]} · EPS growth ≥ '
            f'{v["growth"]}{prom} · ≥ {v["ret"]} a year over a {v["years"]}-year hold</small></summary>'
            f'<ol class="rules"><li><b>{member}.</b> A member of the {e(list_name)}'
            + (f' – not one of the stocks added by hand{off("mid")}' if extras else "") + '.</li>'
            f'{cheap}<li><b>Growing.</b> Earnings per share grew at least {v["growth"]} a year over both the last 5 years and the '
            'last 3, with a profit in every one of those years.</li>'
            f'<li><b>Promoters.</b> Promoters hold at least {v["promoters"]} of the shares'
            + (' – not applied here: the company files carry no promoter holding' if no_data else off("prule")) + '.</li>'
            f'{hold}</ol>{near}')
    return (
        f'<details class="rules"><summary>The five rules <small>· P/E ≤ {v["pe"]} · EPS growth ≥ {v["growth"]} · a profit '
        f'every year · ≥ {v["ret"]} a year over {v["years"]} years · clean books</small></summary><ol class="rules">'
        f'{cheap}<li><b>Growing.</b> Earnings per share grew at least {v["growth"]} a year over both the last 5 years and the '
        'last 3.</li><li><b>Profitable every year.</b> No loss year in that window.</li>'
        f'{hold}<li><b>Clean books.</b> At least {s["min_cash_conversion"]*100:.0f}% of profit arrives as cash, no demerger or '
        f'one-off history, no bad-loan warning, and up-to-date results.</li></ol>{near}')


FUNNEL_WORDS = {"after guards": "have clean books and a profit every year", "+ growth": "grew fast enough",
                "+ P/E": "are cheap enough", "+ 5-yr return": "promise enough return",
                "+ promoters": "have enough promoter holding", "+ government-owned rule": "are not government-owned"}


def funnel_steps(rows: list[dict], s: dict | None = None) -> list[tuple[str, int]]:
    """How many companies survive each rule at the default settings – the same steps as funnel() in screen.js. With the
    screen's config `s`, its default switches (growth_screen.filters) narrow the start and add their own steps."""
    f = G.filters(s or {}, rows)
    left = [r for r in rows if G.in_universe(r, f)]
    steps = [("Start", len(left))]
    tests = [("after guards", lambda r: not r["guards"]), ("+ growth", lambda r: "growth" not in r["missed"]),
             ("+ P/E", lambda r: "pe" not in r["missed"]), ("+ 5-yr return", lambda r: "return" not in r["missed"])]
    if f["prule"]:
        tests.append(("+ promoters", lambda r: r["promoters"] is not None and r["promoters"] >= (s or {}).get("min_promoter", 0.0)))
    if f["psu"]:
        tests.append(("+ government-owned rule", lambda r: not r["state_owned"]))
    for label, test in tests:
        left = [r for r in left if test(r)]
        steps.append((label, len(left)))
    return steps


def funnel_text(steps) -> str:
    """The funnel as one sentence: 'Of 142 companies, 120 have clean books …, 30 of those grew fast enough, …'.
    screen.js has the same wording (funnelText)."""
    (_, n0), rest = steps[0], steps[1:]
    parts = [f"<b>{n}</b> {'of those ' if i else ''}{FUNNEL_WORDS[label]}" for i, (label, n) in enumerate(rest)]
    body = ", ".join(parts[:-1]) + (", and " if len(parts) > 1 else "") + parts[-1]
    return f"Of <b>{n0}</b> companies, {body} – the shortlist."


def _short_of(r: dict) -> str:
    """What a near miss falls short on, with its figure: 'P/E 17.2', 'growth 18%', 'return 9% a year'."""
    out = []
    for m in r["missed"]:
        if m == "pe":
            out.append("no P/E" if r["pe"] is None else f"P/E {r['pe']:.1f}")
        elif m == "growth":
            g = None if r["eps_cagr_5y"] is None or r["eps_cagr_3y"] is None else min(r["eps_cagr_5y"], r["eps_cagr_3y"])
            out.append("growth unknown" if g is None else f"growth {g*100:.0f}%")
        elif m == "return":
            ret = r["expected_return"]
            out.append("no return" if ret is None else f"return {ret*100:.0f}% a year")
    return ", ".join(out)


def _ticker_link(ticker: str, link) -> str:
    return f'<a href="{e(link)}"><b>{e(ticker)}</b></a>' if link else f"<b>{e(ticker)}</b>"


def near_line_html(near: list[dict], href) -> str:
    """The near misses on one line, each with what it falls short on (screen.js nearLine writes the same)."""
    if not near:
        return '<p class="near"><b>Near misses:</b> none.</p>'
    items = " · ".join(f'{_ticker_link(r["ticker"], href(r["ticker"]))} <small>({e(_short_of(r))})</small>' for r in near)
    return f'<p class="near"><b>Near misses:</b> {items}</p>'


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _bt_picks_ret(b: dict):
    return b.get("picks_ret", b.get("picks_total"))


def answer_html(rows: list[dict], results: list[dict], index_name: str, href=None, below: bool = False) -> str:
    """The answer: how many pass today and which, the near misses, and what the same rules returned since the earliest
    backtest date with picks. screen.js rewrites it when the panel's settings differ. `below`: it sits under the screen's
    results, where an empty shortlist is already said (NO_PASS) – then only the backtest line."""
    if not rows:
        return ""
    href = href or (lambda t: f"#c-{t}")
    short = [r for r in rows if r["tier"] == "shortlist"]
    near = [r for r in rows if r["tier"] == "near miss"]
    names = lambda rs: _and_list([_ticker_link(r["ticker"], href(r["ticker"])) for r in rs])  # noqa: E731
    if short:
        today = (f'<b>Today {len(short)} {"stock passes" if len(short) == 1 else "stocks pass"} all five rules:</b> '
                 f'{names(short)}.')
    else:
        today = "<b>Today no stock passes all five rules.</b>"
    if near:
        today += f' {len(near)} more {"misses" if len(near) == 1 else "miss"} by one rule: {names(near)}.'
    bt = ""
    b = next((b for b in results if b["picks"]), None)
    if results:
        if b is None:
            bt = "<b>Backtest:</b> no stock passed these rules on any of the past dates tested."
        else:
            what = "price only" if not b.get("dividends", True) else "with dividends"
            pr, n = _bt_picks_ret(b), len(b["picks"])
            a_year = (f" ({((1 + pr) ** (1 / b['years']) - 1)*100:+.1f}% a year)" if pr is not None and pr > -1 and b["years"] > 0 else "")
            bt = (f'<b>Backtest:</b> the {n} pick{"s" if n > 1 else ""} of {day(b["start"])} {"are" if n > 1 else "is"} up {S.pct(pr, 0) if pr is not None else "–"}'
                  f'{a_year} {what}, against {S.pct(b.get("all_ret", b.get("all_total")), 0)} for every stock screened and '
                  f'{S.pct(b["index_price"], 0)} for the {e(index_name)} (price only). <a href="#backtest">Details below</a>.')
    if below and not short:
        return f'<div class="answer" id="answer" data-below><p data-ans="bt">{bt}</p></div>' if bt else '<div id="answer" data-below hidden></div>'
    return (f'<div class="answer" id="answer"{" data-below" if below else ""}><p data-ans="today">{today}</p>'
            + (f'<p data-ans="bt">{bt}</p>' if bt else "") + "</div>")


def resource_screen_html(rows: list[dict], cfg: dict) -> str:
    """The resource screen (resource_screen.py): value at spot, value with the metal 20% lower, volume growth, the
    return of a 5-year hold; NAV models on their NAV rules."""
    if not rows:
        return ""
    s = cfg["resource_screen"]

    def p(x, nd=0):
        return "–" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x*100:+.{nd}f}%</span>'

    def row(r):
        ccy = r["price_ccy"]
        tier = {"shortlist": '<span class="pill green">Shortlist</span>', "near miss": '<span class="pill blue">Near miss</span>'}.get(r["tier"], "")
        names = {"value": "value", "stress": f"metal −{s['metal_drop']*100:.0f}%", "growth": "volume growth", "return": "5-yr return"}
        why = [names[m] for m in r["missed"]] if r["tier"] != "shortlist" else []
        notes = ("misses: " + ", ".join(why) if why else "") + (" · " if why and r["guards"] else "") + ", ".join(r["guards"])
        flags = " ".join(f"[{e(f)}]" for f in r["flags"])
        if r["model"] in ("developer", "physical", "leases"):
            value = f"{r['pnav']:.2f}× NAV" if r.get("pnav") is not None else "–"
            stress = growth = ret = "–"
        else:
            value = "–" if r["fair"] is None else f"{money(r['fair'], ccy)}"
            stress = "–" if r["stress_value"] is None else money(r["stress_value"], ccy)
            growth = (f"{p(r['volume_growth'])}<br><small>sales {p(r['sales_growth'])} · {e(r['metal'] or '')} {p(r['metal_growth'])}</small>"
                      if r["volume_growth"] is not None else f"–<br><small>sales {p(r['sales_growth'])}</small>")
            ret = p(r["expected_return"], 1)
        return (f'<tr><td><a href="#c-{e(r["ticker"])}"><b>{e(r["ticker"])}</b></a><br><small>{e(r["name"])}</small>'
                f'{"<br><small class=late>" + flags + "</small>" if flags else ""}</td><td>{tier}</td>'
                f'<td>{money(r["price"], ccy)}</td><td>{value}</td><td>{stress}</td><td>{growth}</td><td>{ret}</td>'
                f'<td><span class="pill {r["signal"]}">{e(short_action(r["action"]))}</span></td><td><small>{e(notes)}</small></td></tr>')

    head = ("<thead><tr><th>Company</th><th>Screen</th><th>Price</th><th>Fair value</th>"
            f"<th>Fair value, metal −{s['metal_drop']*100:.0f}%</th><th>Volume growth a year</th><th>5-yr return a year</th>"
            "<th>Signal</th><th>Why not</th></tr></thead>")
    top = [r for r in rows if r["tier"]]
    rest = [r for r in rows if not r["tier"]]
    n_short = sum(1 for r in rows if r["tier"] == "shortlist")
    rule = (f"<b>Value that survives a lower metal price.</b> A miner's profit follows its metal, so the P/E and growth "
            f"screen is translated: shortlist = price at or below <b>fair value</b> (15x owner earnings at today's spot; 13x "
            f"cash flow for oil), still at or below it with the metal <b>{s['metal_drop']*100:.0f}% lower</b>, <b>volume growth</b> of at "
            f"least {s['min_volume_growth']*100:.0f}% a year (revenue growth over about 3 years with the metal-price change taken "
            f"out – approximate: revenue is in the company's currency and acquisitions count as growth), and at least "
            f"{s['min_return']*100:.0f}% a year over a {s['years']}-year hold with earnings flat at today's spot, sold at fair value. "
            f"Guards: positive owner earnings, AISC ≤ {s['max_cost_ratio']*100:.0f}% of spot where known, current results. "
            f"Near miss: fair value met and one other check short. Developers and physical holders: their NAV rules "
            f"(shortlist at the buy level, near miss up to 1.0× NAV). Share dilution is not checked yet.")
    table = lambda rs: f'<div class="wrap"><table class="sum">{head}<tbody>{"".join(row(r) for r in rs)}</tbody></table></div>'  # noqa: E731
    return (f'<section class="company" id="screen"><h2>Screen – {n_short} shortlisted, {len(top) - n_short} near misses '
            f'of {len(rows)}</h2><p class="notes">{rule}</p>'
            + (table(top) if top else '<p class="notes">No company passes, or nearly passes, today.</p>')
            + (f'<details><summary>All {len(rest)} others</summary>{table(rest)}</details>' if rest else "") + '</section>')


def backtest_data(results: list[dict], cfg: dict, href) -> dict:
    """What assets/screen.js needs to re-pick the backtest with the panel's settings: on each start date every stock
    that could pass (no guard, a P/E, growth over 5 and 3 years, every year profitable) with its figures then and its
    return since; all screened as averages (with and without the cyclicals) – they do not depend on the rules."""
    first = results[0]
    years = cfg[first.get("rules", "growth_screen")]["years"]
    names, links, starts = {}, {}, []
    r5 = lambda x: None if x is None else round(x, 5)  # noqa: E731
    max_pe, min_growth = next(x[4] for x in SLIDERS if x[0] == "pe"), next(x[3] for x in SLIDERS if x[0] == "growth") / 100
    for b in results:
        ret, rows = b["ret"], []
        for r in b["all_rows"]:   # what can pass somewhere within the sliders' ranges
            if (r["guards"] or r["pe"] is None or r["pe"] > max_pe or r["eps_cagr_5y"] is None or r["eps_cagr_3y"] is None
                    or not r["every_year_positive"] or min(r["eps_cagr_5y"], r["eps_cagr_3y"]) < min_growth):
                continue
            names[r["ticker"]], links[r["ticker"]] = r["name"], href(r["ticker"])
            row = {"t": r["ticker"], "price": r["price"], "eps": r["eps"], "pe": r["pe"], "c5": r["eps_cagr_5y"],
                   "c3": r["eps_cagr_3y"], "ret": r5(r[ret]), "lfy": r["last_fy"]}
            if r["nc"]:
                row["nc"] = r["nc"]
            if r["promoters"] is not None:
                row["prom"] = r["promoters"]
            if b["dividends"]:
                row["pr"] = r5(r["price_return"])
            row.update({k: True for k, on in (("so", r.get("state_owned")), ("cyc", r.get("cyclical")),
                                              ("short", r["growth_years"] < years)) if on})
            rows.append(row)
        nocyc = [r[ret] for r in b["all_rows"] if not r.get("cyclical") and r[ret] is not None]
        every = [r[ret] for r in b["all_rows"] if r[ret] is not None]   # everyone: b's own averages may leave out cyclicals
        starts.append({"label": day(b["start"]), "years": b["years"], "n": len(b["all_rows"]),
                       "all": sum(every) / len(every) if every else None, "median": statistics.median(every) if every else None,
                       "n_nocyc": sum(1 for r in b["all_rows"] if not r.get("cyclical")),
                       "all_nocyc": sum(nocyc) / len(nocyc) if nocyc else None,
                       "median_nocyc": statistics.median(nocyc) if nocyc else None, "index": b["index_price"],
                       "note": _skipped_note(b), "rows": rows})
    return {"us": not first["dividends"], "years": years, "names": names, "links": links, "starts": starts}


def _skipped_note(b: dict) -> str:
    """Who was left out on a start date, as plain text."""
    if not b.get("dividends", True):
        left = [f'{len(v)} {k}' for k, v in b["skipped"].items() if v]
        return f'Of today\'s members, left out: {", ".join(left)}.'
    short = (f' {b["short_history"]} stocks had one year too few of EPS then for 5-year growth (the data starts at FY2017): '
             f'growth and the hold were measured over 4 years.' if b["short_history"] else "")
    return f'{len(b["skipped"]["not listed then"])} of today\'s members were not listed then and are left out.{short}'


def state_owned_line(results: list[dict], ret: str) -> str:
    """How the state-owned picks did, from the results: how many of the picks were government-owned and on which start
    dates the best pick was one – an empty string when none was."""
    picks = [r for b in results for r in b["picks"]]
    so = [r for r in picks if r.get("state_owned")]
    if not so:
        return ""
    best = [(b, b["best"]) for b in results if b["best"] and b["best"].get("state_owned")]
    n_dates = sum(1 for b in results if b["picks"])
    winners = len(best) * 2 >= n_dates   # the best pick was state-owned on at least half the start dates
    head = (f'<b>State-owned companies were {"most of " if len(so) * 2 > len(picks) else ""}the winners:</b> ' if winners
            else "<b>State-owned picks:</b> ")
    tops = "; ".join(f'{e(r["ticker"])} {S.pct(r[ret], 0)} since {day(b["start"])}' for b, r in best)
    return (f'<p class="notes bt-default">{head}{len(so)} of the {len(picks)} picks were government-owned'
            + (f', and the best pick was one on {len(best)} of the {n_dates} start dates with picks ({tops})' if best else "")
            + '. Tick <i>Exclude government-owned</i> above to see the rules without them.</p>')


PROMOTER_NOTE = '<p class="notes">Promoter rule not applied before 2025: data not available.</p>'


def backtest_html(results: list[dict], cfg: dict, index_name: str, href=None, panel: bool = False,
                  promoter_note: bool = False) -> str:
    """'How these rules did': the growth screen applied on past dates with only what was known then (backtest.py), with
    a chart of the earliest start with picks. India: returns with dividends (Yahoo's adjusted close); US: price only.
    `href(ticker)` links a pick to its page (None: no link); default the company's section."""
    if not results:
        return ""
    href = href or (lambda t: f"#c-{t}")
    first = results[0]
    us = not first.get("dividends", True)
    s = cfg[first.get("rules", "growth_screen")]
    ret = first.get("ret", "total_return")
    with_what = "price only" if us else "with dividends"

    def p(x, nd=0):
        return "–" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x*100:+.{nd}f}%</span>'

    def a_year(x, years):
        return "" if x is None or years <= 0 or x <= -1 else f"<br><small>{((1 + x) ** (1 / years) - 1)*100:+.1f}% a year</small>"

    def name(r):
        link = href(r["ticker"])
        t = f'<b>{e(r["ticker"])}</b>'
        return (f'<a href="{e(link)}">{t}</a>' if link else t) + f'<br><small>{e(r["name"])}</small>'

    def picks_ret(b):
        return b.get("picks_ret", b.get("picks_total"))

    rows = []
    for b in results:
        best = f'{e(b["best"]["ticker"])} {p(b["best"][ret])}' if b["best"] else "–"
        worst = f'{e(b["worst"]["ticker"])} {p(b["worst"][ret])}' if b["worst"] and len(b["picks"]) > 1 else "–"
        rows.append(f'<tr><td><b>{day(b["start"])}</b><br><small>{b["years"]:.0f} years</small></td>'
                    f'<td>{len(b["picks"])} of {b["screened"]}</td><td>{p(picks_ret(b))}{a_year(picks_ret(b), b["years"])}</td>'
                    f'<td>{p(b.get("all_ret", b.get("all_total")))} · median {p(b.get("all_ret_median", b.get("all_total_median")))}</td>'
                    f'<td>{p(b["index_price"])}</td><td>{best}</td><td>{worst}</td></tr>')
    summary = (f'<div class="wrap"><table class="sum"><thead><tr><th>Since</th><th>Picks</th><th>Picks, {with_what}</th>'
               f'<th>All screened, {with_what} (mean · median)</th><th>{e(index_name)} (price only)</th><th>Best</th><th>Worst</th>'
               f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    details = ""
    for b in results:
        if us:
            body = "".join(
                f'<tr><td>{name(r)}</td><td>{r["pe"]:.1f}<br><small>figures to {e(r["last_fy"])}</small></td>'
                f'<td>{p(r["eps_cagr_5y"])} / {p(r["eps_cagr_3y"])}</td><td>{p(r["expected_return"], 1)}</td>'
                f'<td>{p(r["price_return"])}{a_year(r["price_return"], b["years"])}</td></tr>' for r in b["picks"])
            head = '<th>Pick</th><th>P/E then</th><th>EPS growth then (5 / 3 years)</th><th>Expected then</th><th>Return, price only</th>'
        else:
            body = "".join(
                f'<tr><td>{name(r)}</td><td>{r["pe"]:.1f}<br><small>FY to {e(r["last_fy"])}</small></td>'
                f'<td>{p(r["eps_cagr_5y"])} / {p(r["eps_cagr_3y"])}<br><small>{r["growth_years"]} and 3 years</small></td>'
                f'<td>{p(r["expected_return"], 1)}</td><td>{p(r["total_return"])}{a_year(r["total_return"], b["years"])}</td>'
                f'<td>{p(r["price_return"])}</td></tr>' for r in b["picks"])
            head = ('<th>Pick</th><th>P/E then</th><th>EPS growth then</th><th>Expected then</th><th>Return, with dividends</th>'
                    '<th>Price only</th>')
        table = (f'<div class="wrap"><table class="sum"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
                 if b["picks"] else '<p class="notes">No stock passed the rules on this date.</p>')
        got = (f'{len(b["picks"])} pick{"s" if len(b["picks"]) > 1 else ""}, {p(picks_ret(b))} {with_what}' if b["picks"]
               else "no picks")
        details += (f'<details><summary>Since {day(b["start"])}: {got}</summary>'
                    f'<p class="small">{_skipped_note(b)}</p>{table}</details>')
    rules = (f"P/E ≤ {s['max_pe']:g}, EPS growth ≥ {s['min_eps_cagr']*100:.0f}% over 5 and 3 years, every year profitable, "
             f"≥ {s['min_return']*100:.0f}% expected over the hold")
    if us:
        note = ("<b>How it was done.</b> On each date: today's members (the index then is not in the data), each rebuilt "
                "exactly as filed by that day – only the SEC figures filed on or before it (later restatements ignored), the share "
                "count then, and the price then on the share basis of then (splits both ways) – and the same rules as the screen "
                f"above: {rules}. Foreign filers are left out (their figures are today's). Returns to today: the picks equal-"
                "weighted, price only on both sides – the stored US prices carry no dividends (about 1.5% a year for the "
                f"{e(index_name)}). ")
    else:
        note = ("<b>How it was done.</b> On each date: today's members of the list (the index then is not in the data), the "
                "yearly EPS of the years whose results were out (60 days after March), the price that day, and the same rules as the "
                f"screen above – {rules}. The latest yearly EPS stands in for the last twelve months, there is no "
                "net cash, and cash conversion and bad loans are not checked (not in the data then). Returns to today: the picks equal-"
                "weighted with dividends reinvested; the index is its price only (Yahoo has no total-return index; dividends add about "
                "1–1.5% a year). Demergers are not adjusted in the prices (e.g. Tata Motors). ")
    bias = ("<b>Survivorship bias:</b> today's members are the ones that did well enough to be in the index now, so "
            "every average here – picks and all screened alike – flatters; compare the picks with all screened rather than with "
            "the index. Past performance only, and a handful of picks is a small sample.")
    default = ('<p class="notes"><b>The five rules above, at their defaults,</b> applied on each past date'
               + (' – change them under <i>Change the rules</i> and every date is re-picked' if panel else '') + '.</p>')
    custom = ('<p class="notes bt-custom" hidden><b>With your settings from the panel above:</b> the picks, their averages, '
              'best and worst are redone; all screened and the index stay as they are.'
              + ('' if us else ' The promoter rule applies only where the holding then is in the data (the files keep the last '
                 '8 quarters).') + ' The chart shows the default rules.</p>'
              if panel else "")
    chart = ""
    cv = next((b["curve"] for b in results if b.get("curve")), None)
    if cv:
        with tempfile.TemporaryDirectory() as tmp, charts.resolution(110):
            chart = img(charts.backtest_curve(cv, index_name, not us, Path(tmp) / "backtest.png"),
                        f"Growth of 1 since {day(cv['start'])}: {'picks, ' if cv['n_picks'] else ''}all screened and the {index_name}")
    data = (f'<script type="application/json" id="bt-data">{_js(dict(backtest_data(results, cfg, href), index=index_name))}</script>'
            if panel else "")
    near_table = (PROMOTER_NOTE if promoter_note else "") + ("" if us else state_owned_line(results, ret))
    return (f'<section class="company" id="backtest"><h2>How these rules did</h2>{default}{custom}<div class="bt-summary">{summary}</div>{near_table}'
            f'{chart}<p class="notes">{bias}</p><details class="how"><summary>How the backtest was done</summary>'
            f'<p class="notes">{note}</p></details><div class="bt-details">{details}</div>{data}</section>')


@dataclass
class ReportExtras:
    """The optional parts of a list report: previous-run figures, technicals, ETF look-throughs, the cross-company
    heatmaps, the run log, the interactive price charts and the Markets rows."""
    previous: dict = field(default_factory=dict)
    tech: dict = field(default_factory=dict)
    lookthroughs: list = field(default_factory=list)
    heatmaps: tuple = (None, None)
    log_lines: list = field(default_factory=list)
    price_charts: dict = field(default_factory=dict)
    market_rows: list = field(default_factory=list)
    screen_rows: list = field(default_factory=list)   # the growth screen (lists with `screen: growth` or `us-growth`)
    screen_style: dict = field(default_factory=dict)  # growth_screen_html options: key, owners, tail (the US variant)
    resource_rows: list = field(default_factory=list)  # the resource screen (lists with `screen: resource`)
    hide_spot: bool = False                           # leave the metal spot prices out of the header (list setting)
    backtest: list = field(default_factory=list)      # backtest.run results (list setting `backtest:`), shown after the screen
    index_name: str = ""
    chart_dpi: int | None = None                      # lower for big lists (list setting `chart_dpi`) to keep the page light
    pages: str | None = None                          # multi-page: a summary page plus <pages>/<ticker>.html per company
    buy_zone: list | None = None                      # buy_zone.rows (list setting `buy_zone: true`); None = no section
    decisions: list = field(default_factory=list)     # buy_zone.load_decisions – only `public: true` entries are shown


def build(results: dict, companies: dict, cfg: dict, profit_rows: list[dict], path: Path, title: str,
          extras: ReportExtras | None = None):
    x = extras or ReportExtras()
    previous, tech, lookthroughs, heatmaps, log_lines, price_charts, market_rows = (
        x.previous, x.tech, x.lookthroughs, x.heatmaps, x.log_lines, x.price_charts, x.market_rows)
    key = x.screen_style.get("key", "growth_screen")
    tabbed = bool(x.screen_rows) and key == "growth_screen"   # India growth screen: Dr. Gupta's picks | value vs price | growth
    shown = G.apply_filters(x.screen_rows, cfg[key]) if x.screen_rows else []   # as the page shows them by default
    answer = answer_html(shown, x.backtest, x.index_name, href=x.screen_style.get("href"), below=tabbed)
    style = dict(x.screen_style, after=answer) if tabbed else x.screen_style   # tabbed: the answer under the results
    screen_html = growth_screen_html(x.screen_rows, cfg, **style) + resource_screen_html(x.resource_rows, cfg)
    screen_block = screen_html + "\n" if screen_html else ""   # nothing at all for lists without a screen
    bt_html = backtest_html(x.backtest, cfg, x.index_name, href=x.screen_style.get("href"),
                            panel=bool(x.screen_style.get("panel")),   # under the results table
                            promoter_note=tabbed and any(r["promoters"] is not None for r in x.screen_rows))
    if tabbed:
        answer = ""
    bz_html = ""
    if x.buy_zone is not None:
        from . import buy_zone  # noqa: PLC0415
        answer = buy_zone.answer_line(x.buy_zone) + answer
        bz_html = buy_zone.section_html(x.buy_zone, x.decisions, cfg)
    profit = {p["ticker"]: p for p in profit_rows}
    market_html = markets_html(market_rows or [])
    ordered = sorted(results.values(), key=lambda r: r["display_ticker"])
    tickers = [r["ticker"] for r in ordered]
    sp = cfg["spot"]
    counts = {s: sum(1 for r in ordered if r["signal"] == s) for s in ("green", "blue", "red")}
    grades = {g: sum(1 for t in tickers if profit.get(t, {}).get("grade", "n/m") == g) for g in GRADE_ORDER}
    with tempfile.TemporaryDirectory() as tmp, charts.resolution(x.chart_dpi or HTML_DPI):
        sections = [company_section(r, companies[r["ticker"]], cfg, profit.get(r["ticker"]),
                                    (tickers[i - 1] if i else None, tickers[i + 1] if i + 1 < len(tickers) else None),
                                    Path(tmp), tech.get(r["ticker"]), price_charts.get(r["ticker"])) for i, r in enumerate(ordered)]
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
    growth_rows = [r for r in ordered if r["model"] == "growth"]
    growth_html = growth_table_html(growth_rows, previous) if growth_rows else ""
    pvp_html = (f'<h3 id="pvp">Profit growth vs price growth</h3><p class="notes">{pvp._at_a_glance(profit_rows)}</p>'
                f'<p class="notes">{pvp.HOW_TO_READ}</p>' if profit_rows else "")
    log = "".join(f"<li>{e(x)}</li>" for x in log_lines) or "<li>stored prices</li>"
    charts_js = page.chart_scripts() if (price_charts or market_rows) else ""
    spot_text = ("" if x.hide_spot else   # an India-only list has no use for the metal prices
                 f"spot gold ${sp['gold']:,.0f}, silver ${sp['silver']:.2f}, copper ${sp['copper']:.2f},\nuranium ${sp['uranium']:.2f} · ")
    method = """<details class="method"><summary>How the values are worked out</summary><p class="method"><b>Value vs price.</b> Value comes from the latest reported numbers only (no targets, no forecasts) and is compared
with today's price: owner earnings at today's metal prices × 12 / 15 / 25 + net cash for producers and royalties, NAV for developers
and physical holders, and for growth companies the yearly growth the price needs (5 years, 15x exit, 10% US / 12% India).
<b>Profit vs price.</b> Growth in profit and in the share price over about three years; the grade says whether the P/E fell
(A ≤ −25%, B ≤ 0) or rose (C ≤ +33%, D above). Click a ticker for the full working; click a column to sort.</p></details>"""
    links = "".join(f' · <a href="#{k}">{t}</a>' for k, t, on in (("buyzone", "Buy zone", bz_html), ("screen", "Screen", screen_html),
                                                                  ("backtest", "Backtest", bt_html), ("markets", "Markets", market_html),
                                                                  ("heatmaps", "Heatmaps", heat_html)) if on)
    toc_nav = f'<nav class="toc">Companies: {toc}{links}</nav>'
    signals = (f'<span class="pos">{counts["green"]} green</span>, {counts["blue"]} blue, <span class="neg">{counts["red"]} red</span>'
               f'\n· grades {" · ".join(f"{g} {n}" for g, n in grades.items() if n)}')
    table = f"""<div class="controls">
<span class="lab">Signal</span><button class="on" data-sig="all">All</button><button data-sig="green">Green</button>
<button data-sig="blue">Blue</button><button data-sig="red">Red</button>
<span class="lab">Grade</span><button class="on" data-grd="all">All</button>{''.join(f'<button data-grd="{g}">{g}</button>' for g in GRADE_ORDER)}
<input id="q" type="search" placeholder="Search ticker or name"><span class="lab" id="count"></span></div>
{legend_html(ordered)}
<div class="wrap"><table class="sum" id="sum"><thead>{SUMMARY_HEAD}</thead><tbody>
{''.join(summary_row(r, profit.get(r['ticker']), previous, cfg) for r in ordered)}</tbody></table></div>
<p class="notes">{RULES_NOTE}</p>"""
    if tabbed:   # three tabs (report.js shows one; without JavaScript they stack): the screen is Dr. Gupta's, the rest ours
        growth_tab = growth_table_html(growth_rows, previous, heading=False) if growth_rows else ""
        n_short = sum(1 for r in shown if r["tier"] == "shortlist")   # screen.js keeps the count in step with the panel
        name = e(x.screen_style.get("title") or "Dr. Gupta's screen")   # list setting `screen_title` (Nifty 50: its own rules)
        tabs = ([("picks", f"{name} · <span data-tab-count>{n_short}</span>"), ("values", "Value vs price")]
                + ([("growth", "Growth priced in")] if growth_tab else []))
        tab_links = "".join(f'<a href="#{k}"{" class=on" if i == 0 else ""}>{t}</a>' for i, (k, t) in enumerate(tabs))
        main_part = f"""<nav class="tabs">{tab_links}</nav>
<div class="tabpane" id="picks">
{bz_html}{screen_block}{bt_html}
</div>
<div class="tabpane" id="values">
<p class="sub">{signals}</p>
{method}
<details class="toc"><summary>Companies ({len(ordered)}) and section links</summary>{toc_nav}</details>
{table}
{pvp_html}
</div>
{f'<div class="tabpane" id="growth"><p class="sub">{GROWTH_INTRO}</p>{growth_tab}</div>' if growth_tab else ''}"""
        head = f"""<h1 id="summary">{e(title)}</h1>
<p class="sub">{len(ordered)} companies · run {day(cfg['as_of'])}{(' · ' + spot_text.rstrip(' ·')) if spot_text else ''}</p>
{answer}"""
        doc_title = f"{e(title)} – value screen"
    else:
        main_part = f"""{bz_html}{screen_block}{toc_nav}
{table}
{bt_html}
{pvp_html}
{growth_html}"""
        head = f"""<h1 id="summary">{e(title)} – value vs price</h1>
<p class="sub">{len(ordered)} companies · run {day(cfg['as_of'])} · {spot_text}{signals}</p>
{answer}
{method}"""
        doc_title = f"{e(title)} – value vs price"
    body = f"""
{head}
{main_part}
{market_html}{'' if x.pages else ''.join(sections)}{etf_html}{'' if x.pages else heat_html}
<section class="company"><h2>Run log</h2><ul class="small">{log}</ul></section>
<footer>Previous run's figures in (brackets). Prices in each exchange's currency;
sales and profits as the company reports them.</footer>
"""
    if x.pages:
        return write_pages(path, x.pages, title, body, sections, ordered, bool(price_charts or market_rows), heat_html, doc_title)
    html = page.document(doc_title, page.report_css(), body,
                         scripts=f"<script>{page.asset('report.js')}</script>{charts_js}")
    path.write_text(html, encoding="utf-8")
    return path


COMPANY_LINK = re.compile(r'href="#c-([^"]+)"')
PAGE_FOOTER = "<footer>Prices in each exchange's currency; sales and profits as the company reports them.</footer>"


def write_pages(path: Path, pages: str, title: str, body: str, sections: list[str], ordered: list[dict], charts_on: bool,
                heat_html: str = "", doc_title: str | None = None) -> Path:
    """Multi-page report: `path` is the summary page (no company sections; its company links go to <pages>/<ticker>.html),
    and each company gets its own page with the same section, linking back to the summary and to its neighbours. The
    styles and scripts go to assets/ next to the summary page, loaded once and shared by every page, and the
    cross-company heatmaps get a page of their own (<pages>/heatmaps.html). A copy of the summary page is also written
    as <pages>.html, the name the company pages link back to."""
    import shutil  # noqa: PLC0415
    folder = path.parent
    page.write_shared(folder / "assets")
    body = COMPANY_LINK.sub(lambda m: f'href="{pages}/{m.group(1)}.html"', body).replace('href="#heatmaps"', f'href="{pages}/heatmaps.html"')
    summary = page.document(doc_title or f"{e(title)} – value vs price", "", body,
                            scripts=page.shared_scripts("assets/", charts=charts_on, table=True), head=page.shared_style("assets/"))
    path.write_text(summary, encoding="utf-8")
    if path.name != f"{pages}.html":
        (folder / f"{pages}.html").write_text(summary, encoding="utf-8")
    company_dir = folder / pages
    if company_dir.exists():
        shutil.rmtree(company_dir)   # companies that left the list must not linger
    company_dir.mkdir(parents=True)
    for r, section in zip(ordered, sections):
        section = section.replace('href="#summary"', f'href="../{pages}.html#summary"')
        section = COMPANY_LINK.sub(lambda m: f'href="{m.group(1)}.html"', section)
        html = page.document(f"{e(r['display_ticker'])} – {e(r['name'])} · {e(title)}", "", f"\n{section}\n{PAGE_FOOTER}\n",
                             scripts=page.shared_scripts("../assets/", charts=charts_on), head=page.shared_style("../assets/"))
        (company_dir / f"{r['ticker']}.html").write_text(html, encoding="utf-8")
    if heat_html:   # the cross-company heatmaps are big with 150 companies: a page of their own
        back = f'<nav class="crumbs"><a href="../{pages}.html#summary">↑ Summary</a></nav>'
        (company_dir / "heatmaps.html").write_text(page.document(f"Scenario heatmaps · {e(title)}", "", f"\n{back}\n{heat_html}\n{PAGE_FOOTER}\n",
                                                                 head=page.shared_style("../assets/")), encoding="utf-8")
    return path


def file_name(list_name: str | None, as_of) -> str:
    return f"{list_title(list_name).replace(' ', '_')}_Value_vs_Price_{as_of:%d%b%Y}.html"
