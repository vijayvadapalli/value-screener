"""Producers, royalties and streamers (owner earnings × 12 / 15 / 25 + net cash), and oil & gas on the same footing
(cash-flow model: cash from operations before working capital − capex, at 10x / 13x)."""
from __future__ import annotations

import numpy as np

from .. import plot, screening
from .. import style as S
from ..fmt import has_earnings, money, net_cash_term, per_year, signed
from .base import NO_LEVELS, Kind


class ProducerKind(Kind):
    def __init__(self, label: str, buy_rule: str):
        self.label, self.buy_rule = label, buy_rule

    def check(self, c):
        if "shares_m" not in c and "eps_per_period" not in c.get("earnings", {}):
            return f"shares_m is required for model {c['model']}"
        return None

    def zone(self, r, z):
        """Tier A: start at or below 15x, add at or below 12x. Others: BUY with a 20% margin at 12x. AISC ≤ 60% of spot."""
        price = r["price"]
        if r["oe"] <= 0:
            return dict(band="NO EARNINGS", **NO_LEVELS)
        mos = 1 - price / r["v_low"] if r["v_low"] > 0 else -9.99
        cost_ok = r.get("cost_ratio") is None or r["cost_ratio"] <= z["max_cost_ratio"]
        out = dict(margin_of_safety=mos, put_level=max(r["v_low"], 0.0), call_level=r["v_sell"])
        step = None
        if r.get("tier") == "A":
            out.update(buy_level=r["v_high"], add_level=r["v_low"])
            if price <= r["v_high"]:
                band, step = "BUY", ("add" if price <= r["v_low"] else "start")
            else:
                band = "SELL" if price >= r["v_sell"] else "HOLD"
        else:
            out.update(buy_level=(1 - z["buy_margin_of_safety"]) * r["v_low"], add_level=None)
            band = screening.multiple_band(price, r["oe"], r["v_low"], r["v_sell"], z["buy_margin_of_safety"])
        if band == "BUY" and not cost_ok:
            return dict(out, band="WATCH", buy_step=None, high_cost=True)
        return dict(out, band=band, buy_step=step, high_cost=False)

    # ---- words
    def headline(self, r, cfg, at, act, name, mos):
        ccy = r["price_ccy"]
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

    def steps(self, r, c):
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

    def example(self, r, c):
        if not has_earnings(r):
            return None
        ccy = r["price_ccy"]
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

    def figures(self, r):
        ccy = r["price_ccy"]
        if not has_earnings(r):
            return [("Owner earnings per share", money(r.get("oe"), ccy), False)]
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

    def value_cards(self, r, mos, mos_colour):
        if not has_earnings(r):
            return []
        ccy = r["price_ccy"]
        return [("Value", f"{money(r['v_low'], ccy)}–{money(r['v_high'], ccy)}",
                 f"{r['mult_lo']}x–{r['mult_hi']}x owner earnings · what you get", S.SIGNAL["blue"]),
                ("Margin of safety", S.pct(mos), f"at {r['mult_lo']}x · (value − price) ÷ value", mos_colour)]

    def buy_card_rule(self, r):
        if r.get("tier") == "A":
            return f"start ≤ 15x · add ≤ {money(r['add_level'], r['price_ccy'])}"
        return self.buy_rule

    def extra_card(self, r):
        if not r.get("implied_metal_hi"):
            return None
        return (f"{r['primary_metal']} priced in", f"{r['implied_metal_hi']:,.0f}",
                f"at {r['mult_hi']}x · {r['implied_metal_lo']:,.0f} at {r['mult_lo']}x", S.INK2)

    # ---- summary tables
    def summary_detail(self, r):
        if r.get("margin_of_safety") is None:
            return "no earnings"
        return f"price vs 15x: {money(r['price'], r['price_ccy'])} vs {money(r['v_high'], r['price_ccy'])}"

    def value_cell(self, r):
        if (r.get("oe") or 0) > 0:
            return f"{money(r['v_low'], r['price_ccy'])}–{money(r['v_high'], r['price_ccy'])}", f"{r['mult_lo']}–{r['mult_hi']}x"
        return super().value_cell(r)

    # ---- charts
    def band_points(self, r):
        if not r.get("oe") or r["oe"] <= 0:
            return []
        lo, hi = r["mult_lo"], r["mult_hi"]
        if r.get("tier") == "A":
            pts = [(f"{lo}x · add", r["v_low"], "buy"), (f"{hi}x · start", r["v_high"], "buy")]
        else:
            pts = [("Buy · 20% below 12x", r.get("buy_level"), "buy"), (f"{lo}x cautious", r["v_low"], "value"),
                   (f"{hi}x fair", r["v_high"], "value")]
        return pts + [(f"{r['sell_multiple']}x sell zone", r["v_sell"], "sell")]

    def curve(self, ax, r, c, cfg):
        """Value per share against the metal price, with the metal price the share price assumes."""
        if not (bool(r.get("terms")) and (r.get("oe") or 0) > 0):
            return False
        metal = r.get("primary_metal") or r["terms"][0]["metal"]
        t = next((x for x in r["terms"] if x["metal"] == metal), None)
        if not t or not t["sens"]:
            return False
        spot, lo, hi, nc, ccy = t["spot"], r["mult_lo"], r["mult_hi"], r["nc"], r["price_ccy"]
        xs = np.linspace(spot * 0.55, spot * 1.55, 60)
        at = lambda x, k: (r["oe"] + t["sens"] * (x - spot)) * k + nc  # noqa: E731
        ax.fill_between(xs, at(xs, lo), at(xs, hi), color=S.SIGNAL["blue"], alpha=0.10, lw=0)
        ax.plot(xs, at(xs, hi), color=S.SIGNAL["blue"], lw=1.6, label=f"{hi}x fair")
        ax.plot(xs, at(xs, lo), color=S.SIGNAL["blue"], lw=1.4, ls=(0, (4, 2)), label=f"{lo}x cautious")
        plot.price_line(ax, r["price"], ccy)
        ax.axvline(spot, color=S.MUTED, lw=0.8, ls=":")
        ax.text(spot, 1.0, f" spot {spot:,.0f}" if spot >= 100 else f" spot {spot:.2f}", transform=ax.get_xaxis_transform(),
                fontsize=6.5, color=S.MUTED, va="top")
        for key in ("implied_metal_hi", "implied_metal_lo"):
            x = r.get(key)
            if x and xs[0] <= x <= xs[-1]:
                plot.mark(ax, x, r["price"], f"{x:,.0f}")
        for g, v12, _ in r.get("stress", []):
            if xs[0] <= g <= xs[-1]:
                ax.plot([g], [v12], "s", ms=3.6, color=S.SIGNAL["red"], zorder=5)
        ax.legend(loc="upper left")
        ax.set_xlabel(f"{metal.title()} price (US$)")
        plot.per_share_axis(ax, ccy)
        plot.title(ax, f"Value per share against the {metal} price")
        ax.text(0, -0.30, f"Dots: the {metal} price the share price assumes at {hi}x and {lo}x."
                + (" Red squares: 12x value in the gold stress test." if r.get("stress") else ""),
                transform=ax.transAxes, fontsize=6.3, color=S.MUTED)
        return True

    def heat_grid(self, r, c, cfg):
        if (r.get("oe") or 0) <= 0:
            return None
        mults, sc, exp = [10, 12, 15, 20, 25], cfg["metal_scenarios"], r.get("exp") or 0.0
        if not exp:
            return ("Value by multiple (no metal re-pricing)", [f"{k}x" for k in mults], ["at today's prices"],
                    [[r["oe"] * k + r["nc"]] for k in mults])
        metal = r["primary_metal"]
        return (f"Value by {metal} price and multiple", [f"{k}x" for k in mults],
                [f"{metal} {cfg['spot'][metal] * (1 + s):,.0f}" for s in sc],
                [[(r["oe"] + s * exp) * k + r["nc"] for s in sc] for k in mults])

    def value_lines(self, r):
        sell = f"{r['sell_multiple']:g}x sell zone" if r.get("sell_multiple") else "Sell zone"
        lo, hi = r.get("mult_lo"), r.get("mult_hi")
        return [(r.get("v_high"), f"{hi:g}x value" if hi else "Fair value", "value", S.VALUE_LIGHT, True),
                (r.get("v_low"), f"{lo:g}x value" if lo else "Value", "value", S.VALUE_DARK, True),
                (r.get("buy_level"), "start" if r.get("tier") == "A" else "Buy (20% below)", "buy", S.VALUE_LIGHT, False),
                (r.get("add_level"), "add", "add", S.VALUE_DARK, False),
                (r.get("call_level"), sell, "sell", S.SIGNAL["red"], True)]

