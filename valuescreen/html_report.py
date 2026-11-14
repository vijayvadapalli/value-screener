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
import json
import html
import re
import tempfile
from pathlib import Path

from . import charts, price_chart
from . import profit_vs_price as pvp
from . import style as S
from .wording import (GROWTH_NOTE, RULES_NOTE, list_title, MODEL_LABEL, calc_steps, day, headline, key_figures, kpi_cards, money, npa_summary, price_date,
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
td.sig{{width:1%}} .hastip{{position:relative;cursor:help;outline:none}}
.tip{{display:none;position:absolute;z-index:20;left:0;top:calc(100% + 6px);width:340px;max-width:80vw;white-space:normal;
background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:9px 11px;font-size:12.5px;
font-weight:400;line-height:1.45;box-shadow:0 4px 16px rgba(0,0,0,.18)}} .tip>span{{display:block;margin:0 0 5px}} .tip>span:last-child{{margin:0}}
.hastip:hover .tip,.hastip:focus .tip{{display:block}}
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
table.mk{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}} table.mk th,table.mk td{{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right}}
table.mk th:nth-child(-n+2),table.mk td:nth-child(-n+2){{text-align:left}} table.mk th{{font-weight:600;color:var(--ink2,inherit)}}
ol{{padding-left:20px;margin:6px 0}} ol li{{margin:3px 0}}
.pvp{{display:flex;gap:18px;align-items:flex-start}} .pvp>div:last-child{{flex:1}} .pvp p{{margin:0 0 6px}}
.bigrade{{font-size:44px;font-weight:700;line-height:1;min-width:56px;text-align:center}}
footer{{color:var(--muted);font-size:12px;margin-top:40px}}
table.gt th{{cursor:default}} table.gt th:after{{content:none}}
.legend{{display:flex;flex-wrap:wrap;gap:5px;margin:10px 0 4px}} .chip{{font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:3px}}
.notes{{font-size:12.5px;color:var(--ink2);max-width:1100px;margin:6px 0}}
.pc{{margin:12px 0 4px;border:1px solid var(--line);border-radius:6px;padding:8px 8px 4px}}
.pc-bar{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12px;margin-bottom:4px}}
.pc-bar button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:12px;padding:2px 9px;cursor:pointer;font:inherit}}
.pc-bar button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}} .pc-bar .sep{{width:8px}}
.pc-legend{{color:var(--ink2);margin-left:auto;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pc-main{{height:380px}} .pc-rsi{{height:90px;margin-bottom:2px}}
.pc-key{{font-size:11.5px;color:var(--muted);margin:4px 2px 2px;display:flex;flex-wrap:wrap;gap:4px 14px}}
.pc-key i{{display:inline-block;width:16px;height:0;border-top:2px solid;vertical-align:middle;margin-right:4px}}
.pc-cap{{font-size:12.5px;color:var(--ink2);margin:2px 2px 4px}}
@media (max-width:640px){{.pc-main{{height:300px}} .pc-legend{{margin-left:0;width:100%}}}}
"""

VENDOR = Path(__file__).parent / "vendor" / "lightweight-charts.standalone.production.js"
CHART_JS = r"""
const PC_SMA = window.PC_SMA_COLOURS;
const PC_RANGE = {'6M': 0.5, '1Y': 1, '3Y': 3, '5Y': 5, '10Y': 10, 'Max': 100};
const PC_AUTO_IV = {'6M': 'D', '1Y': 'D', '3Y': 'W', '5Y': 'W', '10Y': 'M', 'Max': 'M'};
function pcColours() {
  const cs = getComputedStyle(document.documentElement), v = n => cs.getPropertyValue(n).trim();
  return {bg: v('--bg') || '#fff', ink: v('--ink2') || '#444', muted: v('--muted') || '#888', line: v('--line') || '#eee',
          green: v('--green'), red: v('--red'), blue: v('--blue'), price: v('--price')};
}
function pcSma(c, n) { const o = []; let s = 0; c.forEach((x, i) => { s += x; if (i >= n) s -= c[i - n]; o.push(i >= n - 1 ? s / n : null); }); return o; }
function pcRsi(c, n = 14) {
  const o = c.map(() => null); if (c.length <= n) return o;
  let ag = 0, al = 0;
  for (let i = 1; i <= n; i++) { const d = c[i] - c[i - 1]; ag += Math.max(d, 0); al += Math.max(-d, 0); }
  ag /= n; al /= n; o[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = n + 1; i < c.length; i++) { const d = c[i] - c[i - 1];
    ag = (ag * (n - 1) + Math.max(d, 0)) / n; al = (al * (n - 1) + Math.max(-d, 0)) / n; o[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al); }
  return o;
}
const pcDays = s => Date.parse(s) / 864e5;
function pcInit(box) {
  if (box.dataset.ready) return; box.dataset.ready = 1;
  const d = JSON.parse(document.getElementById(box.dataset.pc).textContent), col = pcColours(), LC = LightweightCharts;
  const base0 = d.D.length ? d.D : d.M, last = base0[base0.length - 1][4], prec = last < 1 ? 4 : last < 10 ? 3 : 2;
  const base = {autoSize: true, layout: {background: {type: 'solid', color: col.bg}, textColor: col.ink, fontSize: 11,
                fontFamily: 'Inter, -apple-system, system-ui, sans-serif'},
                grid: {vertLines: {color: col.line}, horzLines: {color: col.line}}, rightPriceScale: {borderColor: col.line, minimumWidth: 74},
                crosshair: {mode: 0}};
  const main = LC.createChart(box.querySelector('.pc-main'), {...base, timeScale: {borderColor: col.line}});
  const osc = LC.createChart(box.querySelector('.pc-rsi'), {...base, layout: {...base.layout, attributionLogo: false}, timeScale: {visible: false, borderColor: col.line}});
  const candle = main.addCandlestickSeries({upColor: col.green, downColor: col.red, borderVisible: false, wickUpColor: col.green,
    wickDownColor: col.red, priceLineColor: col.price, priceFormat: {type: 'price', precision: prec, minMove: 1 / 10 ** prec}});
  candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.06}});
  let vol = null;   // volume: off by default, the Volume button adds it
  const volData = () => rows.map(r => ({time: r[0], value: r[5], color: r[4] >= r[1] ? col.green + '66' : col.red + '66'}));
  const toggleVol = () => { const b = box.querySelector('[data-vol]');
    if (vol) { main.removeSeries(vol); vol = null; candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.06}}); }
    else { vol = main.addHistogramSeries({priceScaleId: 'vol', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
           main.priceScale('vol').applyOptions({scaleMargins: {top: 0.84, bottom: 0}}); vol.setData(volData());
           candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.2}}); }
    if (b) b.classList.toggle('on', !!vol); };
  const quiet = {priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false};
  const noScale = {autoscaleInfoProvider: () => null};   // averages and trend lines never stretch the price scale
  const avgLine = main.addLineSeries({color: col.ink, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
  const isAvg = r => r[5] === 0 && r[1] === r[2] && r[2] === r[3];   // a monthly average (long-term series), not a real bar
  const smaWidth = {20: 1, 50: 2, 200: 3};
  const smas = {}; for (const n in PC_SMA) smas[n] = main.addLineSeries({color: PC_SMA[n], lineWidth: smaWidth[n] || 1, ...quiet, ...noScale});
  const trends = d.trends.map(t => [t, main.addLineSeries({color: t.kind === 'resistance' ? '#B794F4' : '#4299E1', lineWidth: 2, ...quiet, ...noScale})]);
  const research = d.mode === 'research';
  // chart patterns drawn in the report (cup & handle, rounding bottoms): shown on their own timeframe, Patterns button
  const patCol = {cup: '#2F855A', handle: '#38A169', rim: '#22543D'};
  const pats = (d.patterns || []).map(p => [p, main.addLineSeries({color: patCol[p.kind] || '#2F855A', lineWidth: p.kind === 'rim' ? 2 : 3,
    lineStyle: p.kind === 'rim' ? LC.LineStyle.Dashed : LC.LineStyle.Solid, ...quiet, ...noScale})]);
  let showPats = true;
  const drawPatterns = () => pats.forEach(([p, s]) => {
    if (!showPats || p.tf !== iv) { s.setData([]); return; }
    const seen = new Set(), pts = [];
    p.points.forEach(([date, v]) => { const i = snap(date); if (i < 0 || seen.has(i)) return; seen.add(i); pts.push({time: rows[i][0], value: v}); });
    s.setData(pts); });   // private report: clean by default – their levels on, averages and trend lines behind a button
  const setOverlays = on => { for (const n in smas) smas[n].applyOptions({visible: on});
    trends.forEach(([, s]) => s.applyOptions({visible: on})); btn('data-ma')?.classList.toggle('on', on); };
  // buttons, all off at first: support / resistance (nearest), every level, and our value lines
  const nearest = ['support', 'resistance'].map(k => d.levels.find(l => l.kind === k)).filter(Boolean);
  let levelLines = [], valueLines = [], showValues = false, watchedLines = [], showWatched = false;
  const watchedPrices = (d.watched || []).flatMap(w => [w.lo, w.hi]);
  const btn = k => box.querySelector(`[${k}]`);
  const drawLevels = mode => {   // mode: '' (off), 'near', 'all'
    levelLines.forEach(x => candle.removePriceLine(x));
    levelLines = (mode === 'all' ? d.levels : mode === 'near' ? nearest : []).map(l => candle.createPriceLine({price: l.price,
      color: l.kind === 'support' ? col.green : col.red, lineWidth: 2, lineStyle: LC.LineStyle.Solid, axisLabelVisible: true,
      title: l.kind === 'support' ? 'Support' : 'Resistance'}));
    btn('data-sr')?.classList.toggle('on', mode === 'near'); btn('data-lv')?.classList.toggle('on', mode === 'all'); };
  btn('data-sr').onclick = () => drawLevels(btn('data-sr').classList.contains('on') ? '' : 'near');
  btn('data-lv').onclick = () => drawLevels(btn('data-lv').classList.contains('on') ? '' : 'all');
  if (!d.levels.length) { btn('data-sr').style.display = 'none'; btn('data-lv').style.display = 'none'; }
  else if (d.levels.length <= nearest.length) btn('data-lv').style.display = 'none';
  // value lines: shown on request, thick, and the price scale stretches so every one (25x too) is in view
  const valuePrices = d.values.map(v => v.price);
  candle.applyOptions({autoscaleInfoProvider: original => { const r = original();
    const tfPrices = (d.watched || []).filter(w => (({D: ['D', 'W'], W: ['D', 'W'], M: ['M']})[iv] || []).includes(w.tf || 'D')).flatMap(w => [w.lo, w.hi]);
    const extra = [...(showValues ? valuePrices : []), ...(showWatched ? tfPrices : [])];
    if (!r || !extra.length) return r;
    return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...extra) * 0.97,
                               maxValue: Math.max(r.priceRange.maxValue, ...extra) * 1.03}}; }});
  const toggleValues = () => { showValues = !showValues;
    valueLines.forEach(x => candle.removePriceLine(x));
    valueLines = showValues ? d.values.map(v => candle.createPriceLine({price: v.price, color: v.color, lineWidth: 3,
      lineStyle: v.solid ? LC.LineStyle.Solid : LC.LineStyle.Dashed, axisLabelVisible: true, title: v.label})) : [];
    btn('data-val').classList.toggle('on', showValues); main.timeScale().applyOptions({}); candle.applyOptions({}); };
  if (d.values.length) btn('data-val').onclick = toggleValues; else btn('data-val').style.display = 'none';
  // levels someone else is watching (plain support / resistance, zones as two lines): off at first
  const WATCH_TF = {D: ['D', 'W'], W: ['D', 'W'], M: ['M']};   // each chart shows the levels drawn on that timeframe
  const drawWatched = () => { watchedLines.forEach(x => candle.removePriceLine(x));
    const shown = (d.watched || []).filter(w => (WATCH_TF[iv] || []).includes(w.tf || 'D'));
    watchedLines = showWatched ? shown.flatMap(w => {
      const c = research ? (w.kind === 'support' ? '#1E6B3A' : '#9B2C2C') : (w.kind === 'support' ? '#2C9C94' : '#DD6B20');
      const t = w.kind === 'support' ? 'support' : 'resistance';
      return (w.hi - w.lo > 1e-9 ? [w.lo, w.hi] : [w.lo]).map(p => candle.createPriceLine({price: p, color: c, lineWidth: research ? 2 : 2,
        lineStyle: research ? LC.LineStyle.Solid : LC.LineStyle.LargeDashed, axisLabelVisible: true, title: t})); }) : [];
    candle.applyOptions({}); };
  const toggleWatched = () => { showWatched = !showWatched; btn('data-wl').classList.toggle('on', showWatched); drawWatched(); };
  if (watchedPrices.length) btn('data-wl').onclick = toggleWatched; else btn('data-wl').style.display = 'none';
  const rsi = osc.addLineSeries({color: col.blue, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
    autoscaleInfoProvider: () => ({priceRange: {minValue: 0, maxValue: 100}})});
  osc.applyOptions({watermark: {visible: true, text: 'RSI(14)', fontSize: 11, color: col.muted, horzAlign: 'left', vertAlign: 'top'}});
  rsi.createPriceLine({price: 70, color: col.red, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: false, title: '70'});
  rsi.createPriceLine({price: 30, color: col.green, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: false, title: '30'});
  let syncing = false;
  const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange(r => { if (!r || syncing) return; syncing = true;
    b.timeScale().setVisibleLogicalRange(r); syncing = false; });
  link(main, osc); link(osc, main);
  const legend = box.querySelector('.pc-legend'), fmt = x => x == null ? '–' : x.toLocaleString(undefined, {maximumFractionDigits: prec});
  const vfmt = x => x >= 1e9 ? (x / 1e9).toFixed(2) + 'B' : x >= 1e6 ? (x / 1e6).toFixed(2) + 'M' : x >= 1e3 ? (x / 1e3).toFixed(0) + 'K' : x;
  let rows = [], iv = 'D', range = '1Y';
  const show = r => { if (!r) return; const i = rows.findIndex(x => x[0] === r[0]), prev = i > 0 ? rows[i - 1][4] : r[1];
    const ch = (r[4] / prev - 1) * 100;
    legend.innerHTML = `<b>${r[0]}</b> O <b>${fmt(r[1])}</b> H <b>${fmt(r[2])}</b> L <b>${fmt(r[3])}</b> C <b>${fmt(r[4])}</b> ` +
      `<span class="${ch >= 0 ? 'pos' : 'neg'}">${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%</span> Vol <b>${vfmt(r[5])}</b>`; };
  main.subscribeCrosshairMove(p => { const b = p.time ? rows.find(x => x[0] === p.time) : null; show(b || rows[rows.length - 1]); });
  const snap = date => { const i = rows.findIndex(x => x[0] >= date); return i < 0 ? -1 : i; };
  function setIv(next) {
    iv = next; rows = d[iv]; const c = rows.map(r => r[4]);
    candle.setData(rows.map(r => isAvg(r) ? {time: r[0]} : {time: r[0], open: r[1], high: r[2], low: r[3], close: r[4]}));
    const avg = rows.map((r, i) => isAvg(r) || (i > 0 && isAvg(rows[i - 1])) ? {time: r[0], value: r[4]} : {time: r[0]});
    avgLine.setData(avg);
    for (const n in PC_SMA) { const s = pcSma(c, +n); smas[n].setData(rows.map((r, i) => s[i] == null ? {time: r[0]} : {time: r[0], value: s[i]})); }
    if (vol) vol.setData(volData());
    const rs = pcRsi(c); rsi.setData(rows.map((r, i) => rs[i] == null ? {time: r[0]} : {time: r[0], value: rs[i]}));
    trends.forEach(([t, s]) => { const i0 = snap(t.from[0]), i1 = rows.length - 1;
      if (i0 < 0 || i0 >= i1) { s.setData([]); return; }
      const slope = (t.to[1] - t.from[1]) / Math.max(pcDays(t.to[0]) - pcDays(t.from[0]), 1);
      const at = date => t.from[1] + slope * (pcDays(date) - pcDays(t.from[0]));
      s.setData([{time: rows[i0][0], value: at(rows[i0][0])}, {time: rows[i1][0], value: at(rows[i1][0])}]); });
    const seen = new Set(), marks = [];
    d.markers.forEach(m => { const i = snap(m.date); if (i < 0) return; const key = rows[i][0] + m.kind; if (seen.has(key)) return; seen.add(key);
      marks.push({time: rows[i][0], position: m.kind === 'E' ? 'aboveBar' : 'belowBar', shape: m.kind === 'E' ? 'square' : 'circle',
                  color: m.kind === 'E' ? col.blue : m.kind === 'S' ? col.red : col.muted, text: m.kind}); });
    candle.setMarkers(marks.sort((a, b) => a.time < b.time ? -1 : 1));
    box.querySelectorAll('[data-iv]').forEach(b => b.classList.toggle('on', b.dataset.iv === iv));
    candle.priceScale().applyOptions({mode: iv === 'M' ? 1 : 0});   // monthly = log scale, like long-term charts
    if (showWatched) drawWatched();
    drawPatterns();
    show(rows[rows.length - 1]);
  }
  function setRange(next) {
    range = next; const end = rows[rows.length - 1][0], from = new Date(Date.parse(end) - PC_RANGE[range] * 365.25 * 864e5).toISOString().slice(0, 10);
    if (from <= rows[0][0]) main.timeScale().fitContent(); else main.timeScale().setVisibleRange({from, to: end});
    box.querySelectorAll('[data-rg]').forEach(b => b.classList.toggle('on', b.dataset.rg === range));
  }
  box.querySelectorAll('[data-iv]').forEach(b => b.onclick = () => { setIv(b.dataset.iv); setRange(range); });
  box.querySelectorAll('[data-rg]').forEach(b => b.onclick = () => { if (PC_AUTO_IV[b.dataset.rg] !== iv) setIv(PC_AUTO_IV[b.dataset.rg]); setRange(b.dataset.rg); });
  const vb = box.querySelector('[data-vol]'); if (vb) vb.onclick = toggleVol;
  const mab = btn('data-ma'); if (mab) mab.onclick = () => setOverlays(!mab.classList.contains('on'));
  const pb = btn('data-pat');
  if (pb) { if (!pats.length) pb.style.display = 'none'; else { pb.classList.add('on');
    pb.onclick = () => { showPats = !showPats; pb.classList.toggle('on', showPats); drawPatterns(); }; } }
  if (!d.D.length) { box.querySelectorAll('[data-iv=D],[data-iv=W],[data-rg="6M"],[data-rg="1Y"],[data-rg="3Y"]').forEach(b => b.style.display = 'none');
    setIv('M'); setRange('Max'); } else { setIv('D'); setRange('1Y'); }
  if (research) { setOverlays(false); if (watchedPrices.length) toggleWatched(); } else if (mab) mab.style.display = 'none';
}
if (window.LightweightCharts) {
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { pcInit(x.target); io.unobserve(x.target); } }),
                                                                           {rootMargin: '300px'}) : null;
  document.querySelectorAll('.pc').forEach(b => io ? io.observe(b) : pcInit(b));
}
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


def build(results: dict, companies: dict, cfg: dict, profit_rows: list[dict], path: Path, title: str,
          previous: dict | None = None, tech: dict | None = None, lookthroughs=(), heatmaps=(None, None), log_lines=(),
          price_charts: dict | None = None, market_rows: list[dict] | None = None):
    previous, tech, price_charts = previous or {}, tech or {}, price_charts or {}
    profit = {p["ticker"]: p for p in profit_rows}
    market_html = markets_html(market_rows or [])
    ordered = sorted(results.values(), key=lambda r: r["display_ticker"])
    tickers = [r["ticker"] for r in ordered]
    sp = cfg["spot"]
    counts = {s: sum(1 for r in ordered if r["signal"] == s) for s in ("green", "blue", "red")}
    grades = {g: sum(1 for t in tickers if profit.get(t, {}).get("grade", "n/m") == g) for g in GRADE_ORDER}
    with tempfile.TemporaryDirectory() as tmp, charts.resolution(HTML_DPI):
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
    chart_scripts = (f"<script>{VENDOR.read_text(encoding='utf-8')}</script>"
                     f"<script>window.PC_SMA_COLOURS = {json.dumps({str(k): v for k, v in price_chart.SMA_COLOURS.items()})};</script>"
                     f"<script>{CHART_JS}</script>"
                     if (price_charts or market_rows) and VENDOR.exists() else "")
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
<nav class="toc">Companies: {toc}{' · <a href="#markets">Markets</a>' if market_html else ''}{' · <a href="#heatmaps">Heatmaps</a>' if heat_html else ''}</nav>
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
{market_html}{''.join(sections)}{etf_html}{heat_html}
<section class="company"><h2>Run log</h2><ul class="small">{log}</ul></section>
<footer>Educational framework, not investment advice. Previous run's figures in (brackets). Prices in each exchange's currency;
sales and profits as the company reports them.</footer>
</main><script>{JS}</script>{chart_scripts}</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path


def file_name(list_name: str | None, as_of) -> str:
    return f"{list_title(list_name).replace(' ', '_')}_Value_vs_Price_{as_of:%d%b%Y}.html"
