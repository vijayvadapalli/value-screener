"""Growth companies (tech, Nifty 50): a reverse DCF – the yearly growth for 5 years, sold at 15x, that makes the value
equal the price. The EPS it values follows the Nifty v2 rules when the file has them (v2.py, screening.py)."""
from __future__ import annotations

import numpy as np

from .. import plot, screening
from .. import style as S
from ..fmt import esc, has_earnings, money, net_cash_term
from ..models import dcf_factor
from .base import Kind


class GrowthKind(Kind):
    label = "Growth – reverse DCF"

    def check(self, c):
        if "shares_m" not in c and "eps_per_period" not in c.get("earnings", {}):
            return f"shares_m is required for model {c['model']}"
        return None

    def zone(self, r, z):
        return dict(band=screening.growth_band(r["implied_growth"], r["growth_buy"], z),
                    margin_of_safety=1 - r["price"] / r["v0"] if r["v0"] > 0 else None,
                    put_level=r["v_buy"], call_level=r["v_sell"], buy_level=r["v_buy"], add_level=None)

    # ---- words
    def headline(self, r, cfg, at, act, name, mos):
        g = r.get("implied_growth")
        if g is None:
            return f"{at} {name} has no positive earnings to value – {act}."
        return (f"{at} {name} is worth <b>{money(r['v0'], r['price_ccy'])}</b> a share with no growth. The price needs earnings to grow "
                f"<b>{S.pct(g, 1)}</b> a year for 5 years – {act}.")

    def steps(self, r, c):
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

    def example(self, r, c):
        if not has_earnings(r):
            return None
        ccy = r["price_ccy"]
        how = (r.get("v2") or {}).get("how")
        return (f"<b>Worked example:</b> EPS {money(r['oe'], ccy)}{f' ({esc(how)})' if how else ''} × {r['no_growth_multiple']:.1f} "
                f"(no-growth multiple at {r['discount_rate']*100:.0f}%) {net_cash_term(r['nc'], ccy)} = "
                f"<b>{money(r['v0'], ccy)}</b>. To be worth {money(r['price'], ccy)}, earnings must grow "
                f"<b>{S.pct(r['implied_growth'], 1)}</b> a year for 5 years.")

    def figures(self, r):
        ccy = r["price_ccy"]
        rows = [("Earnings per share used", money(r["oe"], ccy), False)]
        v2 = r.get("v2")
        if v2:
            rows.append(("12-month EPS (one-offs removed)", money(v2["ttm"], ccy), False))
            if v2.get("eps_5y_avg") is not None:
                rows.append(("5-year average EPS", money(v2["eps_5y_avg"], ccy), False))
            elif v2.get("history_not_comparable"):
                rows.append(("5-year average EPS", "not used – history not comparable", False))
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

    def value_cards(self, r, mos, mos_colour):
        return [("Value, no growth", money(r["v0"], r["price_ccy"]), f"{r['no_growth_multiple']:.1f}x EPS + net cash · what you get",
                 S.SIGNAL["blue"]),
                ("Margin of safety", S.pct(mos), "at no growth · your cushion", mos_colour)]

    def buy_card_rule(self, r):
        return f"price at {r['growth_buy']*100:.0f}% growth a year"

    def extra_card(self, r):
        if r.get("implied_growth") is None:
            return None
        return ("Growth needed", S.pct(r["implied_growth"], 1), "a year for 5 years", S.SIGNAL[r["signal"]])

    # ---- summary tables
    def summary_detail(self, r):
        g = r.get("implied_growth")
        return "no valid earnings" if g is None else f"needs {g*100:+.1f}%/yr"

    def value_cell(self, r):
        return money(r["v0"], r["price_ccy"]), "no growth"

    def assumes_cell(self, r):
        g = r.get("implied_growth")
        return ("–" if g is None else S.pct(g, 1) + "/yr"), g

    # ---- charts
    def band_points(self, r):
        if r.get("implied_growth") is None:
            return []
        return [(f"Buy · {r['growth_buy']*100:.0f}%/yr", r["v_buy"], "buy"), ("No growth", r["v0"], "value"),
                ("10%/yr", r["v10"], "value"), ("20%/yr", r["v20"], "value"), ("Sell · 25%/yr", r["v_sell"], "sell")]

    def curve(self, ax, r, c, cfg):
        """Value per share by growth, with the growth the price needs."""
        g = r.get("implied_growth")
        if g is None or not r.get("value_fn"):
            return False
        gs = np.linspace(-0.10, 0.35, 60)
        ax.axvspan(-10, r["growth_buy"] * 100, color=S.BAND["buy"], lw=0)
        ax.axvspan(cfg["zones"]["growth_sell"] * 100, 35, color=S.BAND["sell"], lw=0)
        ax.plot(gs * 100, [r["value_fn"](x) for x in gs], color=S.SIGNAL["blue"], lw=1.6)
        plot.price_line(ax, r["price"], r["price_ccy"])
        if -0.10 <= g <= 0.35:
            plot.mark(ax, g * 100, r["price"], f"needs {g*100:+.1f}%/yr")
        ax.set_xlabel("Earnings growth a year for 5 years (%)")
        plot.per_share_axis(ax, r["price_ccy"])
        plot.title(ax, f"Value per share by growth · {r['discount_rate']*100:.0f}% return, 15x exit")
        return True

    def heat_grid(self, r, c, cfg):
        if r.get("implied_growth") is None:
            return None
        gs, exits = [-0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25], [12, 15, 18]
        return ("Value by growth a year and exit multiple", [f"exit {e}x" for e in exits],
                [f"{g*100:+.0f}%" if g else "0%" for g in gs],
                [[r["oe"] * dcf_factor(g, cfg, r["discount_rate"], e) + r["nc"] for g in gs] for e in exits])

    def value_lines(self, r):
        return [(r.get("buy_level"), f"Buy (≤ {r.get('growth_buy', 0.05) * 100:.0f}% growth)", "buy", S.VALUE_LIGHT, True),
                (r.get("v0"), "Value, no growth", "value", S.VALUE_DARK, True),
                (r.get("call_level"), "Sell zone (25% growth)", "sell", S.SIGNAL["red"], True)]
