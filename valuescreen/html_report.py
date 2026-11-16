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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import charts, kinds, page, price_chart
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
<div class="grid2"><div>{img(curve, 'curve')}</div><div><h3>Key figures</h3>{_key_figures(r)}</div></div>
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
{''.join(f'<button data-rg="{x}">{x}</button>' for x in ('6M', '1Y', '3Y', '5Y', '10Y') + (('Max',) if p.get('mode') == 'research' else ()))}<span class="sep"></span>
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


def growth_table_html(rows, previous) -> str:
    """Growth companies: value with no growth, at 10% and 20% a year, the growth the price needs, and quality."""
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
    return (f'<h3 id="growth">Growth companies – reverse DCF</h3><div class="wrap"><table class="sum gt"><thead><tr>'
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


def growth_screen_html(rows: list[dict], cfg: dict) -> str:
    """The growth-at-a-value-price screen (growth_screen.py): shortlist and near misses, then everyone else folded away."""
    if not rows:
        return ""
    s = cfg["growth_screen"]

    def p(x, nd=0):
        return "–" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x*100:+.{nd}f}%</span>'

    def row(r):
        tier = {"shortlist": '<span class="pill green">Shortlist</span>', "near miss": '<span class="pill blue">Near miss</span>'}.get(r["tier"], "")
        why = [{"pe": "P/E", "growth": "growth", "return": "5-yr return"}[m] for m in r["missed"]] if r["tier"] != "shortlist" else []
        notes = ("misses: " + ", ".join(why) if why else "") + (" · " if why and r["guards"] else "") + ", ".join(r["guards"])
        flags = " ".join(f"[{e(f)}]" for f in r["flags"])
        pe = "–" if r["pe"] is None else f"{r['pe']:.1f}"
        trailing = "" if r["pe_trailing"] is None else f"<br><small>trailing {r['pe_trailing']:.1f}</small>"
        assumed = "" if r["assumed_growth"] is None else f"<br><small>at {r['assumed_growth']*100:.0f}%/yr growth</small>"
        prom = "–" if r["promoters"] is None else f"{r['promoters']*100:.0f}%"
        return (f'<tr><td><a href="#c-{e(r["ticker"])}"><b>{e(r["ticker"])}</b></a><br><small>{e(r["name"])}</small>'
                f'{"<br><small class=late>" + flags + "</small>" if flags else ""}</td><td>{tier}</td>'
                f'<td data-v="{_num(r["pe"])}">{pe}{trailing}</td><td>{p(r["eps_cagr_5y"])} / {p(r["eps_cagr_3y"])}'
                f'{"" if r["every_year_positive"] else "<br><small class=neg>a loss year</small>"}</td>'
                f'<td>{p(r["growth_needed"], 1)}</td><td>{p(r["expected_return"], 1)}{assumed}</td><td>{prom}</td>'
                f'<td><span class="pill {r["signal"]}">{e(short_action(r["action"]))}</span></td><td><small>{e(notes)}</small></td></tr>')

    head = ("<thead><tr><th>Company</th><th>Screen</th><th>P/E</th><th>EPS growth 5 / 3 yrs</th><th>Price needs</th>"
            "<th>5-yr return a year</th><th>Promoters</th><th>Signal</th><th>Why not</th></tr></thead>")
    top = [r for r in rows if r["tier"]]
    rest = [r for r in rows if not r["tier"]]
    n_short = sum(1 for r in rows if r["tier"] == "shortlist")
    rule = (f"<b>Growth at a value price.</b> Shortlist: P/E ≤ {s['max_pe']:g} (price minus net cash ÷ the EPS the "
            f"valuation uses), EPS growth ≥ {s['min_eps_cagr']*100:.0f}% a year over both 5 and 3 years with every year "
            f"profitable, and at least {s['min_return']*100:.0f}% a year expected over a {s['years']}-year hold (growth at "
            f"half the past rate, at most {s['max_assumed_growth']*100:.0f}%, sold at {s['exit_multiple']:g}x). Guards: cash "
            f"conversion ≥ {s['min_cash_conversion']*100:.0f}%, no demerger or one-off history, no bad-loan warning, current "
            f"results. Near miss: one thing short – a P/E of {s['max_pe']:g}–{s['near_max_pe']:g} (growth met), growth of "
            f"{s['near_min_eps_cagr']*100:.0f}–{s['min_eps_cagr']*100:.0f}% (P/E met), or only the return bar. Flags: promoters below "
            f"{s['min_promoter']*100:.0f}% or falling; pledged shares are not in the data yet. Dividends are not counted.")
    table = lambda rs: f'<div class="wrap"><table class="sum">{head}<tbody>{"".join(row(r) for r in rs)}</tbody></table></div>'  # noqa: E731
    return (f'<section class="company" id="screen"><h2>Screen – {n_short} shortlisted, {len(top) - n_short} near misses '
            f'of {len(rows)}</h2><p class="notes">{rule}</p>'
            + (table(top) if top else '<p class="notes">No company passes, or nearly passes, today.</p>')
            + f'<details><summary>All {len(rest)} others</summary>{table(rest)}</details></section>')


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
    screen_rows: list = field(default_factory=list)   # the growth screen (lists with `screen: growth`)
    chart_dpi: int | None = None                      # lower for big lists (list setting `chart_dpi`) to keep the page light
    pages: str | None = None                          # multi-page: a summary page plus <pages>/<ticker>.html per company


def build(results: dict, companies: dict, cfg: dict, profit_rows: list[dict], path: Path, title: str,
          extras: ReportExtras | None = None):
    x = extras or ReportExtras()
    previous, tech, lookthroughs, heatmaps, log_lines, price_charts, market_rows = (
        x.previous, x.tech, x.lookthroughs, x.heatmaps, x.log_lines, x.price_charts, x.market_rows)
    screen_html = growth_screen_html(x.screen_rows, cfg)
    screen_block = screen_html + "\n" if screen_html else ""   # nothing at all for lists without a screen
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
    body = f"""
<h1 id="summary">{e(title)} – value vs price</h1>
<p class="sub">{len(ordered)} companies · run {day(cfg['as_of'])} · spot gold ${sp['gold']:,.0f}, silver ${sp['silver']:.2f}, copper ${sp['copper']:.2f},
uranium ${sp['uranium']:.2f} · <span class="pos">{counts['green']} green</span>, {counts['blue']} blue, <span class="neg">{counts['red']} red</span>
· grades {' · '.join(f'{g} {n}' for g, n in grades.items() if n)}</p>
<p class="method"><b>Value vs price.</b> Value comes from the latest reported numbers only (no targets, no forecasts) and is compared
with today's price: owner earnings at today's metal prices × 12 / 15 / 25 + net cash for producers and royalties, NAV for developers
and physical holders, and for growth companies the yearly growth the price needs (5 years, 15x exit, 10% US / 12% India).
<b>Profit vs price.</b> Growth in profit and in the share price over about three years; the grade says whether the P/E fell
(A ≤ −25%, B ≤ 0) or rose (C ≤ +33%, D above). Click a ticker for the full working; click a column to sort.</p>
{screen_block}<nav class="toc">Companies: {toc}{' · <a href="#screen">Screen</a>' if screen_html else ''}{' · <a href="#markets">Markets</a>' if market_html else ''}{' · <a href="#heatmaps">Heatmaps</a>' if heat_html else ''}</nav>
<div class="controls">
<span class="lab">Signal</span><button class="on" data-sig="all">All</button><button data-sig="green">Green</button>
<button data-sig="blue">Blue</button><button data-sig="red">Red</button>
<span class="lab">Grade</span><button class="on" data-grd="all">All</button>{''.join(f'<button data-grd="{g}">{g}</button>' for g in GRADE_ORDER)}
<input id="q" type="search" placeholder="Search ticker or name"><span class="lab" id="count"></span></div>
{legend_html(ordered)}
<div class="wrap"><table class="sum" id="sum"><thead>{SUMMARY_HEAD}</thead><tbody>
{''.join(summary_row(r, profit.get(r['ticker']), previous, cfg) for r in ordered)}</tbody></table></div>
<p class="notes">{RULES_NOTE}</p>
{pvp_html}
{growth_html}
{market_html}{'' if x.pages else ''.join(sections)}{etf_html}{'' if x.pages else heat_html}
<section class="company"><h2>Run log</h2><ul class="small">{log}</ul></section>
<footer>Educational framework, not investment advice. Previous run's figures in (brackets). Prices in each exchange's currency;
sales and profits as the company reports them.</footer>
"""
    if x.pages:
        return write_pages(path, x.pages, title, body, sections, ordered, bool(price_charts or market_rows), heat_html)
    html = page.document(f"{e(title)} – value vs price", page.report_css(), body,
                         scripts=f"<script>{page.asset('report.js')}</script>{charts_js}")
    path.write_text(html, encoding="utf-8")
    return path


COMPANY_LINK = re.compile(r'href="#c-([^"]+)"')
PAGE_FOOTER = "<footer>Educational framework, not investment advice. Prices in each exchange's currency; sales and profits as the company reports them.</footer>"


def write_pages(path: Path, pages: str, title: str, body: str, sections: list[str], ordered: list[dict], charts_on: bool,
                heat_html: str = "") -> Path:
    """Multi-page report: `path` is the summary page (no company sections; its company links go to <pages>/<ticker>.html),
    and each company gets its own page with the same section, linking back to the summary and to its neighbours. The
    styles and scripts go to assets/ next to the summary page, loaded once and shared by every page, and the
    cross-company heatmaps get a page of their own (<pages>/heatmaps.html). A copy of the summary page is also written
    as <pages>.html, the name the company pages link back to."""
    import shutil  # noqa: PLC0415
    folder = path.parent
    page.write_shared(folder / "assets")
    body = COMPANY_LINK.sub(lambda m: f'href="{pages}/{m.group(1)}.html"', body).replace('href="#heatmaps"', f'href="{pages}/heatmaps.html"')
    summary = page.document(f"{e(title)} – value vs price", "", body,
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
