"""Writes two PDFs on how Value Screener values companies, for someone new to fundamental analysis:
docs/Valuation_Overview.pdf (4 pages, no formulas) and docs/Valuation_Guide.pdf (the detailed guide with basics,
glossary, formulas and worked examples). The worked examples are computed live from the company files and config.yaml, so the guide
always uses the same arithmetic as the reports:

    python docs/build_valuation_guide.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,  # noqa: E402
                                Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

from valuescreen import engine, growth_screen, loader, price_cases  # noqa: E402
from valuescreen import style as S  # noqa: E402
from valuescreen.models import dcf_factor  # noqa: E402

OUT = HERE / "Valuation_Guide.pdf"
OVERVIEW = HERE / "Valuation_Overview.pdf"
TMP = ROOT / "output" / "guide"
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
WIDTH = PAGE_W - 2 * MARGIN


def pdf_fonts() -> dict:
    """Registers Inter (valuescreen/fonts) with reportlab, else matplotlib's DejaVu. {'regular','medium','semibold','bold'}."""
    from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415
    from reportlab.pdfbase.ttfonts import TTFont  # noqa: PLC0415
    weights = {"regular": "Regular", "medium": "Medium", "semibold": "SemiBold", "bold": "Bold"}
    if all((S.FONTS / f"Inter-{w}.ttf").exists() for w in weights.values()):
        for w in weights.values():
            pdfmetrics.registerFont(TTFont(f"Inter-{w}", str(S.FONTS / f"Inter-{w}.ttf")))
        pdfmetrics.registerFontFamily("Inter-Regular", normal="Inter-Regular", bold="Inter-SemiBold",
                                      italic="Inter-Regular", boldItalic="Inter-SemiBold")
        return {k: f"Inter-{w}" for k, w in weights.items()}
    ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("DV", str(ttf / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DVB", str(ttf / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DV", boldItalic="DVB")
    return {"regular": "DV", "medium": "DV", "semibold": "DVB", "bold": "DVB"}


F = pdf_fonts()
FAMILY = S.font_family()
BLUE, GREEN, RED, AMBER = S.SIGNAL["blue"], S.SIGNAL["green"], S.SIGNAL["red"], "#B7791F"


# ------------------------------------------------------------------------------------------------- styles
def ps(name, size, font="regular", color=S.INK, leading=None, **kw):
    return ParagraphStyle(name, fontName=F[font], fontSize=size, leading=leading or size * 1.42, textColor=colors.HexColor(color), **kw)


ST = {
    "title": ps("title", 26, "bold", leading=31),
    "subtitle": ps("subtitle", 12.5, color=S.INK2, leading=17),
    "h1": ps("h1", 17, "bold", leading=21, spaceBefore=4, spaceAfter=8, keepWithNext=1),
    "h2": ps("h2", 12.5, "semibold", leading=16, spaceBefore=10, spaceAfter=4, keepWithNext=1),
    "body": ps("body", 10, leading=14.6, spaceAfter=6),
    "small": ps("small", 8.6, color=S.INK2, leading=12),
    "cell": ps("cell", 8.8, leading=11.6),
    "cellb": ps("cellb", 8.8, "semibold", leading=11.6),
    "cellr": ps("cellr", 8.8, leading=11.6, alignment=2),
    "th": ps("th", 8.4, "semibold", color=S.INK2, leading=10.6),
    "box": ps("box", 9.8, leading=14),
    "formula": ps("formula", 10.2, "medium", leading=15, leftIndent=8),
    "toc1": ps("toc1", 10.5, leading=17),
}


def p(text, style="body"):
    return Paragraph(text, ST[style])


def b(text):
    return f"<font name='{F['semibold']}'>{text}</font>"


def heading(text, level=1):
    para = Paragraph(text, ST["h1" if level == 1 else "h2"])
    para._toc = (level - 1, text)
    return para


def callout(text, colour=BLUE, background=S.SOFT):
    t = Table([[Paragraph(text, ST["box"])]], colWidths=[WIDTH])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                           ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(colour)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([t, Spacer(1, 8)])


def formula(text):
    return callout(f"<font name='{F['medium']}'>{text}</font>", colour=AMBER, background="#FBF6EA")


def table(rows, widths, header=True, right=()):
    data = []
    for i, row in enumerate(rows):
        cells = []
        for j, x in enumerate(row):
            st = "th" if header and i == 0 else ("cellr" if j in right else "cell")
            cells.append(x if not isinstance(x, str) else Paragraph(x, ST[st]))
        data.append(cells)
    t = Table(data, colWidths=[w * WIDTH for w in widths], repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(S.LINE)),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(S.SOFT)),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(S.INK2))]
    t.setStyle(TableStyle(style))
    t.spaceAfter = 8
    return t if len(rows) > 12 else KeepTogether([t])   # long tables may split across pages


def steps(rows):
    """Numbered calculation steps: (what, how, result)."""
    data = [["#", "Step", "How", "Result"]] + [[str(i), a, h, r] for i, (a, h, r) in enumerate(rows, 1)]
    return table(data, [0.05, 0.27, 0.46, 0.22], right=(3,))


def figure(path, width_frac=1.0, height_ratio=0.42):
    w = WIDTH * width_frac
    return KeepTogether([Image(str(path), width=w, height=w * height_ratio), Spacer(1, 6)])


def m(x, ccy="USD", nd=2):
    return S.money(x, ccy, nd)


def pc(x, nd=0, signed=False):
    return S.pct(x, nd, signed)


# ------------------------------------------------------------------------------------------------- charts
def _fig(w=7.2, h=3.0):
    plt.rcParams["font.family"] = FAMILY
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(S.LINE)
    ax.tick_params(colors=S.INK2, labelsize=8.5)
    return fig, ax


def _save(fig, name):
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def chart_multiples():
    fig, ax = _fig(7.2, 2.6)
    mults = [5, 8, 10, 12, 15, 20, 25, 30]
    ys = [1 / x * 100 for x in mults]
    cols = [GREEN if x <= 12 else BLUE if x <= 15 else S.MUTED if x < 25 else RED for x in mults]
    ax.bar([f"{x}x" for x in mults], ys, color=cols, width=0.62)
    for i, y in enumerate(ys):
        ax.text(i, y + 0.4, f"{y:.1f}%", ha="center", fontsize=8.5, color=S.INK)
    ax.set_ylabel("Earnings yield (% a year)", fontsize=8.5, color=S.INK2)
    ax.set_title("Paying a multiple of earnings = earning that yield on your money (if earnings stay flat)",
                 fontsize=9.5, color=S.INK, loc="left")
    return _save(fig, "multiples")


def chart_ladder(r, ccy, name):
    fig, ax = _fig(7.2, 2.5)
    levels = [("Sell zone from (25x)", r["v_sell"], RED), ("Value at 15x", r["v_high"], BLUE),
              ("Value at 12x", r["v_low"], GREEN), ("Buy level (12x − 20%)", r["buy_level"], GREEN)]
    top = max(v for _, v, _ in levels) * 1.08
    for i, (label, v, c) in enumerate(levels):
        ax.barh(i, v, color=c, alpha=0.25 if "Buy" not in label else 0.55, height=0.6)
        ax.text(v, i, f"  {label}: {m(v, ccy)}", va="center", fontsize=8.5, color=S.INK)
    ax.axvline(r["price"], color=S.PRICE, lw=2.2)
    ax.text(r["price"], -0.75, f" price {m(r['price'], ccy)}", color=S.PRICE, fontsize=9, va="center", weight="bold")
    ax.set_ylim(-1.1, len(levels) - 0.5)
    ax.set_yticks([])
    ax.set_xlim(0, top * 1.45)
    ax.set_title(f"{name}: today's price against its value ladder", fontsize=9.5, loc="left", color=S.INK)
    return _save(fig, f"ladder_{name}")


def chart_growth(r, ccy, name):
    fig, ax = _fig(7.2, 2.6)
    gs = [x / 100 for x in range(-10, 36)]
    vals = [r["value_fn"](g) for g in gs]
    ax.plot([g * 100 for g in gs], vals, color=BLUE, lw=2)
    ax.axhline(r["price"], color=S.PRICE, lw=1.8)
    ax.text(-10, r["price"], f" price {m(r['price'], ccy, 0)}", color=S.PRICE, fontsize=8.5, va="bottom")
    g = r["implied_growth"]
    ax.scatter([g * 100], [r["price"]], color=S.PRICE, zorder=3)
    ax.annotate(f"growth needed {g*100:.1f}%/yr", (g * 100, r["price"]), xytext=(g * 100 + 2, r["price"] * 0.62),
                fontsize=8.5, arrowprops=dict(arrowstyle="->", color=S.INK2))
    for x0, x1, c in ((-10, 5, GREEN), (5, 25, BLUE), (25, 35, RED)):
        ax.axvspan(x0, x1, color=c, alpha=0.07)
    ax.set_xlabel("Yearly growth in earnings for the next 5 years (%)", fontsize=8.5, color=S.INK2)
    ax.set_ylabel(f"Value per share ({ccy})", fontsize=8.5, color=S.INK2)
    ax.set_title(f"{name}: value for each growth rate – where the curve meets the price is the growth the price needs",
                 fontsize=9, loc="left", color=S.INK)
    return _save(fig, f"growth_{name}")


def chart_discount(rate):
    fig, ax = _fig(7.2, 2.4)
    ts = list(range(0, 11))
    vals = [100 / (1 + rate) ** t for t in ts]
    ax.bar([str(t) for t in ts], vals, color=BLUE, alpha=0.75, width=0.62)
    for t, v in zip(ts, vals):
        ax.text(t, v + 1.5, f"${v:.0f}", ha="center", fontsize=8, color=S.INK)
    ax.set_xlabel("Years until you receive it", fontsize=8.5, color=S.INK2)
    ax.set_ylabel("Worth today ($)", fontsize=8.5, color=S.INK2)
    ax.set_ylim(0, 112)
    ax.set_title(f"$100 received later, in today's money at {rate*100:.0f}% a year", fontsize=9.5, loc="left", color=S.INK)
    return _save(fig, "discount")


def growth_needed(eps, nc, price, cfg, rate):
    from scipy.optimize import brentq  # noqa: PLC0415
    try:
        return brentq(lambda g: eps * dcf_factor(g, cfg, rate) + nc - price, -0.6, 2.0)
    except ValueError:
        return None


TECH = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "AMD", "AVGO", "TSM", "ASML", "ORCL", "QCOM", "MU")


def chart_nav():
    fig, ax = _fig(7.2, 1.5)
    bands = [(0, 0.8, GREEN, "Buy ≤ 0.80"), (0.8, 1.0, BLUE, "Watch"), (1.0, 1.5, S.MUTED, "Hold"), (1.5, 2.0, RED, "Sell ≥ 1.50")]
    for a, z, c, label in bands:
        ax.barh(0, z - a, left=a, color=c, alpha=0.3, height=0.6)
        ax.text((a + z) / 2, 0, label, ha="center", va="center", fontsize=8.5)
    ax.set_yticks([])
    ax.set_xlabel("Price ÷ NAV (developers); physical holders use 0.85 and 1.10", fontsize=8.5, color=S.INK2)
    return _save(fig, "nav")


# ------------------------------------------------------------------------------------------------- page furniture
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont(F["regular"], 7.5)
    canvas.setFillColor(colors.HexColor(S.MUTED))
    canvas.drawString(MARGIN, 10 * mm, "Value Screener – how companies are valued · educational, not investment advice")
    canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, str(doc.page))
    canvas.restoreState()


class Doc(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "_toc"):
            level, text = flowable._toc
            key = f"s{id(flowable)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=False)
            if level == 0:
                self.notify("TOCEntry", (level, text, self.page, key))


# ------------------------------------------------------------------------------------------------- content
def build():
    cfg = loader.load_config()
    cs = {**loader.load_companies(), **loader.load_companies(loader.companies_folder("miners"))}
    res = lambda t: engine.run(cs, [t], cfg)[t]  # noqa: E731
    spot = cfg["spot"]
    ogc, nem, cnq, msft, sput, abra, ccj = (res(t) for t in ("OGC", "NEM", "CNQ", "MSFT", "SPUT", "ABRA", "CCJ"))
    ccj_cases = price_cases.cases(cs["CCJ"], ccj, cfg)
    c_ogc, c_cnq, c_msft = cs["OGC"], cs["CNQ"], cs["MSFT"]
    lo, hi = cfg["multiples"]["producer"]
    sell = cfg["multiples"]["sell"]
    z = cfg["zones"]
    f0 = dcf_factor(0.0, cfg)
    today = dt.date.today()

    story = [Spacer(1, 40 * mm), p("How Value Screener values a company", "title"), Spacer(1, 4 * mm),
             p("A plain-English guide to the numbers behind every report – technology and other growth companies, "
               "then miners, royalty companies, oil producers, developers and metal holders – for someone new to "
               "fundamental analysis.", "subtitle"),
             Spacer(1, 10 * mm),
             p(f"Worked examples use the company files and prices in the project on {today:%d %B %Y} "
               f"(gold {m(spot['gold'], nd=0)}/oz, silver {m(spot['silver'])}/oz, copper {m(spot['copper'])}/lb, "
               f"uranium {m(spot['uranium'], nd=0)}/lb). Run <i>python docs/build_valuation_guide.py</i> to "
               "rebuild it with today's figures.", "small"),
             Spacer(1, 6 * mm),
             callout("This is an educational framework, not investment advice. Every number in it comes from a company's "
                     "own reported results and today's market prices; nothing here predicts the future."),
             PageBreak(), p("Contents", "h1")]
    toc = TableOfContents()
    toc.levelStyles = [ST["toc1"]]
    story += [toc, Spacer(1, 6 * mm),
              callout(f"{b('Which parts to read')}<br/>"
                      "<b>Everyone:</b> sections 1–2 (the idea and the words).<br/>"
                      "<b>Part A – technology and growth companies:</b> sections 3–8 (the DCF from scratch, the reverse "
                      "DCF, banks and cyclicals, the profit-vs-price grade and Dr. Amit Gupta's growth screen).<br/>"
                      "<b>Part B – miners, royalty companies, oil, developers and metal holders:</b> sections 9–15.<br/>"
                      "<b>Before buying anything:</b> sections 16–17 (reading a report, the checklist, every formula).<br/>"
                      "<b>Timing:</b> section 18 (technical analysis and the price charts).<br/>"
                      "Each part stands on its own – a tech reader can skip Part B, and a resource investor who looks at "
                      "tech only when it is cheap can read Part B first and dip into section 5."),
              PageBreak()]

    # 1 ------------------------------------------------------------------------------------------------
    story += [heading("1. The big idea: price is what you pay, value is what you get"),
              p("A share is a small piece of a business. The <b>price</b> is set every second by buyers and sellers; "
                "the <b>value</b> is what the business is worth to an owner – roughly, the cash it can hand out over "
                "its life. Prices swing far more than values. Most of the time the two are close; sometimes fear makes "
                "the price fall well below the value, and sometimes excitement pushes it far above."),
              p("The whole tool does one thing: it works out a <b>cautious value</b> for each company from its latest "
                "<b>reported</b> numbers, puts it next to today's price, and says whether there is enough room "
                "between the two – a <b>margin of safety</b> – to buy. Different businesses need different yardsticks: a "
                "growing technology company is judged by how much growth its price assumes (Part A); a mine by the cash "
                "it produces at today's metal price (Part B)."),
              callout(f"{b('Three rules run through everything:')}<br/>"
                      "1. <b>Reported numbers only.</b> No analyst forecasts, no price targets, no hoped-for growth. "
                      "If the company did not report it, it is not in the value (or it is marked ASSUMED).<br/>"
                      "2. <b>Be cautious.</b> Pay for little or no growth, value mines at a low multiple with metal at "
                      "today's price, and ask for a discount on top.<br/>"
                      "3. <b>Same rules every time.</b> The thresholds sit in one settings file (config.yaml), so a "
                      "good story or a falling price cannot change them on the day."),
              p("This way of thinking comes from Benjamin Graham and Warren Buffett, and in resources from Rick Rule: "
                "buy good businesses when they are cheap, never pay for growth you cannot see, and let the margin of "
                "safety absorb the mistakes you will inevitably make."),
              heading("Why it works – and when it does not", 2),
              p("It works because the market overreacts: a bad quarter, a sell-off in technology shares, a falling gold "
                "price or a scary headline can push a sound company's price far below what it earns. It does not tell you <i>when</i> the "
                "price will recover – cheap can stay cheap for years – and it cannot see the future: a new competitor, a "
                "product that stops selling, a mine flood or a collapse in the metal price changes the value. That is why the "
                "reports also show stress tests, quality checks and warnings.")]

    # 2 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("2. The words you need"),
              p("Every report uses the same small set of terms. Money in company files is in millions of the "
                "reporting currency; per-share figures are in the currency the shares trade in."),
              table([["Term", "What it means", "Why it matters here"],
                     ["Revenue (sales)", "Money received from selling the product", "The top line – before any costs"],
                     ["Net income (profit)", "What is left after every cost, interest and tax", "The usual 'earnings'; can include one-offs"],
                     ["Adjusted net income", "Net income without one-off items (write-downs, gains on sales, currency moves)", "A cleaner view of a normal quarter – the starting point for miners"],
                     ["Shares outstanding", "How many shares exist", "Everything is divided by this to get 'per share'"],
                     ["EPS", "Earnings per share = net income ÷ shares", "What one share earned"],
                     ["Market value (market cap)", "Share price × shares", "What the whole company costs on the market"],
                     ["Cash, debt, net cash", "Net cash = cash − debt (negative = net debt)", "Added to (or taken off) the value of the business"],
                     ["D&amp;A", "Depreciation and amortisation: the yearly accounting charge for wearing out buildings, equipment and mines", "Not cash this year – added back"],
                     ["Capex – sustaining vs growth", "Spending on equipment and mine development. Sustaining keeps production level; growth adds new production", "Sustaining capex is a real cost of staying in business – subtracted"],
                     ["Operating cash flow", "Cash actually generated by the business in the period", "Harder to dress up than profit"],
                     ["Free cash flow (FCF)", "Operating cash flow − all capex", "Cash left for dividends, buybacks and debt"],
                     ["Owner earnings", "Adjusted profit + D&amp;A − sustaining capex", "The cash an owner could take out and still keep the business the same size (section 8)"],
                     ["Multiple (e.g. 12x)", "Price paid ÷ yearly earnings", "How many years of today's earnings you pay for (section 10)"],
                     ["P/E", "Price ÷ EPS", "The most common multiple"],
                     ["Spot price", "Today's market price of the metal", "What the next ounce will sell for"],
                     ["Realised price", "The average price the company actually got in the quarter", "Used to re-price earnings to spot"],
                     ["AISC", "All-in sustaining cost per ounce: everything needed to keep producing one ounce", "AISC ÷ spot shows how thin or fat the margin is"],
                     ["Royalty", "A share of revenue paid to a government or royalty owner", "Taken off before profit"],
                     ["NPV / NAV", "Net present value: future cash flows of a project discounted to today. NAV adds cash and other assets", "How developers and metal holders are valued"],
                     ["Discount rate", "The yearly return you demand (10% US, 12% India)", "Turns future money into today's money"],
                     ["Present value", "What money received in the future is worth today", "The building block of a DCF (section 3)"],
                     ["DCF", "Discounted cash flow: future earnings, each brought back to today's money, added up", "How growth companies are valued (sections 4–5)"],
                     ["Exit multiple", "The P/E a business is assumed to sell for at the end of the forecast (15x here)", "Stops the DCF assuming growth for ever"],
                     ["Growth needed", "The yearly earnings growth for 5 years that makes the DCF value equal the price", "The signal for growth companies (section 5)"],
                     ["Book value", "Assets minus liabilities – what shareholders own on paper", "How banks are valued (with ROE)"],
                     ["Margin of safety", "How far the price is below the cautious value", "The cushion for mistakes"],
                     ["Dilution", "New shares issued, so each share owns less", "A hidden cost to existing owners"],
                     ["Cash conversion", "Operating cash ÷ net profit over 5 years", "Below 70% means profits are not turning into cash"],
                     ["ROE", "Return on equity = profit ÷ shareholders' equity (book value)", "How well a bank or company uses owners' money"]],
                    [0.2, 0.42, 0.38])]

    # DCF basics -----------------------------------------------------------------------------------------
    r_us = cfg["growth_dcf"]["discount_rate"]
    exit_m = cfg["growth_dcf"]["exit_multiple"]
    years = cfg["growth_dcf"]["years"]
    story += [PageBreak(), heading("3. Part A – tech: money today vs money later, the idea behind a DCF"),
              p("Most companies are not valued on today's earnings alone, because buyers expect them to grow. To put a "
                "value on growth you need one idea: <b>a dollar you receive later is worth less than a dollar today</b>. "
                "If you can earn 10% a year elsewhere – roughly what the US stock market has returned over the long run – "
                "then $100 today becomes $110 in a year. Turned around, $110 promised in a year is worth only $100 "
                "today, and $100 promised in a year is worth $100 ÷ 1.10 = $90.91."),
              formula("Value today of money received in year t = amount ÷ (1 + r)^t &nbsp;&nbsp;(r = the yearly return you require)"),
              p("That r is the <b>discount rate</b>. The tool uses 10% for US and other companies and 12% for Indian "
                "companies (higher interest rates and inflation in India mean investors there expect more). The higher "
                "the rate, the less future money is worth today – which is why share prices of growth companies fall "
                "hardest when interest rates rise."),
              figure(chart_discount(r_us), height_ratio=0.33),
              table([["Year", "Received then", "Divide by", "Worth today at 10%", "Worth today at 12%"]] +
                    [[str(t), "$100", f"1.10^{t} = {1.1**t:.3f}", m(100 / 1.1 ** t), m(100 / 1.12 ** t)] for t in (1, 2, 3, 5, 10)],
                    [0.1, 0.18, 0.26, 0.23, 0.23], right=(1, 3, 4)),
              p("A <b>discounted cash flow</b> (DCF) applies this to a whole business: estimate the earnings (or cash) "
                "it will produce each year, bring each year back to today's money, and add them up. The total is what the "
                "business is worth to someone who requires that return.")]

    ex_eps, ex_g = 10.0, 0.08
    rows, total = [], 0.0
    for t in range(1, years + 1):
        e_t = ex_eps * (1 + ex_g) ** t
        pv = e_t / (1 + r_us) ** t
        total += pv
        rows.append([str(t), m(e_t), f"{1/(1+r_us)**t:.3f}", m(pv)])
    sale = ex_eps * (1 + ex_g) ** years * exit_m
    sale_pv = sale / (1 + r_us) ** years
    story += [PageBreak(), heading("4. A discounted cash flow, step by step"),
              p(f"Take an imaginary company earning {m(ex_eps)} a share this year, with no cash or debt. Suppose earnings "
                f"grow {ex_g*100:.0f}% a year for {years} years, and that at the end you could sell the share for "
                f"{exit_m:.0f} times that year's earnings (the <b>exit multiple</b> – what a mature, steady company "
                "typically sells for). With a 10% required return:"),
              table([["Year", "Earnings per share", "× discount factor", "Worth today"]] + rows +
                    [["Sale", f"{m(ex_eps*(1+ex_g)**years)} × {exit_m:.0f} = {m(sale)}", f"{1/(1+r_us)**years:.3f}", m(sale_pv)],
                     ["", "", b("Value per share"), b(m(total + sale_pv))]],
                    [0.12, 0.38, 0.25, 0.25], right=(1, 2, 3)),
              p(f"So a share of this company is worth about {m(total + sale_pv)} to someone who wants 10% a year – about "
                f"{(total + sale_pv)/ex_eps:.1f} times this year's earnings. Pay less and you should beat 10% a year "
                "<i>if</i> the growth happens; pay more and you need even faster growth."),
              heading("Why five years and a 15x exit?", 2),
              p(f"Most of the value usually sits in the sale at the end ({m(sale_pv)} of {m(total + sale_pv)} here). "
                "Many DCFs assume growth for ever, which can justify almost any price. The tool deliberately keeps it "
                f"short and cautious: {years} years of growth, then a sale at a normal {exit_m:.0f}x – about what a mature "
                "business without much growth trades at. No growth beyond year five is paid for."),
              heading("The no-growth multiple", 2),
              p(f"With zero growth the same sum gives {f0:.1f} times earnings at 10% (and "
                f"{dcf_factor(0.0, cfg, 0.12):.1f}x at 12%). That is the value of a business whose earnings simply stay "
                "flat: it is the floor of the growth model, shown in the reports as the 'value with no growth'."),
              callout("A DCF is only as good as its inputs. A small change in growth or in the required return moves the "
                      "answer a lot (section 6 shows how much). That is why the tool never trusts its own growth guess – "
                      "it turns the question around instead.")]
    # Reverse DCF -----------------------------------------------------------------------------------------
    gr = c_msft["earnings"]
    vf = msft["value_fn"]
    tech = sorted((res(t) for t in TECH if t in cs), key=lambda r: (r["implied_growth"] is None, r["implied_growth"] or 0))
    story += [PageBreak(), heading("5. Technology and growth companies – the reverse DCF"),
              p("For technology and other growing companies – Microsoft, Nvidia, Apple, TSMC, ASML – a low multiple of "
                "today's earnings would call almost everything expensive, because buyers rightly pay for growth. But "
                "guessing that growth is where most valuations go wrong. So the tool turns the DCF around. Instead of "
                "asking 'what is it worth if it grows X%?', it asks: <b>how fast must earnings grow for today's price to "
                "make sense?</b> That number – the <b>growth needed</b> – is easy to judge: compare it with what the "
                "company has actually achieved, and with how long such growth usually lasts."),
              formula("Value = EPS × [ Σ over years 1–5 of ((1 + g) ÷ (1 + r))^t + 15 × ((1 + g) ÷ (1 + r))^5 ] + net cash per share<br/>"
                      f"r = 10% a year (12% for Indian companies) · with g = 0 the bracket is {f0:.1f} – the no-growth multiple"),
              p("The tool tries growth rates until the value equals the price; that rate is the growth needed. It is the "
                "same DCF as in section 4, solved backwards."),
              heading("Worked example: Microsoft (MSFT)", 2),
              steps([("Earnings per share, a year", f"net income {m(gr['net_income'], nd=0)}m in the quarter × 4 ÷ {c_msft['shares_m']:,}m shares", m(msft["oe"])),
                     ("Net cash per share", f"({c_msft['balance']['cash']:,} − {c_msft['balance']['debt']:,}) ÷ shares", m(msft["nc"])),
                     ("Value with no growth", f"{msft['oe']:.2f} × {msft['no_growth_multiple']:.1f} + {msft['nc']:.2f}", m(msft["v0"])),
                     ("Price today", "market", m(msft["price"])),
                     ("P/E today", "price ÷ EPS (after net cash)", f"{msft['pe']:.1f}x"),
                     ("Growth needed", "the g where value = price", pc(msft["implied_growth"], 1, signed=True) + " a year")]),
              figure(chart_growth(msft, "USD", "Microsoft"), height_ratio=0.36),
              p(f"In words: Microsoft's price assumes earnings grow about {msft['implied_growth']*100:.0f}% a year for five "
                f"years and the business is then still worth 15x. If earnings grow faster, the share should beat 10% a "
                f"year; if they grow slower, it will not. With no growth at all it would be worth {m(msft['v0'])}."),
              table([["If earnings grow (a year, 5 years)", "0%", "5%", "10%", "15%", "20%", "25%"],
                     ["Microsoft is worth"] + [m(vf(g), nd=0) for g in (0, 0.05, 0.10, 0.15, 0.20, 0.25)]],
                    [0.34, 0.11, 0.11, 0.11, 0.11, 0.11, 0.11], right=(1, 2, 3, 4, 5, 6)),
              heading("How the signal is set", 2),
              table([["Growth needed", "Signal", "Meaning"],
                     [f"≤ {z['growth_buy']*100:.0f}% a year ({z['growth_buy_tier_a']*100:.0f}% for tier A)", "Green – buy",
                      "Little or no growth is priced in – cheap for a real business"],
                     [f"{z['growth_buy']*100:.0f}–{z['growth_watch']*100:.0f}%", "Blue – watch", "A fair price if growth continues"],
                     [f"{z['growth_watch']*100:.0f}–{z['growth_sell']*100:.0f}%", "Blue – hold", "The price needs strong growth to hold up"],
                     [f"≥ {z['growth_sell']*100:.0f}%", "Red – expensive", "Only years of exceptional growth justify it"]],
                    [0.3, 0.2, 0.5]),
              heading(f"The tech list on {today:%d %B %Y}", 2),
              table([["Company", "Price", "EPS a year", "P/E", "Value with no growth", "Growth needed", "Signal"]] +
                    [[f"{r['display_ticker']} – {r['name']}", m(r["price"], r["price_ccy"], 0), m(r["oe"], r["price_ccy"]),
                      f"{r['pe']:.1f}x" if r.get("pe") else "–", m(r["v0"], r["price_ccy"], 0),
                      pc(r["implied_growth"], 1, signed=True) if r["implied_growth"] is not None else "–",
                      r["action"] + (" [stale]" if r.get("stale") else "")] for r in tech],
                    [0.26, 0.1, 0.1, 0.08, 0.13, 0.12, 0.21], right=(1, 2, 3, 4, 5)),
              p("Read it from the top: the less growth a price needs, the cheaper the company. A cyclical company can show "
                "negative growth needed (its earnings are at a peak, so the price already assumes a fall); it is capped at "
                "blue for that reason. [stale] means newer results are due and the file should be updated first.", "small")]

    story += [PageBreak(), heading("6. Special cases and the limits of a DCF"),
              heading("Banks, insurers and other financials", 2),
              p("A bank's profit swings with loan losses and its 'debt' is its raw material, so net cash means little. "
                "The tool values financials on <b>book value × the 5-year average return on equity (ROE)</b>, averaged "
                "with the latest earnings, and adds no net cash. The report also shows price-to-book against the fair "
                "multiple (ROE × the no-growth multiple)."),
              p("<b>Bad loans.</b> Book value is only as good as the loans behind it. For lenders the tool first takes off "
                "the bad loans not yet provided for – in India the net NPA (net NPA % × loans), in the US any nonaccrual "
                "loans the allowance does not cover – and values that <b>adjusted book</b>. Warning signs cap the signal "
                "at blue: net NPA above 2%, gross NPA above 5%, provision coverage below 60% or gross NPA rising by more "
                "than half a point in a year (India); nonaccrual loans above 2%, an allowance below them, or charge-offs "
                "up by half on a year earlier (US). Capital ratios are not checked – look them up before buying."),
              heading("Cyclical companies", 2),
              p("Chip makers like Micron, chemicals, steel, energy and autos earn a lot at the top of their cycle and "
                "little at the bottom. Valuing peak earnings would make them look cheap just before profits fall. So the "
                "tool uses the <b>average of the last 12 months' and the 5-year average EPS</b>, and a cheap cyclical is "
                "capped at blue: check where the cycle is before buying."),
              heading("Profits that do not turn into cash", 2),
              p("If operating cash flow has been less than 70% of reported profit over five years, the profit may be "
                "flattered by accounting. The signal is capped at blue and flagged 'cash conversion'."),
              heading("Indian companies (Nifty 50 and Nifty Midcap 150)", 2),
              p(f"The same model at 12% a year (no-growth multiple {dcf_factor(0.0, cfg, 0.12):.1f}x). Earnings come from "
                "Screener.in: a quarter more than twice the others is treated as a one-off and replaced, cyclicals use "
                "average EPS, and banks use adjusted book value (less unprovided bad loans) × ROE."),
              heading("How sensitive the answer is", 2),
              p("Two inputs drive a DCF: the growth rate and the required return. Here is Microsoft's value for "
                "different combinations, and the growth its price needs at each required return:"),
              table([["Required return", "No growth", "5% growth", "10% growth", "15% growth", "Growth the price needs"]] +
                    [[f"{rr*100:.0f}% a year"] + [m(msft["oe"] * dcf_factor(g, cfg, rr) + msft["nc"], nd=0) for g in (0, 0.05, 0.10, 0.15)]
                     + [pc(growth_needed(msft["oe"], msft["nc"], msft["price"], cfg, rr), 1, signed=True)] for rr in (0.08, 0.10, 0.12)],
                    [0.2, 0.15, 0.15, 0.15, 0.15, 0.2], right=(1, 2, 3, 4, 5)),
              callout("This is why the tool reports the growth needed rather than a single 'fair value': a value moves "
                      "with every assumption, while 'the price needs 17% a year for five years' is something you can "
                      "judge against the company's record. And it is why it asks for little or no growth (≤ 5%) before "
                      "calling a growth company cheap – the margin of safety is the growth you are not paying for.")]
    # 7 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("7. Profit growth vs price growth – the A to D grade"),
              p("A separate check asks whether the share price ran ahead of the business. Over about three years it "
                "compares how fast profit per share grew with how fast the share price grew, and works out how the "
                "P/E changed:"),
              formula("P/E change = ((1 + price growth a year) ÷ (1 + profit growth a year))^years − 1"),
              table([["Grade", "P/E change", "Meaning"],
                     ["A", "fell 25% or more", "Profits clearly outran the price – getting cheaper while improving"],
                     ["B", "fell up to 25%", "Profits grew a little faster than the price"],
                     ["C", "rose up to a third", "The price grew a little faster than profits"],
                     ["D", "rose more than a third", "The price ran well ahead of profits – a warning"],
                     ["n/m", "not meaningful", "A loss at the start or end, missing data, or an asset model (developers, holders)"]],
                    [0.1, 0.25, 0.65]),
              p("Cheap <i>and</i> grade A or B is the best combination: the price is low and the business is getting "
                "better. Cheap but grade D usually means profits have just jumped – check whether it lasts."),
              p("Where the figures come from: Yahoo Finance statements (diluted EPS) for US and other companies; "
                "Screener.in's own 3-year growth figures for the Nifty 50; and for the Nifty Midcap 150, the yearly and "
                "quarterly EPS already in the company files against the stored daily prices – the same method as Yahoo, "
                "with no extra downloads.", "small")]

    # 8 ------------------------------------------------------------------------------------------------
    gs, us_gs = cfg["growth_screen"], cfg["us_growth_screen"]
    mid = loader.load_companies(loader.companies_folder("midcap150"))
    mid_res = engine.run(mid, list(mid), cfg)
    screen = growth_screen.rows(mid_res, mid, cfg)
    picks = [x for x in screen if x["tier"] in ("shortlist", "near miss")]
    n_short = sum(1 for x in screen if x["tier"] == "shortlist")
    n_state = sum(1 for x in screen if x["tier"] == "shortlist" and x["state_owned"])
    ex_t = next((x["ticker"] for x in screen if x["tier"] == "shortlist" and x["cyclical"]),
                next((x["ticker"] for x in screen if x["tier"] == "shortlist"), None))
    ex, ex_r = next(x for x in screen if x["ticker"] == ex_t), mid_res[ex_t]
    ex_g = min(ex["eps_cagr_5y"], ex["eps_cagr_3y"])
    ex_future = ex["eps"] * (1 + ex["assumed_growth"]) ** gs["years"] * gs["exit_multiple"] + ex["nc"]
    inr = lambda x, nd=2: m(x, "INR", nd)  # noqa: E731
    v2x = ex_r.get("v2") or {}
    ok = lambda passed: "passes" if passed else "fails"  # noqa: E731
    flags_txt = lambda x: ", ".join(x["flags"]) or "–"  # noqa: E731
    story += [PageBreak(), heading("8. The growth screen – Dr. Amit Gupta's filter and rules"),
              p("The reverse DCF asks whether a price is cheap. <b>Dr. Amit Gupta's filter</b> asks a sharper question: "
                "<b>has this company grown fast for years, and is it still priced as if it will not?</b> It looks for "
                "growth at a value price – a business whose earnings per share have compounded at 20% a year or more, "
                "bought at a P/E of 15 or less – and checks that holding it for five years should pay at least 12% a "
                "year even if growth halves."),
              p("The screen runs on every company in the Nifty Midcap 150 and the Nifty 50, and – a little looser – on "
                "the S&amp;P 500 and Nasdaq-100 screen and the tech list. It sits <i>on top of</i> the valuation: it never "
                "changes the green / blue / red signal, which is shown beside it."),
              table([["Rule", "India (Midcap 150, Nifty 50)", "US (S&amp;P 500 + Nasdaq-100, tech)", "Why"],
                     ["P/E", f"≤ {gs['max_pe']}", f"≤ {us_gs['max_pe']}",
                      "Price minus net cash ÷ the EPS the valuation uses (one-offs removed, cyclicals averaged)"],
                     ["EPS growth a year", f"≥ {gs['min_eps_cagr']*100:.0f}% over <b>both</b> 5 and 3 years",
                      f"≥ {us_gs['min_eps_cagr']*100:.0f}% over both", "A 5-year window that starts in a bad year (2021) flatters the rate; the 3-year one checks growth is still there"],
                     ["Every year profitable", "Yes", "Yes", "Growth measured from a loss means nothing"],
                     ["5-year hold return", f"≥ {gs['min_return']*100:.0f}% a year", f"≥ {us_gs['min_return']*100:.0f}% a year",
                      "The discount rate: the hold must at least pay for the risk"],
                     ["Guards", f"cash conversion ≥ {gs['min_cash_conversion']*100:.0f}%, no demerger or one-off history, "
                      "no bad-loan warning, current results", "the same", "A fail here keeps a company off the list whatever its P/E"],
                     ["Flags (shown, not rules)", f"promoters below {gs['min_promoter']*100:.0f}% or down more than "
                      f"{gs['promoter_drop']*100:.0f} points in a year; state-owned; cyclical", "insiders shown; cyclical",
                      "Things to read before acting"]],
                    [0.17, 0.27, 0.2, 0.36]),
              formula(f"Assumed growth = half the past growth (the lower of the 5- and 3-year rates), at most "
                      f"{gs['max_assumed_growth']*100:.0f}% a year<br/>"
                      f"Value after {gs['years']} years = EPS × (1 + assumed growth)^{gs['years']} × {gs['exit_multiple']} + net cash per share<br/>"
                      f"Return a year = (value after {gs['years']} years ÷ price today)^(1/{gs['years']}) − 1"),
              p(f"For Indian companies P/E 15 is exactly the price at which earnings need "
                f"{growth_needed(1, 0, 15, cfg, 0.12)*100:.0f}% growth a year (the 12% DCF of section 5) – the green line. "
                f"So the screen asks for a company that has grown at 20% or more but is priced as if it will grow at 5%. "
                f"Halving the past growth in the return is the margin of safety: fast growth rarely lasts five more years."),
              p(f"<b>Shortlist</b> = passes everything. <b>Near miss</b> = the guards pass and one thing is short: a P/E of "
                f"{gs['max_pe']}–{gs['near_max_pe']} with the growth met, growth of {gs['near_min_eps_cagr']*100:.0f}–"
                f"{gs['min_eps_cagr']*100:.0f}% with the P/E met, or only the return bar."),
              KeepTogether([heading(f"Worked example: {ex_r['name']} ({ex_t})", 2),
              steps([("EPS the valuation uses", v2x.get("how") or "12-month EPS, one-offs removed", inr(ex["eps"])),
                     ("Net cash per share", "cash − debt, per share", inr(ex["nc"])),
                     ("P/E", f"({inr(ex['price'])} − {inr(ex['nc'])}) ÷ {inr(ex['eps'])} – {ok(ex['checks']['pe'])} ≤ {gs['max_pe']}", f"{ex['pe']:.1f}"),
                     ("EPS growth, 5 and 3 years", f"every year profitable: {'yes' if ex['every_year_positive'] else 'no'} – "
                      f"{ok(ex['checks']['growth'])} ≥ {gs['min_eps_cagr']*100:.0f}%",
                      f"{pc(ex['eps_cagr_5y'], 0, True)} / {pc(ex['eps_cagr_3y'], 0, True)}"),
                     ("Assumed growth", f"half of {pc(ex_g, 0)} = {pc(ex_g / 2, 1)}, at most {gs['max_assumed_growth']*100:.0f}%", pc(ex["assumed_growth"], 1)),
                     (f"Value after {gs['years']} years", f"{inr(ex['eps'])} × {1 + ex['assumed_growth']:.2f}^{gs['years']} × {gs['exit_multiple']} + {inr(ex['nc'])}", inr(ex_future, 0)),
                     ("Return a year", f"({inr(ex_future, 0)} ÷ {inr(ex['price'])})^(1/{gs['years']}) − 1 – {ok(ex['checks']['return'])} ≥ {gs['min_return']*100:.0f}%",
                      pc(ex["expected_return"], 1, True)),
                     ("Guards", f"cash conversion {pc(ex_r.get('cash_conversion'), 0)}" + (f"; {', '.join(ex['guards'])}" if ex["guards"] else " – all pass"), ex["tier"].capitalize() or "–"),
                     ("Signal beside it", f"flags: {flags_txt(ex)}", ex["action"])])]),
              callout(f"{b('A shortlist is not a buy.')} {ex_t} passes every rule, yet its signal is capped at blue: it is "
                      "cyclical, and its 12-month EPS is near the top of the cycle. The valuation already halves the "
                      "difference by averaging with the 5-year EPS, and the growth rates themselves start near the 2021 "
                      "low. The screen finds the candidates; the cycle, the promoters and the latest results decide.",
                      colour=AMBER, background="#FBF6EA") if ex["cyclical"] else Spacer(1, 2),
              heading(f"The Midcap 150 screen on {today:%d %B %Y}", 2),
              table([["Company", "Screen", "P/E", "EPS growth 5 / 3 yrs", "Return a year", "Flags", "Signal"]] +
                    [[f"{x['ticker']} – {x['name']}", x["tier"].capitalize(), f"{x['pe']:.1f}",
                      f"{pc(x['eps_cagr_5y'], 0, True)} / {pc(x['eps_cagr_3y'], 0, True)}", pc(x["expected_return"], 1, True),
                      flags_txt(x), x["action"]] for x in picks],
                    [0.24, 0.1, 0.07, 0.14, 0.1, 0.22, 0.13], right=(2, 3, 4)),
              p(f"{n_short} of {len(screen)} companies are on the shortlist" +
                (f", and {'all of them' if n_state == n_short else n_state} {'are' if n_state != 1 else 'is'} state-owned. A state-owned company's promoter is the government, so a high "
                 "promoter holding means control rather than a founder with money at stake – and a state-owned bank's "
                 "growth since 2021 is mostly its bad-loan clean-up: a cycle, not a franchise." if n_state else ".")),
              heading("The settings panel and the backtest", 2),
              p("Above the screen in each report, sliders change the rules – the P/E, the growth, the return, the "
                "holding years, the exit multiple, the promoter rule, leaving out state-owned companies or cyclicals – and "
                "the table re-sorts at once, with a funnel showing how many companies survive each step. <i>Reset to "
                "Dr. Gupta's rules</i> goes back to the defaults above."),
              p("Below the screen, a <b>backtest</b> applies the same rules 5, 4, 3 and 2 years ago with only what was "
                "known then, and follows each pick to today against every company screened and the index. Read it with "
                "care: it uses <b>today's</b> index members (the index of five years ago is not in the data), so every "
                "average is flattered – compare the picks with <i>all screened</i>, not with the index. A few years and a "
                "few dozen picks prove little; past performance only.")]

    # 8 (cont.) – the same idea as a Screener.in query, and how it compares with the rules above
    query = ["Price to Earning &lt; 15 AND", "EPS growth 5Years &gt; 20 AND", "EPS growth 3Years &gt; 20 AND",
             "Profit after tax &gt; 0 AND", "Net profit preceding year &gt; 0 AND", "Profit growth 5Years &gt; 20 AND",
             "Profit growth 3Years &gt; 20 AND", "", "Sales growth 5Years &gt; 12 AND",
             "Return on capital employed &gt; 15 AND", "Debt to equity &lt; 1 AND", "Interest Coverage Ratio &gt; 3 AND",
             "Free cash flow 3years &gt; 0 AND", "Pledged percentage &lt; 10 AND", "Is not SME"]
    story += [heading("The same idea on Screener.in – and how it compares", 2),
              p("Screener.in can run a version of the filter as a query over every listed company. The first block is "
                "Dr. Gupta's rules as far as Screener's fields allow; the second adds checks for the gaps (field names "
                "as Screener's autocomplete shows them; the extra thresholds are suggestions, not rules)."),
              callout("<font name='Courier' size='8.5'>" + "<br/>".join(query) + "</font>", colour=AMBER, background="#FBF6EA"),
              table([["Added check", "Why it helps"],
                     ["Sales growth 5 years &gt; 12%", "Profit growth should come from a growing business, not margin "
                      "gains or a one-off. Profit up 20% a year on flat sales rarely lasts."],
                     ["ROCE &gt; 15%", "Growth that earns a poor return on capital does not compound much."],
                     ["Debt to equity &lt; 1, interest cover &gt; 3", "Keeps out growth paid for with debt – where cheap-P/E traps often hide."],
                     ["Free cash flow over 3 years &gt; 0", f"The nearest Screener field to the cash-conversion guard "
                      f"(≥ {gs['min_cash_conversion']*100:.0f}%), which it cannot express. Much weaker."],
                     ["Pledged percentage &lt; 10%", "Pledged promoter shares are a common red flag in Indian midcaps."],
                     ["Is not SME", "Leaves out thinly traded SME-platform stocks."],
                     ["Optional, to sort by", f"Promoter holding &gt; {gs['min_promoter']*100:.0f} and change in promoter "
                      f"holding &gt; −{gs['promoter_drop']*100:.0f} (the flags row); PEG &lt; 0.75 as a rough stand-in for "
                      f"the {gs['min_return']*100:.0f}% return test."]],
                    [0.3, 0.7]),
              p("Each condition shrinks the list. If it comes back nearly empty, relax ROCE and sales growth first – "
                "they are additions, not Dr. Gupta's rules.", "small"),
              table([["Area", "This screener (Dr. Gupta's rules)", "Screener.in query"],
                     ["P/E", f"≤ {gs['max_pe']} on price minus net cash, one-offs removed, cyclicals averaged",
                      "&lt; 15 on reported 12-month earnings"],
                     ["Growth", f"EPS ≥ {gs['min_eps_cagr']*100:.0f}% a year over both 5 and 3 years",
                      "The same, plus profit growth and sales growth"],
                     ["Every year profitable", "Checked for every year", "Only the last two years; growth is a partial stand-in"],
                     [f"{gs['years']}-year hold return", f"≥ {gs['min_return']*100:.0f}% a year even if growth halves – built in",
                      "Missing"],
                     ["Cash conversion", f"≥ {gs['min_cash_conversion']*100:.0f}% – a hard rule",
                      "Free cash flow positive over 3 years – much weaker"],
                     ["Guards", "Demerger or one-off history, bad-loan warnings, current results", "Missing"],
                     ["Flags", "Promoter holding and its change, state-owned, cyclical", "Pledging only (promoter holding optional)"],
                     ["Universe", "Midcap 150 and Nifty 50 directly", "Every listed company; the index only by market value or by hand"],
                     ["Quality and safety", "Not in the rules", "Extra: ROCE, debt to equity, interest cover"]],
                    [0.2, 0.42, 0.38]),
              p("<b>Where the Screener.in query is stronger:</b> it adds checks the rules do not have – ROCE, debt, "
                "interest cover and sales growth – which catch growth bought with debt or driven by margins alone. It is "
                "instant and covers every listed company."),
              p("<b>Where this screener is stronger:</b> a more honest P/E (net cash, one-offs, cyclicals); the "
                f"{gs['min_return']*100:.0f}% return test, which is the point of \"growth priced as if it will not "
                "continue\"; and the guards against one-offs and demergers, the main cause of false positives."),
              callout(f"{b('Use both.')} The Screener.in query is the wide net: more names, with some false positives – "
                      "cyclicals at peak earnings, one-off profit jumps. This screener is the final check: fewer names, "
                      "cleaner ones. The three extras worth adding to these rules later are ROCE, debt to equity and "
                      "interest cover.")]

    # 9 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("9. Part B – miners: owner earnings, the number everything is built on"),
              p("Reported profit is a good start but has two problems for a mining company. First, it subtracts "
                "<b>depreciation</b>, an accounting charge for mines and trucks bought in the past – not cash spent "
                "this year. Second, it ignores the cash a mine must spend every year just to keep producing "
                "(<b>sustaining capex</b>: new equipment, underground development, tailings dams). Buffett's "
                "<b>owner earnings</b> fix both:"),
              formula("Owner earnings = adjusted net income + depreciation &amp; amortisation − sustaining capex"),
              p("It answers a simple question: <i>how much cash could the owners take out each year and still have "
                "the same business next year?</i> Growth capex (a new mine) is left out on purpose – it buys future "
                "earnings that are not in today's value yet. Where a company reports operating cash flow before "
                "working-capital swings (oil producers), the tool uses that minus capex instead."),
              p("A quarter's owner earnings are multiplied by 4 (by 2 for a half-year) to get a yearly figure, then "
                "divided by the number of shares to get owner earnings <b>per share</b>."),
              heading("Re-pricing to today's metal price", 2),
              p("A quarter's profit was earned at that quarter's metal price. If gold has since fallen, next quarter "
                "will earn less. So the tool re-prices: for each metal, it takes the ounces (or pounds) sold, adjusts "
                "for royalties and tax, and moves earnings by the gap between today's spot price and the price the "
                "company actually realised."),
              formula("Change in owner earnings per share = ounces sold per year × (1 − royalty) × (1 − tax rate) "
                      "÷ shares × (spot − realised price)"),
              p("This is why a gold miner's value moves with the gold price in every report, and why the stress test "
                "(section 12) can show the value at a lower gold price.")]

    # 10 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("10. What 12x, 15x and 25x mean"),
              p("A <b>multiple</b> is how many years of today's earnings you pay for. Paying 12x owner earnings means "
                "that if earnings stayed exactly the same, the business would pay you back in 12 years. Turn it "
                "upside down and you get the <b>earnings yield</b>: 1 ÷ 12 = 8.3% a year on your money."),
              figure(chart_multiples(), height_ratio=0.36),
              table([["Multiple", "Earnings yield", "What the tool uses it for", "Why this number"],
                     [f"{lo}x", f"{100/lo:.1f}%", "<b>Cautious value</b> of a producer. The margin of safety is measured from here.",
                      "Mines run out and metal prices swing, so a mining business deserves a lower multiple than a steady "
                      "consumer company. 8.3% a year is a fair return for that risk."],
                     [f"{hi}x", f"{100/hi:.1f}%", "<b>Fair value</b> of a producer. Tier A companies may start buying here.",
                      "What a good, steady miner or royalty company usually trades at in normal times."],
                     [f"{sell}x", f"{100/sell:.1f}%", "<b>Sell zone</b> – at or above this, don't add; consider selling.",
                      "Only 4% a year on today's earnings: the price is betting on much higher metal prices or growth."],
                     ["10x and 13x", "10.0% and 7.7%", "Oil and gas producers (cash-flow model): cautious and fair.",
                      "Oil is more cyclical than gold and reserves deplete faster, so lower multiples."],
                     [f"{f0:.1f}x", f"{100/f0:.1f}%", "Growth companies with no growth (sections 4 and 5).",
                      "What a business is worth at a 10% return if earnings never grow: 5 years of earnings plus a "
                      "15x exit, discounted at 10% a year."]],
                    [0.11, 0.12, 0.37, 0.40]),
              callout("For comparison: the S&amp;P 500 has usually traded between 15x and 25x earnings. Asking for 12x on a "
                      "miner – and then a further 20% discount – is deliberately strict. It is meant to leave room for "
                      "being wrong about the metal price, the costs or the mine.")]

    # 11 ------------------------------------------------------------------------------------------------
    e = c_ogc["earnings"]
    oe_q = e["adj_net_income"] + e["da"] - e["sustaining_capex"]
    gold = next(t for t in ogc["terms"] if t["metal"] == "gold")
    copper = next(t for t in ogc["terms"] if t["metal"] == "copper")
    story += [PageBreak(), heading("11. Producers, royalty and streaming companies"),
              p("Most companies in the core and miners lists are <b>producers</b>: they run mines that already sell "
                "metal. Royalty and streaming companies (Franco-Nevada, Wheaton, Royal Gold) are valued the same way – "
                "they receive a share of other companies' production, with almost no costs of their own."),
              formula(f"Value at {lo}x = owner earnings per share (at spot) × {lo} + net cash per share<br/>"
                      f"Value at {hi}x = owner earnings per share × {hi} + net cash per share<br/>"
                      f"Sell zone from = owner earnings per share × {sell} + net cash per share<br/>"
                      f"Margin of safety = 1 − price ÷ value at {lo}x"),
              p("Net cash is added because an owner of the whole company would also own its bank balance (and owe "
                "its debts)."),
              heading(f"Worked example: OceanaGold (OGC), {c_ogc['period']['label']}", 2),
              p("From the company's results release: adjusted net profit "
                f"{m(e['adj_net_income'], nd=1)}m, depreciation {m(e['da'], nd=1)}m, sustaining capex "
                f"{m(e['sustaining_capex'], nd=1)}m, {c_ogc['shares_m']:.1f}m shares, cash "
                f"{m(c_ogc['balance']['cash'], nd=1)}m and no debt; {c_ogc['metals'][0]['units']*1000:.1f} thousand oz of gold "
                f"sold at {m(c_ogc['metals'][0]['realised'], nd=0)} and {c_ogc['metals'][1]['units']:.1f}m lb of copper "
                f"at {m(c_ogc['metals'][1]['realised'])}; AISC {m(c_ogc['metals'][0]['aisc'], nd=0)}/oz."),
              steps([("Owner earnings for the quarter", f"{e['adj_net_income']:.1f} + {e['da']:.1f} − {e['sustaining_capex']:.1f}", f"{m(oe_q, nd=1)}m"),
                     ("A full year", f"× 4 quarters ÷ {c_ogc['shares_m']:.1f}m shares", f"{m(ogc['oe_rep'])} / share"),
                     ("Re-price gold to spot", f"gold {m(gold['realised'], nd=0)} → {m(gold['spot'], nd=0)}: "
                      f"{gold['sens']*1000:.3f} per $1,000 × {gold['spot']-gold['realised']:+,.0f}", f"{m(gold['delta'])}"),
                     ("Re-price copper to spot", f"copper {m(copper['realised'])} → {m(copper['spot'])}", f"{m(copper['delta'])}"),
                     ("Owner earnings at spot", "step 2 + steps 3 and 4", f"{m(ogc['oe'])} / share"),
                     ("Net cash per share", f"{c_ogc['balance']['cash']:.1f} − {c_ogc['balance']['debt']:.1f} ÷ {c_ogc['shares_m']:.1f}", m(ogc["nc"])),
                     (f"Value at {lo}x (cautious)", f"{ogc['oe']:.2f} × {lo} + {ogc['nc']:.2f}", m(ogc["v_low"])),
                     (f"Value at {hi}x (fair)", f"{ogc['oe']:.2f} × {hi} + {ogc['nc']:.2f}", m(ogc["v_high"])),
                     (f"Sell zone from ({sell}x)", f"{ogc['oe']:.2f} × {sell} + {ogc['nc']:.2f}", m(ogc["v_sell"])),
                     ("Margin of safety", f"1 − {ogc['price']:.2f} ÷ {ogc['v_low']:.2f}", pc(ogc["margin_of_safety"])),
                     ("Buy level", f"value at {lo}x × (1 − 20%)", m(ogc["buy_level"])),
                     ("Cost check", f"AISC {c_ogc['metals'][0]['aisc']:,} ÷ gold spot {spot['gold']:,}", pc(ogc["cost_ratio"]))]),
              figure(chart_ladder(ogc, "USD", "OceanaGold"), width_frac=0.8, height_ratio=0.26),
              p(f"The price ({m(ogc['price'])}) is {pc(ogc['margin_of_safety'])} below the cautious value, more than "
                f"the 20% asked for, and costs are {pc(ogc['cost_ratio'])} of the gold price, under the 60% limit – so "
                f"the signal is {b(ogc['signal'])} ({ogc['action']}). In plain words: at today's gold price the "
                f"company earns about {m(ogc['oe'])} a share a year for its owners and holds {m(ogc['nc'])} a share "
                f"in cash, yet the share costs {m(ogc['price'])} – about {ogc['pe']:.1f} years of owner earnings after "
                "taking off the cash.")]

    # 12 ------------------------------------------------------------------------------------------------
    st = ogc.get("stress") or []
    story += [PageBreak(), heading("12. Tiers, cost checks and stress tests"),
              heading("Tiers – how strict to be", 2),
              p("Not every miner deserves the same caution. The settings file sorts companies into three tiers:"),
              table([["Tier", "Who", "Buy rule"],
                     ["A", "Large, low-cost producers and royalty companies with strong balance sheets (e.g. Newmont, "
                      "Agnico Eagle, Franco-Nevada, Wheaton)", f"Start at or below the {hi}x value; add at or below the {lo}x value"],
                     ["B", "Mid-sized producers", f"Buy only with a 20% margin of safety at {lo}x"],
                     ["C", "Juniors, developers, single-asset or speculative companies", "Same strict rule; small positions only"]],
                    [0.08, 0.55, 0.37]),
              p(f"Example – Newmont (tier A): value at {lo}x {m(nem['v_low'])}, at {hi}x {m(nem['v_high'])}, price "
                f"{m(nem['price'])}. The price is above the {lo}x value (margin {pc(nem['margin_of_safety'], signed=True)}) but "
                f"below the {hi}x value, so a tier A company is a {b(nem['action'])}: start a small position now, add "
                f"below {m(nem['add_level'])}."),
              heading("The cost check (AISC)", 2),
              p(f"A miner whose all-in costs are close to the metal price has no cushion: a small fall in the price "
                f"wipes out its profit. So a producer can only be green if its AISC is at most "
                f"{z['max_cost_ratio']*100:.0f}% of spot. Otherwise it shows 'WATCH (high cost)', however cheap it looks."),
              heading("The stress test", 2),
              p("Every gold producer's value is also worked out at lower gold prices (the settings use "
                + ", ".join(m(g, nd=0) for g in cfg.get("stress_gold", [])) + "). For OceanaGold: "
                + "; ".join(f"at gold {m(g, nd=0)} the {lo}x value would be {m(v)}" for g, v, _ in st)
                + f". The report also shows the <b>gold price the share price already assumes</b>: OceanaGold's price "
                f"is justified at {lo}x if gold is about {m(ogc['implied_metal_lo'], nd=0)}. When that is well below "
                "spot, the market is pricing in a big fall in the metal – a sign of value."),
              heading("Price cases – the value at other metal prices", 2),
              p("Core company pages add a table of the value at fixed metal prices (gold "
                + ", ".join(m(g, nd=0) for g in cfg.get("price_cases", {}).get("gold", []))
                + ", with similar cases for silver and uranium), one metal at a time, with the company's own model re-run "
                "at each price. It is an assumption, not a reported figure, and the headline value never changes. Read it "
                "as what you would have to believe about the metal price for the share price to make sense."),
              p("Cameco shows why a straight 'pounds × price' sum can mislead. It sells mostly under long-term contracts "
                "with floors and ceilings, so its realised price lags spot. Its quarterly report publishes a table of the "
                "realised price it expects at each spot price, year by year, and the price cases use that table. "
                f"The {lo}x value: "
                + "; ".join(f"uranium at {m(row['price'], nd=0)}: {m(row['values'][0])}"
                            for row in (ccj_cases[0]["rows"] if ccj_cases else []))
                + f" (price {m(ccj['price'])}). Cameco's own figures show that a higher uranium price lowers this "
                "year's earnings slightly, because its purchases cost more while ceilings cap what it sells for."),
              heading("Forward – the company's own estimates", 2),
              p("A few company files also carry a forward year, built line by line from the company's outlook, capital "
                "plan and contract table – every line with its source. It sits beside the trailing value as 'company "
                "estimates – assumption, not reported'; analyst consensus is shown as a reference row and never used in "
                "a value. Two checks come first: the same inputs must reproduce the company's reported results, and "
                "their result is compared with consensus."),
              p(f"Cameco: trailing owner earnings {m(ccj['oe'])} a share ({lo}x value {m(ccj['v_low'])}); "
                + "; ".join(f"{y['year']} from its own estimates {m(y['oe_ps'])} a share ({lo}x {m(y['values'][0])}, "
                            f"{hi}x {m(y['values'][1])})" for y in ccj.get("forward", []))
                + f". Even on Cameco's own forward numbers the share at {m(ccj['price'])} costs far more than "
                f"{hi}x owner earnings. Analyst consensus is higher still, so the market is paying for growth the "
                "company has not yet put in its guidance."),
              heading("Cyclical and other caps", 2),
              p("Some green signals are capped at blue: companies in cyclical industries (oil, chemicals, steel) "
                "because their good years do not last, and companies whose operating cash has been below 70% of "
                "their reported profit over five years, because the profit is not turning into cash. Stale data – "
                "results older than about 100 days, or a newer report already out – turns a buy into 'refresh data'.")]

    # 13 ------------------------------------------------------------------------------------------------
    ec = c_cnq["earnings"]
    en = c_cnq.get("earnings_normalised", {})
    story += [PageBreak(), heading("13. Oil and gas producers – the cash-flow model"),
              p("Oil companies report large swings in profit from hedges, impairments and the oil price. The steadier "
                "measure is cash: <b>operating cash flow before working-capital changes, minus all capex</b>. Because "
                "oil is very cyclical, the tool can also rank on a <b>normalised</b> figure – an average of about four "
                "years – so one boom year does not make a company look cheap."),
              formula("Value at 10x = (cash flow before working capital − capex) per share × 10 + net cash per share<br/>"
                      "Value at 13x = the same × 13 · margin of safety and buy level as for miners"),
              heading("Worked example: Canadian Natural Resources (CNQ)", 2),
              steps([("Cash flow before working capital, last 12 months", "from the results", f"C${ec['cfo_ex_wc']:,.0f}m"),
                     ("Capex", "all capital spending", f"C${ec['capex']:,.0f}m"),
                     ("Normalised (4-year average) instead", "used for the value because of the cycle",
                      f"C${en.get('cfo_ex_wc', 0):,.0f}m − C${en.get('capex', 0):,.0f}m"),
                     ("Per share", f"÷ {c_cnq['shares_m']:,.0f}m shares", m(cnq["oe"], "CAD")),
                     ("Net cash (here net debt) per share", f"({c_cnq['balance']['cash']:,.0f} − {c_cnq['balance']['debt']:,.0f}) ÷ shares", m(cnq["nc"], "CAD")),
                     ("Value at 10x", f"{cnq['oe']:.2f} × 10 {cnq['nc']:+.2f}", m(cnq["v_low"], "CAD")),
                     ("Value at 13x", f"{cnq['oe']:.2f} × 13 {cnq['nc']:+.2f}", m(cnq["v_high"], "CAD")),
                     ("Margin of safety", f"1 − {cnq['price']:.2f} ÷ {cnq['v_low']:.2f}", pc(cnq["margin_of_safety"], signed=True))]),
              p(f"At {m(cnq['price'], 'CAD')} the price is above both values, so the signal is {b(cnq['signal'])} "
                f"({cnq['action']}). Debt matters a lot for oil companies: CNQ's net debt takes "
                f"{m(-cnq['nc'], 'CAD')} a share off the value.")]

    # 14 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("14. Developers, physical metal holders and other special cases"),
              heading("Developers – a mine that does not exist yet", 2),
              p("A developer has a project but no production, so it has no earnings to multiply. Instead the tool uses "
                "the company's own <b>feasibility study</b>, which gives the project's NPV (the value today of all its "
                "future cash flows, discounted at usually 5–8%) at several metal prices. The tool reads the NPV at "
                "today's spot from that curve, adds net cash, and divides by shares to get <b>NAV per share</b>."),
              formula("NAV per share = (project NPV at spot × ownership + net cash) ÷ shares<br/>"
                      f"Buy if price ÷ NAV ≤ {z['developer_buy_pnav']} · sell zone from {z['developer_sell_pnav']}"),
              figure(chart_nav(), height_ratio=0.2),
              p(f"Example – AbraSilver (ABRA): NAV {m(abra['nav'], 'CAD')} a share against a price of "
                f"{m(abra['price'], 'CAD')}, so price ÷ NAV = {abra['pnav']:.2f} – {b(abra['action'])}. "
                "Why ask for 0.8 or less? A study NPV is before financing (often new shares), construction overruns "
                "and country risk; most developers trade well below NAV until the mine is built. A developer is "
                "always tier C."),
              heading("Physical metal holders – SPUT, Yellow Cake", 2),
              p("These funds simply own metal (uranium) in a vault. Their value is the metal at spot plus cash, per "
                "unit – the NAV. Buying below NAV means getting metal at a discount."),
              p(f"Example – Sprott Physical Uranium Trust: NAV {m(sput['nav'])} a unit at uranium "
                f"{m(spot['uranium'], nd=0)}/lb, price {m(sput['price'])}, so price ÷ NAV = {sput['pnav']:.2f}. "
                f"Buy at or below {z['physical_buy_pnav']} ({m(sput['buy_level'])}), sell zone from "
                f"{z['physical_sell_pnav']} – {b(sput['action'])}."),
              heading("Leases (Hut 8) and 'not valued' (UEC, UUUU)", 2),
              p("Data-centre leases are valued as contracts: the cash from signed leases, discounted, minus what is "
                "still to be built. Companies with neither earnings nor a single study (some uranium companies) are "
                "<b>not valued</b>; the report only shows their cash and inventory as a share of their market value, "
                "and the signal is red – there is no value to hold the price up.")]

    # 15 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("15. Quick screens vs full company files"),
              p("Building a full company file takes about ten minutes of reading a results release. To decide which "
                "companies deserve that time, the tool first runs <b>quick screens</b> over large lists – about 270 "
                "miners from seven ETFs and the 520 companies of the S&amp;P 500 and Nasdaq-100 – using Yahoo's or the "
                "SEC's figures:"),
              table([["", "Quick screen", "Full company file"],
                     ["Earnings", "Net profit of the last 12 months", "Owner earnings from the latest quarter (profit + D&amp;A − sustaining capex)"],
                     ["Metal price", "Not re-priced", "Re-priced to today's spot"],
                     ["Costs", "Not known", "AISC per ounce; checked against spot"],
                     ["One-offs", "Included", "Removed (adjusted profit)"],
                     ["Use", "A filter: which companies to look at", "A decision: buy, watch or sell"]],
                    [0.16, 0.37, 0.47]),
              callout(f"{b('Why it matters – B2Gold, November 2026.')} The quick screen showed B2Gold about 54% below its "
                      "12x value. The full file, from its Q3 results, counted $133m of sustaining capex and an AISC of "
                      "$2,602/oz – over 60% of the gold price – and re-priced to the lower spot price. The full value "
                      "put the price about 19% <i>above</i> the 12x value. A quick-screen green means "
                      "'make a full company file', never 'buy'.", colour=RED, background="#FDF0EE")]

    # 16 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("16. Reading a report, and a checklist before buying"),
              heading("The colours", 2),
              table([["Signal", "Means", "What to do"],
                     ["Green", "Price below the buy level (or tier A within its start zone); costs, data and cash checks pass",
                      "Candidate to buy – start with a third if the price trend is down"],
                     ["Blue", "Fair, watch, hold, or capped (cyclical, low cash conversion, high cost)", "Hold if owned; wait if not"],
                     ["Red", "Expensive (sell zone), no earnings, or not valued", "Don't add; review if owned"]],
                    [0.12, 0.5, 0.38]),
              p("Flags in [brackets] are warnings to read before acting: STALE (results out of date), price days old, "
                "cyclical, cash conversion, AISC above 60% of spot, debt above 3× EBITDA, shares up more than 10% in "
                "three years, one-off quarter removed."),
              heading("Checklist before buying", 2),
              table([["#", "Check"],
                     ["1", "The company has a full company file – not only a quick screen – with results less than ~100 days old"],
                     ["2", "The signal is green and the price is at or below the buy level"],
                     ["3", "Costs are well below the metal price (AISC ≤ 60% of spot) and debt is manageable"],
                     ["4", "The stress test value at a lower metal price is still near or above the price"],
                     ["5", "No heavy dilution; profits turn into cash; grade not D"],
                     ["6", "You have read the latest results release yourself: anything the numbers miss (a mine problem, "
                           "a government change, a large acquisition)?"],
                     ["7", "Position size: small for tier C; start with a third when the price is below its 200-day average"],
                     ["8", "Write down why you are buying and what would make you sell – the sell zone, or the thesis breaking"]],
                    [0.06, 0.94])]

    # 17 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("17. All formulas and settings in one place"),
              table([["What", "Formula"],
                     ["Owner earnings (period)", "adjusted net income + D&amp;A − sustaining capex (oil: cash flow before working capital − capex)"],
                     ["Owner earnings per share (year)", "period owner earnings × periods a year ÷ shares"],
                     ["Re-pricing per metal", "units × periods × (1 − royalty) × (1 − tax) ÷ shares × (spot − realised)"],
                     ["Net cash per share", "(cash − debt) ÷ shares"],
                     ["Producer values", f"OE × {lo} (cautious), × {hi} (fair), × {sell} (sell zone), each + net cash"],
                     ["Oil values", "cash flow per share × 10 and × 13, + net cash"],
                     ["Margin of safety", "1 − price ÷ cautious value"],
                     ["Buy level (B and C)", "cautious value × (1 − 20%)"],
                     ["Tier A levels", f"start ≤ {hi}x value, add ≤ {lo}x value"],
                     ["Developer NAV", "(NPV at spot × ownership + net cash) ÷ shares"],
                     ["Physical NAV", "units of metal × spot + other net assets, per unit"],
                     ["Growth value", "EPS × Σ((1+g)/(1+r))^t, t = 1–5, + 15 × ((1+g)/(1+r))^5, + net cash"],
                     ["Growth needed", "g where growth value = price"],
                     ["P/E change", "((1 + price growth)/(1 + profit growth))^years − 1"],
                     ["Growth screen P/E", "(price − net cash) ÷ the EPS the valuation uses"],
                     ["Growth screen return", "((EPS × (1 + assumed growth)^5 × 15 + net cash) ÷ price)^(1/5) − 1; "
                      "assumed growth = half the lower of the 5- and 3-year EPS growth, at most 15%"]],
                    [0.3, 0.7]),
              table([["Setting (config.yaml)", "Value"],
                     ["Producer multiples", f"{lo}x cautious, {hi}x fair, {sell}x sell zone"],
                     ["Oil multiples", "10x cautious, 13x fair"],
                     ["Margin of safety to buy", f"{z['buy_margin_of_safety']*100:.0f}%"],
                     ["Highest AISC for a buy", f"{z['max_cost_ratio']*100:.0f}% of spot"],
                     ["Developer buy / sell", f"price ÷ NAV ≤ {z['developer_buy_pnav']} / ≥ {z['developer_sell_pnav']}"],
                     ["Physical holder buy / sell", f"price ÷ NAV ≤ {z['physical_buy_pnav']} / ≥ {z['physical_sell_pnav']}"],
                     ["Growth: buy / watch / sell", f"≤ {z['growth_buy']*100:.0f}% / ≤ {z['growth_watch']*100:.0f}% / ≥ {z['growth_sell']*100:.0f}% a year (tier A buy ≤ {z['growth_buy_tier_a']*100:.0f}%)"],
                     ["Discount rate", "10% (12% for India); 5 years then a 15x exit"],
                     ["Cash conversion floor", f"{z['min_cash_conversion']*100:.0f}% of profit over 5 years"],
                     ["Stale results", "older than 100 days (developers 200, physical holders 45)"],
                     ["Gold stress test", ", ".join(m(g, nd=0) for g in cfg.get("stress_gold", []))],
                     ["Growth screen – India (Dr. Gupta)", f"P/E ≤ {gs['max_pe']}, EPS growth ≥ {gs['min_eps_cagr']*100:.0f}% over 5 and 3 years, "
                      f"return ≥ {gs['min_return']*100:.0f}% a year; near miss: P/E ≤ {gs['near_max_pe']} or growth ≥ {gs['near_min_eps_cagr']*100:.0f}%; "
                      f"promoter flag below {gs['min_promoter']*100:.0f}%"],
                     ["Growth screen – US", f"P/E ≤ {us_gs['max_pe']}, EPS growth ≥ {us_gs['min_eps_cagr']*100:.0f}%, return ≥ {us_gs['min_return']*100:.0f}% a year; "
                      f"near miss: P/E ≤ {us_gs['near_max_pe']} or growth ≥ {us_gs['near_min_eps_cagr']*100:.0f}%"]],
                    [0.35, 0.65]),
              Spacer(1, 6),
              p("Educational framework, not investment advice. Numbers can be wrong: check every figure that matters "
                "against the company's own filing before acting.", "small")]

    # 18 ------------------------------------------------------------------------------------------------
    story += [PageBreak(), heading("18. Technical analysis – timing, not value"),
              p("Everything above works out what a company is <b>worth</b>. Technical analysis looks only at the "
                "<b>price</b>: its trend, its momentum and the levels where buyers and sellers have turned it before. In "
                "this tool it has one job – to help decide <b>when</b> and <b>how much</b> to buy a company the valuation "
                "already says is cheap. A good chart never makes an expensive company a buy, and a weak chart is not a "
                "reason to sell a cheap one."),
              table([["Term", "What it means", "How it is used here"],
                     ["Moving average (SMA 20 / 50 / 200)", "The average closing price of the last 20, 50 or 200 trading days",
                      "Price above a rising 200-day average = long-term uptrend. Below it = buy in thirds, not all at once"],
                     ["RSI(14)", "A 0–100 gauge of how strong the last 14 days' gains were against the losses",
                      "Under 30 = oversold, often a better entry for a cheap company; over 70 = overbought, wait for a pullback"],
                     ["MACD", "The gap between a fast and a slow moving average, and that gap's own trend", "Rising = momentum improving"],
                     ["Support and resistance", "Prices where the share has repeatedly stopped falling (support) or rising (resistance)",
                      "Places to start or add near support; a rally may stall at resistance"],
                     ["Trend line", "A line through rising lows (uptrend) or falling highs (downtrend)", "Shows whether a trend is still intact"],
                     ["Volume", "The number of shares traded each day", "Moves on heavy volume matter more than moves on thin trading"]], [0.22, 0.38, 0.40]),
              heading("What the reports do today", 2),
              p("With <i>run --technicals</i>, each company section shows the price against its 200-day average, RSI and "
                "MACD; below the 200-day average, buy in thirds. The model portfolios buy in full only at or above 95% of "
                "the 200-day average with a positive 6-month return; otherwise they start with a third."),
              heading("The price chart in every company section", 2),
              table([["Step", "What it adds"],
                     ["Price history", "10 years of daily open, high, low, close and volume, with splits and dividends, for the "
                                       "core, tech, oil and promoted miners lists"],
                     ["The chart", "RSI on top; daily / weekly / monthly candles with the 20-, 50- and 200-day averages; support and resistance found from the price's own turning points; trend lines through "
                      "rising lows or falling highs (marked 'auto'); and the valuation on it – the 12x–15x value band, buy, add and "
                      "sell-zone lines, today's signal, results (E) and dividend (D) markers – so you see where the price sits "
                      "against its value"],
                     ["Coming later", "Levels you are watching from your own research; a markets page (sector ratios such as junior silver vs gold miners, uranium miners vs "
                      "gold, gold vs silver), forward returns after past sell-offs, and a scorecard of whether the signals "
                      "and levels actually worked"]], [0.28, 0.72]),
              callout("How to combine the two: <b>valuation first</b> – only companies with a margin of safety are "
                      "candidates. <b>Then the chart</b> – buy a full position when the trend is up, or a third when the price "
                      "is still falling, adding near support or when the trend turns. Support near the buy level is the "
                      "strongest setup: the market and the valuation agree.")]

    doc = Doc(str(OUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=18 * mm,
              title="How Value Screener values a company", author="Value Screener")
    doc.multiBuild(story, onFirstPage=on_page, onLaterPages=on_page)
    return OUT


# ------------------------------------------------------------------------------------------------- the 3-page overview
def chart_flow():
    plt.rcParams["font.family"] = FAMILY
    fig, ax = plt.subplots(figsize=(7.4, 1.9), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2.2)
    ax.axis("off")
    boxes = [("Results", "last quarter's\nreported numbers", S.INK2), ("Owner\nearnings", "cash owners could\ntake out yearly", AMBER),
             ("× 12 / 15 / 25", "years of earnings\nyou pay for", AMBER), ("Value", "+ cash − debt,\nper share", BLUE),
             ("vs price", "how big is\nthe discount?", S.PRICE), ("Signal", "green · blue · red", GREEN)]
    w = 1.45
    for i, (t, sub, c) in enumerate(boxes):
        x = 0.1 + i * 1.66
        ax.add_patch(plt.Rectangle((x, 0.35), w, 1.5, fc="white", ec=c, lw=2))
        ax.text(x + w / 2, 1.42, t, ha="center", va="center", fontsize=9, weight="bold", color=S.INK, linespacing=1.0)
        ax.text(x + w / 2, 0.78, sub, ha="center", va="center", fontsize=7, color=S.INK2)
        if i < len(boxes) - 1:
            ax.annotate("", xy=(x + 1.66, 1.1), xytext=(x + w, 1.1), arrowprops=dict(arrowstyle="-|>", color=S.MUTED, lw=1.5))
    return _save(fig, "flow")


def build_overview():
    cfg = loader.load_config()
    cs = {**loader.load_companies(), **loader.load_companies(loader.companies_folder("miners"))}
    res = lambda t: engine.run(cs, [t], cfg)[t]  # noqa: E731
    ogc, msft = res("OGC"), res("MSFT")
    tech = sorted((res(t) for t in TECH if t in cs), key=lambda r: (r["implied_growth"] is None, r["implied_growth"] or 0))
    lo, hi = cfg["multiples"]["producer"]
    sell = cfg["multiples"]["sell"]
    z = cfg["zones"]
    f0 = dcf_factor(0.0, cfg)
    today = dt.date.today()
    story = [p("Value Screener in five minutes", "title"),
             p("How the reports decide whether a share is cheap – technology companies and miners – without formulas.", "subtitle"),
             Spacer(1, 6 * mm),
             heading("The idea", 2),
             p("A share is a piece of a business. Its <b>price</b> moves every day with fear and excitement; its "
               "<b>value</b> – what the business earns for its owners – moves slowly. The reports work out a "
               "<b>cautious value</b> for each company from what it actually reported, put it next to today's price, "
               "and only call it a buy when the price is well below the value. That gap is the <b>margin of safety</b>: "
               "the cushion that protects you when something goes wrong."),
             heading("Three rules", 2),
             table([["Rule", "What it means"],
                    ["Reported numbers only", "No forecasts, no price targets, no hoped-for growth – only what the company reported"],
                    ["Be cautious", "Pay for little or no growth; value mines at a low multiple with metal at today's price; "
                                    "ask for a discount on top"],
                    ["Same rules every time", "The thresholds are fixed in one settings file, not decided on the day"]], [0.28, 0.72]),
             heading("Two kinds of business, two yardsticks", 2),
             table([["", "Technology and growth companies (page 2)", "Miners, royalty and oil companies (page 3)"],
                    ["The question", "How fast must profits grow for today's price to make sense?",
                     "How much cash does the business produce at today's metal price?"],
                    ["The tool", "A reverse discounted cash flow (DCF)", "Owner earnings × 12 / 15 / 25 years"],
                    ["Cheap when", f"The price needs {z['growth_buy']*100:.0f}% growth a year or less",
                     "The price is at least 20% below the 12x value"],
                    ["Examples", "Microsoft, Nvidia, TSMC, ASML", "Newmont, OceanaGold, Wheaton, Canadian Natural"]],
                   [0.16, 0.42, 0.42]),
             p("Read the page you need: tech readers can skip page 3; a resource investor who looks at tech only when it "
               "is cheap can go straight to page 3 and use page 2 to spot the rare cheap tech name.", "small"),
             PageBreak(),
             heading("Technology and growth companies – the DCF in plain words", 2),
             p("<b>Money later is worth less than money now.</b> If you can earn 10% a year elsewhere, $100 promised in a "
               "year is worth about $91 today, and $100 in five years about $62. A <b>discounted cash flow (DCF)</b> "
               "uses this to value a business: take the profits it will earn each year, convert each into today's money, "
               "and add them up. The total is what the business is worth to someone who wants 10% a year."),
             figure(chart_discount(cfg["growth_dcf"]["discount_rate"]), width_frac=0.8, height_ratio=0.27),
             p(f"<b>The tool keeps it short and cautious:</b> five years of profits, then a sale at {cfg['growth_dcf']['exit_multiple']:.0f} "
               f"times that year's profit – what a mature business usually sells for. With no growth at all this makes a "
               f"business worth about {f0:.0f} times its profit; growth adds more."),
             p("<b>Then it turns the question around.</b> Guessing growth is where most valuations go wrong, so instead "
               "of asking 'what is it worth if it grows 15%?', the tool asks <b>'how much growth does today's price "
               "need?'</b> – the <b>growth needed</b>. That is easy to judge against the company's record."),
             p(f"<b>Example – Microsoft:</b> it earns about {m(msft['oe'])} a share a year. With no growth it would be "
               f"worth about {m(msft['v0'], nd=0)}; the price is {m(msft['price'], nd=0)}, which needs profits to grow about "
               f"{msft['implied_growth']*100:.0f}% a year for five years. Possible for Microsoft – but you are paying for "
               "that growth in advance, so there is no margin of safety."),
             table([["Growth the price needs", "Signal", "Meaning"],
                    [f"{z['growth_buy']*100:.0f}% a year or less", "Green", "Little growth paid for – cheap for a real business"],
                    [f"{z['growth_buy']*100:.0f}–{z['growth_sell']*100:.0f}%", "Blue", "A fair to full price; growth must continue"],
                    [f"{z['growth_sell']*100:.0f}% or more", "Red", "Only years of exceptional growth justify it"]], [0.28, 0.14, 0.58]),
             table([["Today", "P/E", "Growth needed", "Signal"]] +
                   [[f"{r['display_ticker']}", f"{r['pe']:.0f}x" if r.get("pe") else "–",
                     pc(r["implied_growth"], 0, signed=True) if r["implied_growth"] is not None else "–", r["action"]] for r in tech],
                   [0.2, 0.15, 0.25, 0.4], right=(1, 2)),
             p("Banks are valued on book value × their return on equity; cyclical companies (such as memory-chip makers) "
               "on average profits, and capped at blue because their good years do not last.", "small"),
             PageBreak(),
             heading("Miners, royalty companies and oil – owner earnings × years", 2),
             p("A mine's value is the cash it produces. <b>Owner earnings</b> = profit + depreciation − the spending needed "
               "just to keep producing: the cash owners could take out each year. It is re-priced to today's metal price, "
               "then multiplied by a number of years."),
             figure(chart_flow(), height_ratio=0.25),
             table([["Multiple", "You pay", "You earn a year", "In the reports"],
                    [f"{lo}x", f"{lo} years of earnings", f"{100/lo:.1f}%", "Cautious value – the margin of safety is measured from here"],
                    [f"{hi}x", f"{hi} years", f"{100/hi:.1f}%", "Fair value for a good miner or royalty company"],
                    [f"{sell}x", f"{sell} years", f"{100/sell:.1f}%", "Sell zone – the price is betting on much more"]], [0.12, 0.2, 0.18, 0.5]),
             p("Miners get low multiples because mines run out and metal prices swing. Oil producers use 10x and 13x "
               "of cash flow; developers (mines not built yet) are bought at 80% or less of their study value; metal "
               "holders such as Sprott Physical Uranium at 85% or less of the metal they hold.", "small"),
             p(f"<b>Example – OceanaGold:</b> at today's gold price it earns about {m(ogc['oe'])} a share a year for its "
               f"owners and holds {m(ogc['nc'])} a share in net cash. At {lo}x that is worth {m(ogc['v_low'])}; the share "
               f"costs {m(ogc['price'])} – {pc(ogc['margin_of_safety'])} below, with costs at {pc(ogc['cost_ratio'])} of the "
               f"gold price. Signal <b>{ogc['signal']}</b>; buy level {m(ogc['buy_level'])}, sell zone from {m(ogc['v_sell'])}."),
             figure(chart_ladder(ogc, "USD", "OceanaGold"), width_frac=0.85, height_ratio=0.28),
             heading("The growth screen – Dr. Amit Gupta's rules", 2),
             p("For Indian midcaps and the Nifty 50 (and, a little looser, US companies) a second filter looks for "
               "<b>growth at a value price</b>: earnings per share that have grown 20% a year or more over both five and "
               "three years, with a profit every year, bought at no more than 15 times earnings – a price that assumes "
               "only about 5% growth. It also checks that a five-year hold should still pay 12% a year if growth halves. "
               "Companies that pass go on a shortlist; one rule short makes a near miss. Like the quick screens, it "
               "finds candidates – a cyclical company at the top of its cycle can pass every rule and still be capped at "
               "blue."),
             PageBreak(),
             heading("The colours", 2),
             table([["Signal", "Means", "What to do"],
                    ["Green", "Below the buy level and the safety checks pass", "Candidate to buy – in thirds if the price is still falling"],
                    ["Blue", "Fair, watch or hold – or cheap but capped by a warning", "Hold if owned; wait if not"],
                    ["Red", "Expensive, no earnings, or no value to measure", "Don't add; review if owned"]], [0.12, 0.48, 0.4]),
             heading("Safety checks behind every green", 2),
             table([["Check", "Why"],
                    ["Profits turn into cash (≥ 70% over 5 years)", "Profit without cash is a warning sign"],
                    ["Debt, and new shares issued", "Both take value from existing owners"],
                    ["Mining costs well below the metal price (≤ 60%)", "A thin margin disappears when the metal price falls"],
                    ["Stress test at a lower gold price", "Shows what a miner is worth if gold drops"],
                    ["Fresh results", "Results older than about 100 days turn a buy into 'refresh data'"],
                    ["Profit vs price grade A–D", "Did the price run ahead of the business over three years?"]], [0.45, 0.55]),
             heading("Quick screens are a filter, not a decision", 2),
             p("To find candidates, the tool first runs rough screens over hundreds of companies – about 270 miners and "
               "the S&amp;P 500 and Nasdaq-100. They use simpler figures and can be badly wrong: in November 2026 B2Gold "
               "looked 54% cheap on the quick screen, but its full results showed it was about 19% <i>above</i> its "
               "cautious value. A quick-screen green means 'look closer', never 'buy'."),
             heading("Before you buy", 2),
             table([["#", "Check"],
                    ["1", "A full company file with recent results – not just a quick screen"],
                    ["2", "Green signal, price at or below the buy level"],
                    ["3", "Read the latest results yourself: anything the numbers miss?"],
                    ["4", "Small positions for speculative companies; buy in thirds while the price trend is down"],
                    ["5", "Write down why you are buying and what would make you sell"]], [0.06, 0.94]),
             heading("Technical analysis – timing, not value", 2),
             p("Valuation decides <b>what</b> to buy; the price chart helps decide <b>when</b> and <b>how much</b>. Today the "
               "reports show the price against its 200-day average, RSI and MACD, and buy in thirds while a cheap "
               "company's price is still below its 200-day average. Every company section also has a price chart: candles, "
               "the 20-, 50- and 200-day averages, RSI, the nearest support and resistance and trend lines – with the "
               "value and buy level drawn on it, so you see where the price sits against its value.", "small"),
             Spacer(1, 4),
             p("The detailed guide (Valuation_Guide.pdf) explains every term, formula and model with worked examples: "
               "Part A for technology and growth companies, Part B for miners, section 18 for technical analysis. Educational framework, not investment advice.", "small")]
    doc = SimpleDocTemplate(str(OVERVIEW), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm,
                            bottomMargin=18 * mm, title="Value Screener in five minutes", author="Value Screener")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return OVERVIEW

if __name__ == "__main__":
    print(build_overview())
    print(build())
