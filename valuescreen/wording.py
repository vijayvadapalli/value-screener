"""What the reports say about each company: headlines, comments, the calculation steps, worked examples, the key-figure
rows and the "how to read" cards. Plain functions on a result dict (see engine.run); the PDF only lays them out.

Text uses reportlab's paragraph mark-up (<b>, <br/>, <font>), which the PDF renders."""
from __future__ import annotations

import html

from . import style as S


MODEL_LABEL = {"producer": "Producer / royalty – owner earnings", "cashflow": "Cash-flow (oil & gas)",
               "developer": "Developer – study NAV", "physical": "Physical holder – NAV", "growth": "Growth – reverse DCF",
               "leases": "Contracted leases – equity DCF", "liquid": "Not valued – liquid assets only"}
BUY_RULE = {"producer": "20% margin at 12x", "cashflow": "20% margin at the cautious multiple", "developer": "0.8× NAV",
            "physical": "0.85× NAV", "leases": "0.8× cautious value"}


# ------------------------------------------------------------------------------------------------- formatting
def esc(x):
    return html.escape(str(x), quote=False)


def money(x, ccy, nd=2):
    if x is None:
        return "–"
    if ccy == "GBP" and abs(x) < 100:   # LSE shares are quoted in pence
        return f"{x * 100:,.0f}p"
    return S.money(x, ccy, nd if abs(x) < 10000 else 0)


def day(d):
    return f"{d.day} {d:%b %Y}" if d else "–"


def price_date(r):
    return "date not shown" if r.get("price_undated") else day(r["price_date"])


def per_year(n):
    return "4/3" if abs(n - 4 / 3) < 1e-6 else f"{n:g}"


def signed(x, nd=2):
    return f"{'−' if x < 0 else '+'}{abs(x):,.{nd}f}"


def net_cash_term(nc, ccy):
    return f"+ {money(nc, ccy)} net cash" if nc >= 0 else f"− {money(-nc, ccy)} net debt"


def flag_text(r):
    return " ".join(f"[{esc(f)}]" for f in r.get("flags", []))


def has_earnings(r):
    return (r.get("oe") or 0) > 0


# ------------------------------------------------------------------------------------------------- headline and comment
def auto_comment(r):
    m = r["model"]
    if m in ("producer", "cashflow"):
        if not has_earnings(r):
            return "No positive owner earnings in the period."
        bits = [f"{r['pe']:.0f}x owner earnings"]
        if r.get("cost_ratio") is not None:
            bits.append(f"AISC {r['cost_ratio']*100:.0f}% of spot")
        if r.get("implied_metal_hi"):
            bits.append(f"price assumes {r['primary_metal']} {r['implied_metal_hi']:,.0f} at 15x")
        return "; ".join(bits) + "."
    if m in ("developer", "physical"):
        extra = f"; NAV = price at about {r['implied_metal_hi']:,.1f}" if r.get("implied_metal_hi") else ""
        return f"{r['pnav']:.2f}× NAV{extra}."
    if m == "leases":
        extra = f"; about {r['irr']*100:.1f}% a year in the base case" if r.get("irr") else ""
        return f"{r['pnav']:.2f}× the cautious value{extra}."
    if m == "liquid":
        return f"Liquid assets cover {r['liquid_ratio']*100:.0f}% of the market value; the rest is projects."
    return "No positive earnings to value." if r.get("implied_growth") is None else ""   # the table already shows the growth


def headline(r, cfg):
    ccy, m, name = r["price_ccy"], r["model"], esc(r["name"])
    at = f"At <b>{money(r['price'], ccy)}</b> ({price_date(r)})"
    act = f"<b>{esc(r['action'])}</b>"
    mos = S.pct(r.get("margin_of_safety"))
    if m in ("producer", "cashflow"):
        if not has_earnings(r):
            return f"{at} {name} has no positive owner earnings, so there is no earnings value – {act}."
        repriced = f"re-priced to {r['primary_metal']} at {cfg['spot'][r['primary_metal']]:,.0f}, " if r.get("terms") else ""
        text = (f"{at} {name} is worth <b>{money(r['v_low'], ccy)}–{money(r['v_high'], ccy)}</b> a share "
                f"({r['mult_lo']}–{r['mult_hi']}x owner earnings, {repriced}plus net cash). Margin of safety at "
                f"{r['mult_lo']}x: <b>{mos}</b> – {act}.")
        if r.get("implied_metal_hi"):
            text += (f" The price already assumes about <b>{r['implied_metal_hi']:,.0f}–{r['implied_metal_lo']:,.0f}</b> "
                     f"{r['primary_metal']} (at {r['mult_hi']}x / {r['mult_lo']}x).")
        return text
    if m in ("developer", "physical"):
        text = f"{at} {name} trades at <b>{r['pnav']:.2f}× NAV</b> (NAV {money(r['nav'], ccy)} a share). Margin of safety <b>{mos}</b> – {act}."
        if r.get("implied_metal_hi"):
            text += f" The price matches NAV at about <b>{r['implied_metal_hi']:,.1f}</b>."
        return text
    if m == "leases":
        text = (f"{at} {name} is worth about <b>{money(r['v_low'], ccy, 0)}</b> cautious, <b>{money(r['v_base'], ccy, 0)}</b> base "
                f"and <b>{money(r['v_high'], ccy, 0)}</b> fair, counting only the cash its signed leases hand to shareholders "
                f"after bonds and tax. The price is <b>{r['pnav']:.2f}×</b> the cautious value – {act}.")
        if r.get("irr"):
            text += f" Bought today, the base case returns about <b>{r['irr']*100:.1f}% a year</b> if every lease is delivered on time."
        return text
    if m == "liquid":
        return (f"<b>Not valued:</b> {at} {name} has no earnings value and no single study, so this framework gives no value. "
                f"Liquid assets cover <b>{r['liquid_ratio']*100:.0f}%</b> of the market value; the rest pays for projects and growth.")
    g = r.get("implied_growth")
    if g is None:
        return f"{at} {name} has no positive earnings to value – {act}."
    return (f"{at} {name} is worth <b>{money(r['v0'], ccy)}</b> a share with no growth. The price needs earnings to grow "
            f"<b>{S.pct(g, 1)}</b> a year for 5 years – {act}.")


# ------------------------------------------------------------------------------------------------- how the value is calculated
def calc_steps(r, c):
    m = r["model"]
    if m in ("producer", "cashflow"):
        royalty = "royalty" in c.get("sector", "") or "streaming" in c.get("name", "").lower()
        first = ("<b>Owner earnings</b> = adjusted net income (royalty and streaming companies have no meaningful capex), "
                 "× periods a year." if royalty else
                 "<b>Owner earnings</b> = adjusted net income + D&amp;A − sustaining capex, × periods a year.")
        if r.get("terms"):
            second = "<b>Re-price to today's metals</b>: ounces / pounds sold × (spot − realised price) × (1 − royalty) × (1 − tax)."
        else:
            why = " – Cameco sells uranium mostly under long-term contracts" if c["ticker"] == "CCJ" else ""
            second = f"<b>No re-pricing to spot</b>: earnings stay at the company's own realised prices{why}."
        if r.get("tier") == "A":
            rule = "<b>Rule (tier A)</b>: start a position at or below the 15x value, add at or below 12x; AISC ≤ 60% of spot."
        else:
            rule = "<b>Rule</b>: BUY needs a 20% margin of safety at 12x and AISC ≤ 60% of spot. 25x and above is the sell zone."
        return [first, second, f"<b>Value</b> = owner earnings × {r['mult_lo']} (cautious) and × {r['mult_hi']} (fair), "
                               "plus net cash per share.", rule]
    if m == "developer":
        return ["<b>No earnings yet</b>: value comes from the feasibility study – the after-tax NPV at several metal prices.",
                "<b>Read the NPV at today's metal price</b> (straight line between the study's cases), × ownership.",
                "<b>Add cash, subtract debt</b>, divide by shares = NAV per share. The study NPV is a ceiling, not a floor.",
                "<b>Rule</b>: BUY ≤ 0.8× NAV, WATCH ≤ 1.0×, HOLD ≤ 1.5×, SELL above."]
    if m == "physical":
        return ["<b>The company holds the metal</b>: NAV = holdings × today's spot + other net assets, per share.",
                "<b>Rule</b>: BUY ≤ 0.85× NAV, WATCH ≤ 1.0×, HOLD ≤ 1.1×, SELL above."]
    if m == "leases":
        return ["<b>Not owner earnings</b>: the value is in data centres being built under long leases, valued on the cash "
                "they hand to shareholders once finished.",
                "<b>Pay the bonds first</b>: net operating income − interest − bond repayments − tax = cash to shareholders.",
                "<b>Discount</b> at the return you want (cautious / base / fair), add the sites' value when the leases end, "
                "then add bitcoin, cash and the rest of the business, minus other debt.",
                "<b>Rule</b> on the cautious value: BUY ≤ 0.8×, WATCH ≤ 1.0×, HOLD ≤ 1.5×, SELL above."]
    if m == "liquid":
        return ["<b>Not valued</b>: no meaningful earnings and no single study covers the company, so neither the earnings "
                "nor the NAV model applies.",
                "<b>Instead</b>: liquid assets (cash, securities, metal at spot) as a share of the market value. The signal "
                "is red – there is no valid value to buy against."]
    v2 = r.get("v2")
    financial = bool(v2) and v2["kind"] == "financial"
    return ["<b>Earnings per share</b>: " + (esc(v2["how"]) if v2 else "the latest reported earnings, annualised") + ".",
            f"<b>Value</b> = 5 years of earnings growing at g, then sold at 15x, discounted at {r['discount_rate']*100:.0f}% "
            f"(no-growth multiple {r['no_growth_multiple']:.1f}x)"
            + (", with no net-cash adjustment for a financial." if financial else ", plus net cash."),
            "<b>Growth needed</b> = the yearly growth that makes the value equal the price.",
            f"<b>Rule</b>: green if it needs ≤ {r['growth_buy']*100:.0f}% a year, blue 5–25%, red ≥ 25%. Cyclicals and "
            "cash conversion below 70% are capped at blue."] \
        + (["<b>Bad loans</b>: book value is cut by the bad loans not yet provided for (net NPA × loans). Net NPA "
               "above 2%, gross NPA above 5%, provision coverage below 60% or gross NPA rising by more than half a point "
               "in a year caps the signal at blue. Capital ratios are not checked – look them up."]
              if financial and v2.get("asset_quality") else [])


def worked_example(r, c):
    ccy, m = r["price_ccy"], r["model"]
    if m in ("producer", "cashflow") and has_earnings(r):
        e = c[r.get("basis", "earnings")]
        n = e.get("per_year", c["period"]["per_year"])
        if "eps_per_period" in e:
            first = f"EPS {e['eps_per_period']:,.2f} × {per_year(n)}"
        else:
            if "cfo_ex_wc" in e:
                terms = f"{e['cfo_ex_wc']:,.0f} − {e.get('capex', 0):,.0f}"
            else:
                terms = f"{e.get('adj_net_income', e.get('net_income', e.get('owner_earnings', 0))):,.0f}"
                terms += "".join(f" + {e[k]:,.0f}" for k in ("addbacks", "da") if e.get(k))
                terms += f" − {e['sustaining_capex']:,.0f}" if e.get("sustaining_capex") else ""
            converted = "" if c["currency"] == ccy else f" in {c['currency']}m, converted to {ccy}"
            first = f"({terms}) × {per_year(n)} ÷ {e.get('shares_m', c.get('shares_m')):,.1f}m shares{converted}"
        delta = r["oe"] - r["oe_rep"]
        repriced = f"; re-priced to today's metals {signed(delta)} → <b>{money(r['oe'], ccy)}</b>" if abs(delta) > 1e-9 else ""
        return (f"<b>Worked example:</b> {first} = <b>{money(r['oe_rep'], ccy)}</b> a share{repriced}. × {r['mult_lo']} "
                f"{net_cash_term(r['nc'], ccy)} = <b>{money(r['v_low'], ccy)}</b> (cautious); × {r['mult_hi']} = "
                f"<b>{money(r['v_high'], ccy)}</b> (fair). Price {money(r['price'], ccy)}.")
    if m == "growth" and has_earnings(r):
        how = (r.get("v2") or {}).get("how")
        return (f"<b>Worked example:</b> EPS {money(r['oe'], ccy)}{f' ({esc(how)})' if how else ''} × {r['no_growth_multiple']:.1f} "
                f"(no-growth multiple at {r['discount_rate']*100:.0f}%) {net_cash_term(r['nc'], ccy)} = "
                f"<b>{money(r['v0'], ccy)}</b>. To be worth {money(r['price'], ccy)}, earnings must grow "
                f"<b>{S.pct(r['implied_growth'], 1)}</b> a year for 5 years.")
    if m in ("developer", "physical"):
        return (f"<b>Worked example:</b> price {money(r['price'], ccy)} ÷ NAV {money(r['nav'], ccy)} = <b>{r['pnav']:.2f}× NAV</b>; "
                f"buy at or below {money(r['buy_level'], ccy)}.")
    if m == "leases":
        return (f"<b>Values:</b> cautious {money(r['v_low'], ccy)}, base {money(r['v_base'], ccy)}, fair {money(r['v_high'], ccy)} "
                f"a share against {money(r['price'], ccy)} = <b>{r['pnav']:.2f}×</b> the cautious value.")
    return None


# ------------------------------------------------------------------------------------------------- key figures
def _producer_figures(r):
    ccy = r["price_ccy"]
    rows = [("Owner earnings / share – reported period × year", money(r["oe_rep"], ccy), False)]
    rows += [(f"{t['metal'].title()}: {t['realised']:,.2f} realised → {t['spot']:,.2f} spot", signed(t["delta"]), False)
             for t in r.get("terms", [])]
    rows += [("Owner earnings / share at today's prices", money(r["oe"], ccy), True),
             ("Net cash per share", money(r["nc"], ccy), False),
             (f"Value at {r['mult_lo']}x / {r['mult_hi']}x / {r['sell_multiple']}x",
              f"{money(r['v_low'], ccy)} / {money(r['v_high'], ccy)} / {money(r['v_sell'], ccy)}", False),
             ("Price ÷ owner earnings (ex net cash)", f"{r['pe']:.1f}x", False),
             (f"Margin of safety at {r['mult_lo']}x", S.pct(r.get("margin_of_safety")), True)]
    if r.get("implied_metal_hi"):
        rows.append((f"{r['primary_metal'].title()} price the share price assumes ({r['mult_hi']}x / {r['mult_lo']}x)",
                     f"{r['implied_metal_hi']:,.0f} / {r['implied_metal_lo']:,.0f}", False))
    rows.append(("AISC ÷ spot", "–" if r.get("cost_ratio") is None else f"{r['cost_ratio']*100:.0f}%", False))
    rows += [(f"Stress: {r['mult_lo']}x value at gold ${g:,.0f}", money(v, ccy), False) for g, v, _ in r.get("stress", [])]
    if r.get("fcf_ps") is not None:
        rows.append(("Free cash flow / share after all capex (yield)",
                     f"{money(r['fcf_ps'], ccy)} ({r['fcf_ps'] / r['price'] * 100:.1f}%)", False))
    return rows


def _nav_figures(r):
    ccy = r["price_ccy"]
    rows = [("NAV per share", money(r["nav"], ccy), False), ("Price ÷ NAV", f"{r['pnav']:.2f}", False),
            ("Margin of safety", S.pct(r.get("margin_of_safety")), True)]
    if r.get("implied_metal_hi"):
        rows.append(("Metal price at which NAV = price", f"{r['implied_metal_hi']:,.1f}", False))
    rows += [(f"{esc(p['name'])} (not in the headline value)", money(p["value_ps"], ccy), False) for p in r.get("projects", [])]
    return rows + [("Buy level", money(r["buy_level"], ccy), False), ("Sell level", money(r["call_level"], ccy), False)]


def _lease_figures(r):
    ccy = r["price_ccy"]
    rows = [(f"{k} value per share (margin of safety)", f"{money(v, ccy)} ({S.pct(1 - r['price'] / v)})", k == "Cautious")
            for k, v in r["scenario_values"].items()]
    if r.get("irr") is not None:
        rows.append(("Return a year at today's price – base / cautious",
                     f"{r['irr']*100:.1f}% / {(r['irr_cautious'] or 0)*100:.1f}%", False))
    rows += [(f"Cap-rate check – {k.lower()}", money(v, ccy), False) for k, v in r.get("caprate", {}).items()]
    return rows + [("Buy level (0.8× cautious)", money(r["buy_level"], ccy), False),
                   ("Sell level (1.5× cautious)", money(r["call_level"], ccy), False)]


def _liquid_figures(r):
    ccy = r["price_ccy"]
    rows = [("Market value", f"{money(r['market_value'], ccy, 0)}m", False)]
    rows += [(esc(label), f"{money(amount, ccy, 0)}m", False) for label, amount in r["liquid_items"]]
    if r.get("debt"):
        rows.append(("Debt", f"−{money(r['debt'], ccy, 0)}m", False))
    return rows + [("Liquid assets ÷ market value", f"{r['liquid_ratio']*100:.0f}%", True)]


def _growth_figures(r):
    ccy = r["price_ccy"]
    rows = [("Earnings per share used", money(r["oe"], ccy), False)]
    v2 = r.get("v2")
    if v2:
        rows.append(("12-month EPS (one-offs removed)", money(v2["ttm"], ccy), False))
        if v2.get("eps_5y_avg") is not None:
            rows.append(("5-year average EPS", money(v2["eps_5y_avg"], ccy), False))
        rows += [("One-off quarter replaced", f"{old:,.2f} → {new:,.2f}", False) for _, old, new in v2.get("one_offs", [])]
    rows += [("Net cash per share", money(r["nc"], ccy), False),
             ("Discount rate · no-growth multiple", f"{r['discount_rate']*100:.0f}% · {r['no_growth_multiple']:.1f}x", False),
             ("Value: no growth / 10% / 20% a year", f"{money(r['v0'], ccy)} / {money(r['v10'], ccy)} / {money(r['v20'], ccy)}", False),
             ("Growth the price needs", S.pct(r.get("implied_growth"), 1), True)]
    if r.get("pe"):
        rows.append(("P/E (ex net cash)", f"{r['pe']:.1f}", False))
    if r.get("cash_conversion") is not None:
        rows.append(("Cash conversion (5 years)", f"{r['cash_conversion']*100:.0f}%", False))
    aq = r.get("asset_quality")
    if aq:
        rows += [(esc(label), esc(text), False) for label, text in aq["lines"]]
        if aq.get("bad_loans_ps"):
            rows.append(("Bad loans not provided for, per share", f"−{money(aq['bad_loans_ps'], ccy)}", False))
    if r.get("pb") is not None:
        fair = f" · fair {r['fair_pb']:.2f}" if r.get("fair_pb") is not None else ""
        adjusted = aq and aq.get("bad_loans_ps")
        label = "Price ÷ adjusted book" if adjusted else "Price ÷ book"
        reported = f" (reported book {r['pb_reported']:.2f})" if adjusted and r.get("pb_reported") else ""
        rows.append((f"{label} (fair = 5-yr ROE × no-growth multiple)", f"{r['pb']:.2f}{fair}{reported}", False))
    if r.get("market_value_usd_bn") is not None:
        rows.append(("Market value", f"US${r['market_value_usd_bn']:,.1f}bn", False))
    return rows


def npa_summary(r):
    """One short line for the summary tables: a lender's latest gross and net NPA, '' for anyone else."""
    aq = r.get("asset_quality") or {}
    if aq.get("gross_npa") is None and aq.get("net_npa") is None:
        return ""
    f = lambda x: "–" if x is None else f"{x*100:.2f}%"  # noqa: E731
    return f"NPA {f(aq.get('gross_npa'))} gross · {f(aq.get('net_npa'))} net"


def key_figures(r):
    m = r["model"]
    if m in ("producer", "cashflow"):
        rows = _producer_figures(r) if has_earnings(r) else [("Owner earnings per share", money(r.get("oe"), r["price_ccy"]), False)]
    elif m in ("developer", "physical"):
        rows = _nav_figures(r)
    elif m == "leases":
        rows = _lease_figures(r)
    elif m == "liquid":
        rows = _liquid_figures(r)
    else:
        rows = _growth_figures(r)
    return rows + [("Zone", esc(r["zone"]), False)]


# ------------------------------------------------------------------------------------------------- the 'how to read' cards
def kpi_cards(r):
    """(label, value, caption, colour) – the playbook's 'how to read' cards with this company's numbers."""
    ccy, m = r["price_ccy"], r["model"]
    mos = r.get("margin_of_safety")
    mos_colour = S.SIGNAL["green"] if (mos or 0) >= 0 else S.SIGNAL["red"]
    cards = [("Price", money(r["price"], ccy), f"{price_date(r)} · what you pay", S.PRICE)]
    if m in ("producer", "cashflow") and has_earnings(r):
        cards += [("Value", f"{money(r['v_low'], ccy)}–{money(r['v_high'], ccy)}",
                   f"{r['mult_lo']}x–{r['mult_hi']}x owner earnings · what you get", S.SIGNAL["blue"]),
                  ("Margin of safety", S.pct(mos), f"at {r['mult_lo']}x · (value − price) ÷ value", mos_colour)]
    elif m in ("developer", "physical"):
        cards += [("Value (NAV)", money(r["nav"], ccy), "per share · what you get", S.SIGNAL["blue"]),
                  ("Margin of safety", S.pct(mos), f"{r['pnav']:.2f}× NAV · your cushion", mos_colour)]
    elif m == "leases":
        cards += [("Value", f"{money(r['v_low'], ccy, 0)}–{money(r['v_high'], ccy, 0)}", "cautious – fair · what you get", S.SIGNAL["blue"]),
                  ("Margin of safety", S.pct(mos), "on the cautious value · your cushion", mos_colour)]
    elif m == "liquid":
        cards += [("Value", "Not valued", "no earnings, no single study", S.MUTED),
                  ("Liquid assets", f"{r['liquid_ratio']*100:.0f}%", "of the market value", S.MUTED)]
    elif m == "growth":
        cards += [("Value, no growth", money(r["v0"], ccy), f"{r['no_growth_multiple']:.1f}x EPS + net cash · what you get", S.SIGNAL["blue"]),
                  ("Margin of safety", S.pct(mos), "at no growth · your cushion", mos_colour)]
    if r.get("buy_level") is not None:
        if m in ("producer", "cashflow") and r.get("tier") == "A":
            rule = f"start ≤ 15x · add ≤ {money(r['add_level'], ccy)}"
        elif m == "growth":
            rule = f"price at {r['growth_buy']*100:.0f}% growth a year"
        else:
            rule = BUY_RULE.get(m, "")
        cards.append(("Buy level", f"≤ {money(r['buy_level'], ccy)}", rule, S.SIGNAL["green"]))
    if m in ("producer", "cashflow") and r.get("implied_metal_hi"):
        cards.append((f"{r['primary_metal']} priced in", f"{r['implied_metal_hi']:,.0f}",
                      f"at {r['mult_hi']}x · {r['implied_metal_lo']:,.0f} at {r['mult_lo']}x", S.INK2))
    elif m in ("developer", "physical") and r.get("implied_metal_hi"):
        cards.append(("Metal priced in", f"{r['implied_metal_hi']:,.1f}", "NAV = price at this metal price", S.INK2))
    elif m == "growth" and r.get("implied_growth") is not None:
        cards.append(("Growth needed", S.pct(r["implied_growth"], 1), "a year for 5 years", S.SIGNAL[r["signal"]]))
    elif m == "leases" and r.get("irr") is not None:
        cards.append(("Return a year", f"{r['irr']*100:.1f}%", "base case at today's price", S.INK2))
    return cards
