"""Not valued (UEC, UUUU): no meaningful earnings and no single study, so neither the earnings nor the NAV model
applies. Shown instead: liquid assets as a share of the market value. Always red – no valid value to buy against."""
from __future__ import annotations

from .. import plot
from .. import style as S
from ..fmt import esc, money
from .base import NO_LEVELS, Kind


class LiquidKind(Kind):
    label = "Not valued – liquid assets only"
    profit_note = "no meaningful profits; not valued"

    def check(self, c):
        if not (c.get("liquid_assets") or c.get("holdings")):
            return "liquid model needs liquid_assets (and shares_m)"
        return None if "shares_m" in c else "liquid model needs shares_m"

    def zone(self, r, z):
        return dict(band="NOT VALUED", **NO_LEVELS)

    # ---- words
    def headline(self, r, cfg, at, act, name, mos):
        return (f"<b>Not valued:</b> {at} {name} has no earnings value and no single study, so this framework gives no value. "
                f"Liquid assets cover <b>{r['liquid_ratio']*100:.0f}%</b> of the market value; the rest pays for projects and growth.")

    def steps(self, r, c):
        return ["<b>Not valued</b>: no meaningful earnings and no single study covers the company, so neither the earnings "
                "nor the NAV model applies.",
                "<b>Instead</b>: liquid assets (cash, securities, metal at spot) as a share of the market value. The signal "
                "is red – there is no valid value to buy against."]

    def figures(self, r):
        ccy = r["price_ccy"]
        rows = [("Market value", f"{money(r['market_value'], ccy, 0)}m", False)]
        rows += [(esc(label), f"{money(amount, ccy, 0)}m", False) for label, amount in r["liquid_items"]]
        if r.get("debt"):
            rows.append(("Debt", f"−{money(r['debt'], ccy, 0)}m", False))
        return rows + [("Liquid assets ÷ market value", f"{r['liquid_ratio']*100:.0f}%", True)]

    def value_cards(self, r, mos, mos_colour):
        return [("Value", "Not valued", "no earnings, no single study", S.MUTED),
                ("Liquid assets", f"{r['liquid_ratio']*100:.0f}%", "of the market value", S.MUTED)]

    # ---- summary tables
    def summary_detail(self, r):
        return "not valued"

    # ---- charts
    def curve(self, ax, r, c, cfg):
        """What the price buys: the liquid assets, then what is left for projects and growth."""
        ccy, mv = r["price_ccy"], r["market_value"]
        greens = ["#17895F", "#4FA884", "#8CC9AE", "#BFE2D2"]
        left = 0.0
        for (label, amount), colour in zip(r["liquid_items"], greens):
            ax.barh(0, amount, left=left, color=colour, height=0.5, label=f"{label}: {plot.fmt_money(amount, ccy)}m")
            left += amount
        rest = mv - left
        ax.barh(0, rest, left=left, color="#E9ECF1", height=0.5, label=f"Paid for projects and growth: {plot.fmt_money(rest, ccy)}m")
        ax.text(left + rest / 2, 0, f"{rest / mv * 100:.0f}% of the price", ha="center", va="center", fontsize=7.5, color=S.INK2)
        ax.set_yticks([])
        ax.set_ylim(-0.6, 1.4)
        ax.grid(False)
        ax.legend(loc="upper left", ncol=1, fontsize=6.6)
        ax.set_xlabel(f"Market value ({S.CURRENCY_SYMBOL.get(ccy, '')}m)")
        plot.title(ax, f"What the price buys: liquid assets cover {r['liquid_ratio']*100:.0f}%")
        return True
