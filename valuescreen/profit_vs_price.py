"""Profit growth vs price growth: did the share price run ahead of the company's profits over about three years?

For each company: yearly growth in sales, profit and share price over the same years, and what that did to the P/E:

    P/E change = ((1 + price growth) / (1 + profit growth)) ^ years − 1

Grade A = P/E fell 25% or more (profits clearly outran the price) · B = fell up to 25% · C = rose up to a third
(roughly in line) · D = rose more than a third (price ran ahead of profits) · n/m = not comparable (a loss at either
end, or missing figures). Each row also shows the company's value-report signal, so "cheap and improving" (A/B +
green) and "expensive and stretched" (D + red) stand out.

Currencies: prices in the stock exchange's currency; sales and profits as the company reports them. Growth rates and
the P/E change do not depend on the currency.
Sources: Screener.in's compounded 3-year growth for Indian companies (net profit), Yahoo Finance's annual and
quarterly statements for the rest (diluted EPS, so buybacks and new shares count).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import style as S
from .pdf import Pill, Styles, _header, _widths, hexc, muted, new_document
from .wording import day, esc, money

ASSET_MODELS = {"developer": "a developer, valued on its study NAV, not profits",
                "physical": "holds the metal; profits are revaluations, so it is valued on NAV",
                "leases": "valued on contracted lease cash, not today's profits",
                "liquid": "no meaningful profits; not valued"}
GRADE_COLOUR = {"A": S.SIGNAL["green"], "B": "#4FA884", "C": "#B7791F", "D": S.SIGNAL["red"], "n/m": S.MUTED}
GRADE_TINT = {"A": S.TINT["green"][1], "B": S.TINT["green"][3], "C": "#FBF6EA", "D": S.TINT["red"][2], "n/m": S.SOFT}


# ------------------------------------------------------------------------------------------------- the numbers
def cagr(then, now, years):
    """Yearly growth from `then` to `now`; None when either end is not positive or the period is unknown."""
    if then is None or now is None or not years or then <= 0 or now <= 0:
        return None
    return (now / then) ** (1 / years) - 1


def pe_change(price_growth, profit_growth, years):
    if price_growth is None or profit_growth is None or not years:
        return None
    return ((1 + price_growth) / (1 + profit_growth)) ** years - 1


def grade(change):
    if change is None:
        return "n/m"
    return "A" if change <= -0.25 else "B" if change <= 0 else "C" if change <= 1 / 3 else "D"


def evaluate(rec: dict) -> dict:
    """Adds sales / profit / price growth, the P/E change and the grade to one company's raw record.

    Screener records carry Screener's own 3-year growth rates; Yahoo records carry the figures at both ends."""
    out = dict(rec)
    years = rec.get("years") or 3.0
    model = (rec.get("value") or {}).get("model")
    if model in ASSET_MODELS:   # profits here are revaluations or there are none – the value report uses assets instead
        return dict(out, years=years, sales_growth=None, profit_growth=None, pe_change=None, grade="n/m",
                    price_growth=rec.get("price_growth_3y") or cagr(rec.get("price_then"), rec.get("price"), years),
                    nm_reason=ASSET_MODELS[model])
    if rec.get("source") == "screener":
        sales, profit, price = rec.get("sales_growth_3y"), rec.get("profit_growth_3y"), rec.get("price_growth_3y")
        if rec.get("profit_then") is not None and rec["profit_then"] <= 0:
            profit = None   # growth from a loss means nothing
    else:
        sales = cagr(rec.get("sales_then"), rec.get("sales_now"), years)
        profit = cagr(rec.get("eps_then"), rec.get("eps_now"), years)
        price = cagr(rec.get("price_then"), rec.get("price"), years)
    change = pe_change(price, profit, years)
    out.update(years=years, sales_growth=sales, profit_growth=profit, price_growth=price, pe_change=change, grade=grade(change))
    if change is None:
        out["nm_reason"] = rec.get("nm_reason") or ("a loss or no profit at one end" if profit is None else "no price history")
    return out


def value_summary(r: dict) -> dict:
    """The value report's verdict for one company, as shown next to its grade."""
    m = r["model"]
    if m == "growth":
        g = r.get("implied_growth")
        detail = "no valid earnings" if g is None else f"needs {g*100:+.1f}%/yr"
    elif m in ("developer", "physical"):
        detail = f"{r['pnav']:.2f}× NAV"
    elif m == "leases":
        detail = f"{r['pnav']:.2f}× cautious value"
    elif m == "liquid":
        detail = "not valued"
    elif r.get("margin_of_safety") is None:
        detail = "no earnings"
    else:
        detail = f"price vs 15x: {money(r['price'], r['price_ccy'])} vs {money(r['v_high'], r['price_ccy'])}"
    return {"signal": r["signal"], "action": r["action"], "detail": detail, "model": m}


def rows(entries: list[dict], raw: dict, results: dict, companies: dict) -> list[dict]:
    """Evaluated rows for every list entry that has figures, best grade first. `results` are the value results."""
    out = []
    for entry in entries:
        t = entry["ticker"]
        if not raw.get(t):
            continue
        company = companies.get(t) or {}
        price_date = raw[t].get("price_date")
        out.append(evaluate({**raw[t], "ticker": t, "quantity": entry.get("quantity"),
                             "name": company.get("name") or entry.get("name") or raw[t].get("name", t),
                             "price_date": dt.date.fromisoformat(price_date) if isinstance(price_date, str) else price_date,
                             "value": value_summary(results[t]) if t in results else None}))
    return sorted(out, key=sort_key)


def sources_text(rows_: list[dict], as_of: dt.date) -> str:
    used = sorted({"Screener.in company pages (3-year compounded growth)" if r["source"] == "screener" else
                   "Yahoo Finance annual and quarterly statements and prices" for r in rows_})
    return "; ".join(used) + f", fetched {as_of:%d %b %Y}; value signals from this project's company files."


def comment(r: dict) -> str:
    if r["grade"] == "n/m":
        text = f"Not comparable: {r['nm_reason']}."
        if r.get("price_growth") is not None:
            text += f" Price {r['price_growth']*100:+.0f}%/yr."
    else:
        direction = "down" if r["pe_change"] < 0 else "up"
        text = (f"Profits {r['profit_growth']*100:+.0f}%/yr vs price {r['price_growth']*100:+.0f}%/yr – P/E {direction} "
                f"{abs(r['pe_change'])*100:.0f}% in {r['years']:.0f} years.")
    value = r.get("value")
    if value:
        text += {"green": " Cheap on the value report.", "red": " Expensive on the value report.",
                 "blue": " Watch / hold on the value report."}.get(value["signal"], "")
    return text + (f" {esc(r['note'])}" if r.get("note") else "")


# ------------------------------------------------------------------------------------------------- the PDF
def _amount(x, ccy, unit):
    if x is None:
        return "–"
    if unit == "cr":
        return f"{S.money(x, ccy, 0)} cr"
    millions = x / 1e6
    return f"{S.money(millions / 1000, ccy, 1)}bn" if abs(millions) >= 10000 else f"{S.money(millions, ccy, 0)}m"


def _pct(x, nd=0):
    return "–" if x is None else S.pct(x, nd) + "/yr"


def _row(r, st, widths, with_position):
    ccy = r["currency"]
    late = r.get("price_date") and (dt.date.today() - r["price_date"]).days > 7
    price = (f"{st.bold(money(r['price'], ccy))}<br/><font size='6.1' color='{'#B7791F' if late else S.MUTED}'>"
             f"{day(r.get('price_date'))}</font>")
    one_year = "<br/>" + muted(f"1 yr {S.pct(r['price_change_1y'])}", 5.9) if r.get("price_change_1y") is not None else ""
    unit = "cr" if r.get("source") == "screener" else "m"
    then_now = f"{_amount(r.get('profit_then'), r['report_ccy'], unit)} → {_amount(r.get('profit_now'), r['report_ccy'], unit)}"
    period = f"{r.get('base_label') or '?'} → {r.get('latest_label') or '?'}".replace(" ", "&nbsp;")
    profit = f"{st.bold(_pct(r['profit_growth']))}<br/>{muted(then_now + ' · ' + period, 5.9)}"
    pe_change_txt = "n/m" if r["pe_change"] is None else st.bold(S.pct(r["pe_change"]))
    value = r.get("value")
    if value:
        value_cell = Table([[Pill(value["action"], S.SIGNAL[value["signal"]], widths[9] - 10, st.f["semibold"], 6.4)],
                            [Paragraph(muted(esc(value["detail"]), 6), st.td)]], colWidths=[widths[9] - 8])
        value_cell.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    else:
        value_cell = Paragraph(muted("no company file"), st.td)
    cells = [Paragraph(f"{st.bold(esc(r['ticker']))}<br/><font size='6.2' color='{S.INK2}'>{esc(r['name'])}</font>", st.td),
             Paragraph(price, st.td), Paragraph(_pct(r["sales_growth"]), st.td_right), Paragraph(profit, st.td_right),
             Paragraph(_pct(r["price_growth"]) + one_year, st.td_right), Paragraph(pe_change_txt, st.td_right),
             Paragraph("–" if not r.get("pe_now") else f"{r['pe_now']:.1f}", st.td_right),
             Paragraph("–" if r.get("roe") is None else f"{r['roe']*100:.0f}%", st.td_right),
             Paragraph(f"<font size='{13 if len(r['grade']) == 1 else 8}' color='{GRADE_COLOUR[r['grade']]}' "
                       f"name='{st.f['bold']}'>{r['grade']}</font>", st.td_center),
             value_cell]
    if with_position:
        q = r.get("quantity")
        cells.append(Paragraph("–" if not q else f"{money(q * r['price'], ccy, 0)}<br/>{muted(f'{q:,g} shares', 5.9)}", st.td_right))
    cells.append(Paragraph(comment(r), st.comment))
    return cells


def _table(rows, st):
    with_position = any(r.get("quantity") for r in rows)
    parts = [30, 21, 14, 40, 15, 14, 11, 10, 10, 30] + ([20] if with_position else []) + [56]
    widths = _widths(parts)
    names = ["Ticker", "Price (date)", "Sales growth", "Profit growth (then → now)", "Price growth", "P/E change",
             "P/E now", "ROE", "Grade", "Value report"] + (["Position"] if with_position else []) + ["Comment"]
    numeric = {2, 3, 4, 5, 6, 7} | ({10} if with_position else set())
    data = [_header(names, numeric, st)] + [_row(r, st, widths, with_position) for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("BACKGROUND", (0, 0), (-1, 0), hexc("#EEF0F4")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, hexc(S.INK2))]
    for i, r in enumerate(rows, start=1):
        style += [("BACKGROUND", (0, i), (-1, i), hexc(GRADE_TINT[r["grade"]])), ("LINEBELOW", (0, i), (-1, i), 1.0, hexc("#FFFFFF")),
                  ("LINEBEFORE", (0, i), (0, i), 3, hexc(GRADE_COLOUR[r["grade"]]))]
    t.setStyle(TableStyle(style))
    return t


def _at_a_glance(rows):
    counts = {g: sum(1 for r in rows if r["grade"] == g) for g in GRADE_COLOUR}
    text = "<b>At a glance:</b> " + " · ".join(f"{g} {n}" for g, n in counts.items() if n)
    cheap = [r["ticker"] for r in rows if r["grade"] in ("A", "B") and (r.get("value") or {}).get("signal") == "green"]
    dear = [r["ticker"] for r in rows if r["grade"] == "D" and (r.get("value") or {}).get("signal") == "red"]
    if cheap:
        text += f". <b>Profits outran the price and cheap on value (A/B + green):</b> {', '.join(cheap)}"
    if dear:
        text += f". <b>Price outran profits and expensive (D + red):</b> {', '.join(dear)}"
    return text + "."


HOW_TO_READ = ("<b>How to read it.</b> Growth is a yearly rate over about three years: for Indian companies Screener.in's "
               "compounded figures (net profit, latest three financial years; share price over three years); for the rest, "
               "Yahoo Finance statements from the financial year about three years back to the latest twelve months "
               "(diluted EPS, so buybacks and new shares count). P/E change = ((1 + price growth) ÷ (1 + profit growth)) ^ years "
               "− 1: negative means the share is cheaper relative to profits than at the start. <b>Grade:</b> A = P/E fell "
               "25% or more · B = fell up to 25% · C = rose up to a third · D = rose more than a third · n/m = not comparable. "
               "Prices are in the exchange's currency; sales and profits as reported (m = millions, cr = crore). Profits "
               "include one-offs – check large jumps in the filing. A rising metal price lifts miners' profits faster than "
               "their prices (most gold miners grade A now); if the metal falls, profits fall faster too.")


def build(rows: list[dict], path: Path, title: str, as_of: dt.date, sources: str):
    """rows: evaluated records (see evaluate), sorted as they should appear."""
    st = Styles()
    doc = new_document(path, f"{title} – profit growth vs price growth", f"{title} · profit growth vs price growth · {day(as_of)}", st)
    story = [Paragraph(f"{esc(title)} – profit growth vs price growth", st.title),
             Paragraph(f"{len(rows)} companies, from 'profits ran furthest ahead of the price' (top) to 'price ran ahead of "
                       f"profits' (bottom) · run {day(as_of)}", st.subtitle),
             Spacer(1, 3), Paragraph(_at_a_glance(rows), st.small), Spacer(1, 5), _table(rows, st), Spacer(1, 4),
             Paragraph(HOW_TO_READ, st.tiny), Spacer(1, 2), Paragraph(f"<b>Sources:</b> {esc(sources)}", st.tiny)]
    doc.build(story)
    return path


def sort_key(r):
    """A first (most negative P/E change), n/m last."""
    return (r["pe_change"] is None, r["pe_change"] if r["pe_change"] is not None else 0)
