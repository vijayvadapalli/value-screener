"""What the reports say about each company: headlines, the calculation steps, worked examples, the key-figure rows and
the "how to read" cards, and the notes under the summary tables. Each model writes its own words (kinds/<model>.py);
these functions add the shared parts. Plain functions on a result dict (see engine.run); html_report.py lays them out.

Text uses a small paragraph mark-up (<b>, <br/>, <font>), which html_report.markup() turns into HTML."""
from __future__ import annotations

import re

from . import kinds
from . import style as S
from .fmt import day, esc, flag_text, has_earnings, money, net_cash_term, per_year, price_date, signed  # noqa: F401 (re-exported)

MODEL_LABEL = {m: k.label for m, k in kinds.KINDS.items()}
BUY_RULE = {m: k.buy_rule for m, k in kinds.KINDS.items() if k.buy_rule}


# ------------------------------------------------------------------------------------------------- per company
# Each model says its own words (kinds/<model>.py); these put the shared parts around them.
def headline(r, cfg):
    at = f"At <b>{money(r['price'], r['price_ccy'])}</b> ({price_date(r)})"
    return kinds.of(r["model"]).headline(r, cfg, at, f"<b>{esc(r['action'])}</b>", esc(r["name"]), S.pct(r.get("margin_of_safety")))


def calc_steps(r, c):
    return kinds.of(r["model"]).steps(r, c)


def worked_example(r, c):
    return kinds.of(r["model"]).example(r, c)


def key_figures(r):
    return kinds.of(r["model"]).figures(r) + [("Zone", esc(r["zone"]), False)]


def kpi_cards(r):
    """(label, value, caption, colour) – the playbook's 'how to read' cards with this company's numbers."""
    kind, ccy = kinds.of(r["model"]), r["price_ccy"]
    mos = r.get("margin_of_safety")
    mos_colour = S.SIGNAL["green"] if (mos or 0) >= 0 else S.SIGNAL["red"]
    cards = [("Price", money(r["price"], ccy), f"{price_date(r)} · what you pay", S.PRICE)]
    cards += kind.value_cards(r, mos, mos_colour)
    if r.get("buy_level") is not None:
        cards.append(("Buy level", f"≤ {money(r['buy_level'], ccy)}", kind.buy_card_rule(r), S.SIGNAL["green"]))
    extra = kind.extra_card(r)
    return cards + ([extra] if extra else [])


def npa_summary(r):
    """One short line for the summary tables: a lender's latest gross and net NPA, '' for anyone else."""
    aq = r.get("asset_quality") or {}
    if aq.get("gross_npa") is None and aq.get("net_npa") is None:
        return ""
    f = lambda x: "–" if x is None else f"{x*100:.2f}%"  # noqa: E731
    return f"NPA {f(aq.get('gross_npa'))} gross · {f(aq.get('net_npa'))} net"


# ------------------------------------------------------------------------------------------------- report notes
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


def list_title(list_name: str | None) -> str:
    """'nifty50' → 'Nifty 50', 'core' → 'Core', None → 'All Companies'."""
    return re.sub(r"([A-Za-z])(\d)", r"\1 \2", (list_name or "all companies").replace("_", " ").title())
