"""One bookmarked PDF per run (Valuation Playbook, section 4).

Page 1 explains the method, shows the legend and the summary table(s): a value table (12x / 15x / 25x values)
for producers, royalty companies, developers and the rest, and a growth table (reverse DCF) for tech and Nifty
stocks. Rows are tinted in their signal's colour – darker for tier A or bigger companies.

Then one section per company, alphabetical:
  page 1 – headline, the "how to read" cards with this company's numbers, the valuation band, the main curve and
           the key figures;
  page 2 – the sensitivity heatmap (and the EPS history for Nifty v2), how the value is calculated with a worked
           example, assumptions and data notes, and sources.
Every page carries the footer "educational framework, not investment advice". The words come from wording.py,
the charts from charts.py; this module only lays them out.
"""
from __future__ import annotations

import datetime as dt
import re
import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, Image, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from . import charts, price_chart
from . import style as S
from .wording import (BUY_RULE, MODEL_LABEL, auto_comment, calc_steps, day, esc, flag_text,
                      has_earnings, headline, key_figures, kpi_cards, money, npa_summary, price_date, worked_example)

PAGE = landscape(A4)
MARGIN = 12 * mm
BOTTOM = 13 * mm
WIDTH = PAGE[0] - 2 * MARGIN
LEFT_COLUMN = 132 * mm       # charts on the left of each company page, words on the right
LATE = "#B7791F"             # amber for stale or undated data


def hexc(value):
    return colors.HexColor(value)


# ------------------------------------------------------------------------------------------------- text styles
class Styles:
    def __init__(self):
        self.f = S.pdf_fonts()

        def style(name, size, weight="regular", color=S.INK, leading=None, align=0, **kw):
            return ParagraphStyle(name, fontName=self.f[weight], fontSize=size, leading=leading or size * 1.28,
                                  textColor=hexc(color), alignment=align, **kw)
        self.title = style("title", 19, "semibold", leading=23)
        self.subtitle = style("subtitle", 9, color=S.INK2, leading=12)
        self.h2 = style("h2", 11.5, "semibold", leading=15, spaceBefore=2, spaceAfter=4)
        self.h3 = style("h3", 8.6, "semibold", leading=11, spaceAfter=3)
        self.small = style("small", 7.1, color=S.INK2, leading=9.4)
        self.tiny = style("tiny", 6.4, color=S.MUTED, leading=8.2)
        self.th = style("th", 6.5, "semibold", color=S.INK2, leading=8)
        self.th_right = style("thr", 6.5, "semibold", color=S.INK2, leading=8, align=2)
        self.td = style("td", 7.1, leading=8.8)
        self.td_right = style("tdr", 7.1, leading=8.8, align=2)
        self.td_center = style("tdc", 7.1, leading=8.8, align=1)
        self.comment = style("comment", 6.5, color=S.INK2, leading=8.2)
        self.kpi_label = style("kpil", 6.4, "semibold", color=S.MUTED, leading=8)
        self.kpi_value = style("kpiv", 14, "semibold", leading=17)
        self.kpi_caption = style("kpic", 6.5, color=S.INK2, leading=8.4)
        self.callout = style("callout", 8.8, leading=12.4)
        self.step = style("step", 7.8, leading=10.6)
        self.step_no = style("stepn", 7.8, "semibold", leading=10.6, color=S.SIGNAL["blue"])

    def bold(self, text):
        return f"<font name='{self.f['semibold']}'>{text}</font>"


def muted(text, size=6):
    return f"<font size='{size}' color='{S.MUTED}'>{text}</font>"


# ------------------------------------------------------------------------------------------------- flowables
class Pill(Flowable):
    """A rounded label in a signal colour; the text shrinks to fit."""

    def __init__(self, text, color, width, font, size=6.9):
        super().__init__()
        self.text, self.color, self.width, self.font, self.size = text, color, width, font, size
        self.height = size + 6.5

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        size = self.size
        while stringWidth(self.text, self.font, size) > self.width - 8 and size > 5:
            size -= 0.3
        self.canv.setFillColor(hexc(self.color))
        self.canv.roundRect(0, 0, self.width, self.height, self.height / 2, fill=1, stroke=0)
        self.canv.setFillColor(colors.white)
        self.canv.setFont(self.font, size)
        self.canv.drawCentredString(self.width / 2, (self.height - size) / 2 + 1.3, self.text)


class Bookmark(Flowable):
    def __init__(self, key, title, level=0):
        super().__init__()
        self.key, self.title, self.level = key, title, level

    def wrap(self, *_):
        return 0, 0

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


def image(path, width):
    w, h = ImageReader(str(path)).getSize()
    return Image(str(path), width=width, height=width * h / w)


def boxed(content, width, color, background=S.SOFT):
    """A soft panel with a coloured bar on the left – used for headlines and worked examples."""
    t = Table([[content]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), hexc(background)), ("LINEBEFORE", (0, 0), (0, -1), 3, hexc(color)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def side_by_side(left, right, left_width=LEFT_COLUMN):
    t = Table([[left, right]], colWidths=[left_width, WIDTH - left_width])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (0, -1), 7 * mm), ("RIGHTPADDING", (1, 0), (1, -1), 0)]))
    return t


# ------------------------------------------------------------------------------------------------- key figures and cards
def figures_table(rows, st, width):
    data = [[Paragraph(st.bold(k) if b else k, st.td), Paragraph(st.bold(v) if b else v, st.td_right)] for k, v, b in rows]
    t = Table(data, colWidths=[width * 0.62, width * 0.38])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, hexc(S.LINE)), ("TOPPADDING", (0, 0), (-1, -1), 2.4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def kpi_row(cards, st):
    width = WIDTH / len(cards)
    cells = []
    for label, value, caption, colour in cards:
        card = Table([[Paragraph(label.upper(), st.kpi_label)], [Paragraph(value, st.kpi_value)], [Paragraph(caption, st.kpi_caption)]],
                     colWidths=[width - 4])
        card.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), hexc(S.SOFT)), ("LINEABOVE", (0, 0), (-1, 0), 2.2, hexc(colour)),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                                  ("TOPPADDING", (0, 0), (0, 0), 6), ("TOPPADDING", (0, 1), (-1, -1), 1),
                                  ("BOTTOMPADDING", (0, 0), (-1, 1), 1), ("BOTTOMPADDING", (0, -1), (-1, -1), 7)]))
        cells.append(card)
    row = Table([cells], colWidths=[width] * len(cards))
    row.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                             ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return row


# ------------------------------------------------------------------------------------------------- summary tables
def tint_strength(r):
    """Tier A/B/C for tiered lists; market-value shade for growth stocks."""
    if r.get("tier") in S.TIER_STRENGTH:
        return S.TIER_STRENGTH[r["tier"]]
    return S.SHADE_STRENGTH.get(r.get("shade"), 3)


def _table_style(rows):
    s = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1),
         ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
         ("BACKGROUND", (0, 0), (-1, 0), hexc("#EEF0F4")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, hexc(S.INK2))]
    for i, r in enumerate(rows, start=1):
        s += [("BACKGROUND", (0, i), (-1, i), hexc(S.tint(r["signal"], tint_strength(r)))),
              ("LINEBELOW", (0, i), (-1, i), 1.0, colors.white),
              ("LINEBEFORE", (0, i), (0, i), 3, hexc(S.SIGNAL[r["signal"]]))]
    return TableStyle(s)


def _header(names, numeric, st):
    return [Paragraph(h, st.th_right if i in numeric else st.th) for i, h in enumerate(names)]


def _widths(parts):
    return [w * WIDTH / sum(parts) for w in parts]


def _ticker(r, st):
    return Paragraph(f"{st.bold(esc(r['display_ticker']))}<br/><font size='6.2' color='{S.INK2}'>{esc(r['name'])}</font>", st.td)


def _price(r, st):
    late = r.get("price_undated") or "STALE" in r.get("flags", []) or any(f.startswith("price ") for f in r.get("flags", []))
    return Paragraph(f"{st.bold(money(r['price'], r['price_ccy']))}<br/>"
                     f"<font size='6.1' color='{LATE if late else S.MUTED}'>{price_date(r)}</font>", st.td)


def _mos(x, st, previous=None):
    if x is None:
        return Paragraph("–", st.td_right)
    colour = S.SIGNAL["green"] if x >= 0 else S.SIGNAL["red"]
    text = f"<font color='{colour}'>{st.bold(S.pct(x).replace('< ', '<'))}</font>"
    if previous is not None:
        text += "<br/>" + muted(f"({S.pct(previous)})")
    return Paragraph(text, st.td_right)


def _comment(r, st, tech):
    text = esc(r.get("comment") or auto_comment(r))
    if tech and tech.get("note"):
        text += " " + muted(f"· {esc(tech['note'])}", 6.3)
    if r.get("flags"):
        text += " " + muted(flag_text(r), 6.3)
    return Paragraph(text, st.comment)


def _buy_level(r):
    ccy, m = r["price_ccy"], r["model"]
    if r.get("buy_level") is None:
        return "–"
    if m in ("producer", "cashflow") and r.get("tier") == "A":
        return f"start ≤ {money(r['buy_level'], ccy)}<br/>add ≤ {money(r['add_level'], ccy)}"
    rule = f"needs ≤ {r['growth_buy']*100:.0f}%/yr" if m == "growth" else BUY_RULE.get(m, "")
    return f"≤ {money(r['buy_level'], ccy)}<br/>{muted(rule, 5.9)}"


def _values(r):
    """The 12x / 15x / 25x cells, the value the margin of safety is measured from, and that margin."""
    ccy, m = r["price_ccy"], r["model"]
    label = lambda t: "<br/>" + muted(t, 5.8)  # noqa: E731
    if m in ("producer", "cashflow") and has_earnings(r):
        tags = (label(f"{r['mult_lo']}x"), label(f"{r['mult_hi']}x")) if m == "cashflow" else ("", "")
        return (money(r["v_low"], ccy) + tags[0], money(r["v_high"], ccy) + tags[1], money(r["v_sell"], ccy)), r["v_low"]
    if m in ("developer", "physical"):
        return (money(r["nav"], ccy) + label("NAV"), "–", money(r["call_level"], ccy) + label("sell")), r["nav"]
    if m == "leases":
        return (money(r["v_low"], ccy) + label("cautious"), money(r["v_base"], ccy) + label("base"),
                money(r["v_high"], ccy) + label("fair")), r["v_low"]
    return ("–", "–", "–"), None


def value_table(rows, st, previous, tech):
    widths = _widths([34, 22, 17, 17, 17, 17, 14, 8, 29, 25, 72])
    data = [_header(["Ticker", "Price (date)", "12x value", "15x value", "25x value", "Margin of safety", "MoS %", "Tier",
                     "Signal", "Buy level", "Comment"], {2, 3, 4, 5, 6}, st)]
    for r in rows:
        (v12, v15, v25), value = _values(r)
        gap = "–" if value is None else money(value - r["price"], r["price_ccy"])
        before = previous.get(r["ticker"], {}).get("margin_of_safety")
        data.append([_ticker(r, st), _price(r, st), Paragraph(v12, st.td_right), Paragraph(v15, st.td_right),
                     Paragraph(v25, st.td_right), Paragraph(gap, st.td_right), _mos(r.get("margin_of_safety"), st, before),
                     Paragraph(r.get("tier") or "–", st.td_center), Pill(r["action"], S.SIGNAL[r["signal"]], widths[8] - 8, st.f["semibold"]),
                     Paragraph(_buy_level(r), st.td), _comment(r, st, tech.get(r["ticker"]))])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(_table_style(rows))
    return table


def _quality(r):
    if r.get("pb") is not None and r.get("fair_pb") is not None:
        fair = muted(f"fair {r['fair_pb']:.1f}")
        label = "P/ABV" if (r.get("asset_quality") or {}).get("bad_loans_ps") else "P/B"   # on book less bad loans
        npa = npa_summary(r).replace(" gross · ", " / ").replace(" net", "")
        return f"{label} {r['pb']:.1f}<br/>{fair}" + (f"<br/>{muted(npa)}" if npa else "")
    if r.get("cash_conversion") is not None:
        cc = r["cash_conversion"]
        return f"<font color='{S.SIGNAL['red'] if cc < 0.7 else S.INK}'>cash {cc*100:.0f}%</font>"
    if r.get("fcf_ps") is not None:
        return f"FCF {r['fcf_ps'] / r['price'] * 100:.1f}%"
    return "–"


def growth_table(rows, st, previous, tech):
    widths = _widths([34, 22, 17, 17, 17, 21, 15, 12, 19, 16, 28, 20, 38])
    data = [_header(["Ticker", "Price (date)", "No growth", "@ 10%/yr", "@ 20%/yr", "Growth needed", "MoS", "P/E", "Quality",
                     "Mkt value", "Signal", "Buy price", "Comment"], set(range(2, 10)), st)]
    for r in rows:
        ccy, g = r["price_ccy"], r.get("implied_growth")
        before = previous.get(r["ticker"], {}).get("implied_growth")
        needed = "–" if g is None else st.bold(S.pct(g, 1)) + ("<br/>" + muted(f"({S.pct(before, 1)})") if before is not None else "")
        mv = r.get("market_value_usd_bn")
        size = "–" if mv is None else f"${mv:,.0f}bn" if mv >= 10 else f"${mv:,.1f}bn"
        data.append([_ticker(r, st), _price(r, st), Paragraph(money(r["v0"], ccy), st.td_right),
                     Paragraph(money(r["v10"], ccy), st.td_right), Paragraph(money(r["v20"], ccy), st.td_right),
                     Paragraph(needed, st.td_right), _mos(r.get("margin_of_safety"), st),
                     Paragraph(f"{r['pe']:.1f}" if r.get("pe") else "–", st.td_right), Paragraph(_quality(r), st.td_right),
                     Paragraph(size, st.td_right), Pill(r["action"], S.SIGNAL[r["signal"]], widths[10] - 8, st.f["semibold"]),
                     Paragraph(_buy_level(r), st.td), _comment(r, st, tech.get(r["ticker"]))])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(_table_style(rows))
    return table


def legend(st, rows):
    """Signal colours, then what the tint strength means: tiers for a tiered list, otherwise market value."""
    tiered = any(r.get("tier") for r in rows)
    shades = (["Tier A · large, low-cost, royalties", "Tier B · mid-tier / higher cost", "Tier C · juniors, developers"] if tiered
              else ["≥ $100bn (tech ≥ $200bn)", "$30–100bn", "$10–30bn", "< $10bn"])
    chips = [("Green · buy / start a position", S.SIGNAL["green"], "#FFFFFF"), ("Blue · watch / hold", S.SIGNAL["blue"], "#FFFFFF"),
             ("Red · expensive or no valid value", S.SIGNAL["red"], "#FFFFFF")]
    chips += [(label, S.TINT["blue"][i], S.INK) for i, label in enumerate(shades)]
    font, size, pad, gap = st.f["semibold"], 6.9, 6, 5
    t = Table([[label for label, _, _ in chips]], hAlign="LEFT",
              colWidths=[stringWidth(label, font, size) + 2 * pad + gap for label, _, _ in chips])
    style = [("FONT", (0, 0), (-1, -1), font, size), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
             ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad + gap)]
    for i, (_, background, text) in enumerate(chips):
        style += [("TEXTCOLOR", (i, 0), (i, 0), hexc(text)), ("BACKGROUND", (i, 0), (i, 0), hexc(background)),
                  ("LINEAFTER", (i, 0), (i, 0), gap, colors.white)]
    t.setStyle(TableStyle(style))
    return t


METHOD = ("<b>Method.</b> Value from the latest reported numbers only (no targets, no forecasts) against today's price. "
          "Producers and royalties: owner earnings at today's metal prices × 12 / 15 / 25 + net cash. Developers and physical "
          "holders: NAV. Growth: the yearly growth the price needs (5 years, 15x exit, 10% US / 12% India). "
          "Margin of safety = (value − price) ÷ value.")


RULES_NOTE = ("<b>Rules.</b> Tier A: start at or below the 15x value, add at or below 12x. Tiers B and C: buy only with a 20% "
                  "margin at 12x and AISC ≤ 60% of spot, or ≤ 0.8× NAV (0.85× physical). Red = ≥ 25x, ≥ 1.5× NAV or no valid "
                  "value. Before buying: price vs 200-day average (below = buy in thirds), RSI/MACD; sell puts at 12x. "
                  "[Flags]: STALE = results > ~100 days old and newer ones out (or due); price age. (Previous run.)")


GROWTH_NOTE = ("<b>Columns.</b> Value per share with no growth, 10% and 20% a year for 5 years (15x exit, discounted at 10% US / "
               "12% India). Growth needed = the growth that makes the value equal the price; previous run in (brackets). Green ≤ 5% "
               "a year (≤ 10% for tier A), blue 5–25%, red ≥ 25%. Cyclicals, cash conversion below 70% and lenders with "
               "bad-loan warning signs are capped at blue. Quality = 5-year cash conversion, or price-to-book against the fair "
               "multiple (5-yr ROE × no-growth multiple) for financials; P/ABV = on book less bad loans not provided for. "
               "Shade = market value.")


# ------------------------------------------------------------------------------------------------- one company
def company_section(r, c, cfg, st, chart_dir: Path, tech=None, pchart=None):
    signal_colour = S.SIGNAL[r["signal"]]
    out = [Bookmark(f"s_{r['ticker']}", f"{r['display_ticker']} – {r['name']}", 1)]
    title = Table([[Paragraph(f"{st.bold(esc(r['display_ticker']))}&nbsp;&nbsp;<font color='{S.INK2}'>{esc(r['name'])}</font>", st.title),
                    Pill(r["action"], signal_colour, 60 * mm, st.f["semibold"], 8.5)]], colWidths=[WIDTH - 62 * mm, 62 * mm])
    title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    reported = f", reported {day(r['period_reported'])}" if r.get("period_reported") else ""
    meta = [MODEL_LABEL.get(r["model"], r["model"])] + ([f"tier {r['tier']}"] if r.get("tier") else [])
    meta += [f"results {esc(r['period'])} (to {day(r['period_end'])}{reported})",
             f"price {price_date(r)} · {esc(r.get('price_source', ''))}"]
    flags = f"&nbsp;&nbsp;<font color='{LATE}'>{flag_text(r)}</font>" if r.get("flags") else ""
    out += [title, Paragraph(" · ".join(meta) + flags, st.subtitle), Spacer(1, 5), kpi_row(kpi_cards(r), st), Spacer(1, 6),
            boxed(Paragraph(headline(r, cfg), st.callout), WIDTH, signal_colour), Spacer(1, 4)]

    def chart(fn, name, *args):
        path = fn(*args, chart_dir / f"{r['ticker']}_{name}.png")
        return image(path, LEFT_COLUMN - 7 * mm) if path else None

    price = price_chart.static_png(pchart, chart_dir / f"{r['ticker']}_price.png")
    if price:
        values = " · ".join(f"{v['label']} {v['price']:,.2f}" for v in pchart["values"])
        text = (f"<b>Price</b> ({esc(pchart['symbol'])}, {esc(pchart['currency'] or '')}): {esc(price_chart.caption(pchart))} · "
                + (f"value lines: {esc(values)} · " if values else "")
                + "dotted: nearest support (green) / resistance (red), auto · blue / purple: trend lines (auto)")
        out += [image(price, WIDTH), Paragraph(text, st.tiny), Spacer(1, 4)]
    band = charts.band(r, chart_dir / f"{r['ticker']}_band.png", width_mm=WIDTH / mm)
    if band:
        out.append(image(band, WIDTH))
    curve = chart(charts.curve, "curve", r, c, cfg)
    figures = [Paragraph("Key figures", st.h3), figures_table(key_figures(r), st, WIDTH - LEFT_COLUMN)]
    out += [Spacer(1, 4), side_by_side(curve or Spacer(1, 1), figures)]

    panels = [chart(charts.heatmap, "heat", r, c, cfg)]
    if r.get("v2"):
        panels.append(chart(charts.eps_history, "eps", r))
    if r["model"] == "leases":
        panels.append(chart(charts.bridge, "bridge", r))
    panels = [p for p in panels if p]
    working = [Paragraph("How the value is calculated", st.h3), _steps(calc_steps(r, c), st, WIDTH - LEFT_COLUMN)]
    example = worked_example(r, c)
    if example:
        working += [Spacer(1, 5), boxed(Paragraph(example, st.callout), WIDTH - LEFT_COLUMN, S.SIGNAL["blue"])]
    if tech and tech.get("note"):
        working += [Spacer(1, 5), Paragraph(f"<b>Before buying</b> (200-day average, RSI, MACD): {esc(tech['note'])}", st.small)]
    left = []
    for p in panels:
        left += [p, Spacer(1, 4)]
    out += [CondPageBreak(80 * mm), Spacer(1, 6), side_by_side(left or Spacer(1, 1), working)]

    notes = ([f"STALE: {r['stale_reason']}"] if r.get("stale_reason") else []) + list(c.get("assumptions", [])) + list(c.get("notes", []))
    if r.get("signal_caps"):
        notes.append("Signal capped at blue: " + ", ".join(r["signal_caps"]) + ".")
    spot = cfg["spot"]
    notes.append(f"Spot used: gold ${spot['gold']:,.0f}/oz, silver ${spot['silver']:.2f}/oz, copper ${spot['copper']:.2f}/lb, "
                 f"uranium ${spot['uranium']:.2f}/lb (config.yaml, run of {day(cfg['as_of'])}).")
    bullets = lambda items: [Paragraph(f"•&nbsp;&nbsp;{esc(x)}", st.small) for x in items]  # noqa: E731
    notes_block = bullets(notes)
    out += [KeepTogether([Spacer(1, 6), Paragraph("Assumptions and data notes", st.h3)] + notes_block[:2])] + notes_block[2:]
    out += [Spacer(1, 5), Paragraph("Sources", st.h3)] + bullets(c.get("sources", []))
    return out


def _steps(items, st, width):
    t = Table([[Paragraph(str(i + 1), st.step_no), Paragraph(x, st.step)] for i, x in enumerate(items)],
              colWidths=[5 * mm, width - 5 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]))
    return t


# ------------------------------------------------------------------------------------------------- the document
def new_document(path: Path, title: str, footer: str, st: Styles):
    """A landscape A4 document with the footer line and page number on every page."""
    footer += " · educational framework, not investment advice"

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(hexc(S.LINE))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 10 * mm, PAGE[0] - MARGIN, 10 * mm)
        canvas.setFont(st.f["regular"], 6.8)
        canvas.setFillColor(hexc(S.MUTED))
        canvas.drawString(MARGIN, 6.5 * mm, footer)
        canvas.drawRightString(PAGE[0] - MARGIN, 6.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=BOTTOM,
                          title=title, author="value-screener", subject="Educational framework, not investment advice")
    frame = Frame(MARGIN, BOTTOM, WIDTH, PAGE[1] - MARGIN - BOTTOM, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(frames=[frame], onPage=on_page)])
    return doc


MARKETS_NOTE = ("Price only – commodities, an index and ETFs have no earnings, so they are not valued. Daily prices from Yahoo "
                "(futures for gold, silver and oil); uranium is Cameco's month-end spot price. Charts are in the HTML report.")


def markets_table(rows, st):
    """Markets (price only): price, date, changes, price vs the 50- and 200-day averages, RSI, 52-week range."""
    def num(x, nd=1):
        return "–" if x is None else f"{x:,.{nd}f}"

    def signed(x):
        if x is None:
            return "–"
        return f"<font color='{S.SIGNAL['green'] if x >= 0 else S.SIGNAL['red']}'>{x*100:+.1f}%</font>"

    names = ["Market", "Price", "Date", "1 week", "1 month", "1 year", "vs 50-day", "vs 200-day", "RSI", "52-week range"]
    numeric = set(range(1, len(names)))
    data = [_header(names, numeric, st)]
    for r in rows:
        cells = [f"{num(r['price'], 2)} <font size='5.8' color='{S.MUTED}'>{esc(r['unit'] or r['currency'] or '')}</font>",
                 esc(r["date"]), signed(r["chg_1w"]), signed(r["chg_1m"]), signed(r["chg_1y"]), signed(r["vs50"]),
                 signed(r["vs200"]), num(r["rsi"], 0), f"{num(r['low52'], 2)}–{num(r['high52'], 2)}"]
        data.append([Paragraph(f"{st.bold(esc(r['ticker']))}<br/><font size='6.2' color='{S.INK2}'>{esc(r['name'])}</font>", st.td)]
                    + [Paragraph(c, st.td_right) for c in cells])
    table = Table(data, colWidths=_widths([16, 13, 9, 8, 8, 8, 8, 8, 5, 15]), repeatRows=1)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 0.8),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("BACKGROUND", (0, 0), (-1, 0), hexc("#EEF0F4")),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.8, hexc(S.INK2)), ("LINEBELOW", (0, 1), (-1, -1), 0.4, hexc(S.LINE))]))
    return table


def build(results: dict, companies: dict, cfg: dict, path: Path, title: str, previous: dict | None = None,
          tech: dict | None = None, log_lines=(), price_charts: dict | None = None, market_rows: list | None = None):
    previous, tech, price_charts = previous or {}, tech or {}, price_charts or {}
    st = Styles()
    doc = new_document(path, f"{title} – value vs price", f"{title} · value vs price · {day(cfg['as_of'])}", st)

    ordered = sorted(results.values(), key=lambda r: r["display_ticker"])
    others = [r for r in ordered if r["model"] != "growth"]
    growth = [r for r in ordered if r["model"] == "growth"]
    spot = cfg["spot"]
    story = [Bookmark("summary", "Summary", 0), Paragraph(f"{esc(title)} – value vs price", st.title),
             Paragraph(f"{len(ordered)} companies, alphabetical · run {day(cfg['as_of'])} · spot gold ${spot['gold']:,.0f}, "
                       f"silver ${spot['silver']:.2f}, copper ${spot['copper']:.2f}, uranium ${spot['uranium']:.2f} · each "
                       "company's report follows in the same order", st.subtitle),
             Spacer(1, 3), Paragraph(METHOD, st.small), Spacer(1, 4), legend(st, others or growth), Spacer(1, 4)]
    if others:
        story += [value_table(others, st, previous, tech), Spacer(1, 2), Paragraph(RULES_NOTE, st.tiny)]
    if growth:
        if others:
            story += [CondPageBreak(60 * mm), Spacer(1, 8), Paragraph("Growth companies – reverse DCF", st.h2),
                      legend(st, growth), Spacer(1, 4)]
        story += [growth_table(growth, st, previous, tech), Spacer(1, 4), Paragraph(GROWTH_NOTE, st.tiny)]
    if market_rows:
        story += [CondPageBreak(50 * mm), Spacer(1, 8), Bookmark("markets", "Markets", 0),
                  Paragraph("Markets – price only, not valued", st.h2), Spacer(1, 3), markets_table(market_rows, st),
                  Spacer(1, 2), Paragraph(MARKETS_NOTE, st.tiny)]
    if log_lines:
        story += [Spacer(1, 4), Paragraph("Run notes: " + esc(" · ".join(log_lines)), st.tiny)]
    story.append(Bookmark("companies", "Companies", 0))
    with tempfile.TemporaryDirectory() as tmp:
        for r in ordered:
            story += [PageBreak()] + company_section(r, companies[r["ticker"]], cfg, st, Path(tmp), tech.get(r["ticker"]),
                                                        price_charts.get(r["ticker"]))
        doc.build(story)
    return path


def list_title(list_name: str | None) -> str:
    """'nifty50' → 'Nifty 50', 'core' → 'Core', None → 'All Companies'."""
    return re.sub(r"([A-Za-z])(\d)", r"\1 \2", (list_name or "all companies").replace("_", " ").title())


def file_name(list_name: str | None, as_of: dt.date) -> str:
    return f"{list_title(list_name).replace(' ', '_')}_Value_vs_Price_{as_of:%d%b%Y}.pdf"
