"""Contracted leases (Hut 8): an equity DCF of the cash the signed leases hand to shareholders after the bonds and tax,
judged like a NAV on its cautious value (see leases.py for the valuation)."""
from __future__ import annotations

from .. import plot
from .. import style as S
from ..fmt import money
from .base import Kind
from .nav import nav_zone


class LeasesKind(Kind):
    label = "Contracted leases – equity DCF"
    buy_rule = "0.8× cautious value"
    profit_note = "valued on contracted lease cash, not today's profits"

    def check(self, c):
        for f in ("projects", "scenarios", "balance", "shares_m"):
            if f not in c:
                return f"leases model needs {f}"
        for s in ("Cautious", "Base", "Fair"):
            if s not in c["scenarios"]:
                return f"leases model needs a {s} scenario"
        return None

    def zone(self, r, z):
        return nav_zone(r, z["developer_buy_pnav"], z["developer_sell_pnav"])

    # ---- words
    def headline(self, r, cfg, at, act, name, mos):
        ccy = r["price_ccy"]
        text = (f"{at} {name} is worth about <b>{money(r['v_low'], ccy, 0)}</b> cautious, <b>{money(r['v_base'], ccy, 0)}</b> base "
                f"and <b>{money(r['v_high'], ccy, 0)}</b> fair, counting only the cash its signed leases hand to shareholders "
                f"after bonds and tax. The price is <b>{r['pnav']:.2f}×</b> the cautious value – {act}.")
        if r.get("irr"):
            text += f" Bought today, the base case returns about <b>{r['irr']*100:.1f}% a year</b> if every lease is delivered on time."
        return text

    def steps(self, r, c):
        return ["<b>Not owner earnings</b>: the value is in data centres being built under long leases, valued on the cash "
                "they hand to shareholders once finished.",
                "<b>Pay the bonds first</b>: net operating income − interest − bond repayments − tax = cash to shareholders.",
                "<b>Discount</b> at the return you want (cautious / base / fair), add the sites' value when the leases end, "
                "then add bitcoin, cash and the rest of the business, minus other debt.",
                "<b>Rule</b> on the cautious value: BUY ≤ 0.8×, WATCH ≤ 1.0×, HOLD ≤ 1.5×, SELL above."]

    def example(self, r, c):
        ccy = r["price_ccy"]
        return (f"<b>Values:</b> cautious {money(r['v_low'], ccy)}, base {money(r['v_base'], ccy)}, fair {money(r['v_high'], ccy)} "
                f"a share against {money(r['price'], ccy)} = <b>{r['pnav']:.2f}×</b> the cautious value.")

    def figures(self, r):
        ccy = r["price_ccy"]
        rows = [(f"{k} value per share (margin of safety)", f"{money(v, ccy)} ({S.pct(1 - r['price'] / v)})", k == "Cautious")
                for k, v in r["scenario_values"].items()]
        if r.get("irr") is not None:
            rows.append(("Return a year at today's price – base / cautious",
                         f"{r['irr']*100:.1f}% / {(r['irr_cautious'] or 0)*100:.1f}%", False))
        rows += [(f"Cap-rate check – {k.lower()}", money(v, ccy), False) for k, v in r.get("caprate", {}).items()]
        return rows + [("Buy level (0.8× cautious)", money(r["buy_level"], ccy), False),
                       ("Sell level (1.5× cautious)", money(r["call_level"], ccy), False)]

    def value_cards(self, r, mos, mos_colour):
        ccy = r["price_ccy"]
        return [("Value", f"{money(r['v_low'], ccy, 0)}–{money(r['v_high'], ccy, 0)}", "cautious – fair · what you get", S.SIGNAL["blue"]),
                ("Margin of safety", S.pct(mos), "on the cautious value · your cushion", mos_colour)]

    def extra_card(self, r):
        if r.get("irr") is None:
            return None
        return ("Return a year", f"{r['irr']*100:.1f}%", "base case at today's price", S.INK2)

    # ---- summary tables
    def summary_detail(self, r):
        return f"{r['pnav']:.2f}× cautious value"

    def value_cell(self, r):
        ccy = r["price_ccy"]
        return f"{money(r['v_low'], ccy, 0)}–{money(r['v_high'], ccy, 0)}", "cautious–fair"

    def assumes_cell(self, r):
        text, v = super().assumes_cell(r)
        if text == "–" and r.get("irr") is not None:
            return f"{r['irr']*100:.1f}% return", None
        return text, v

    # ---- charts
    def band_points(self, r):
        return [("Buy · 0.8× cautious", r["buy_level"], "buy"), ("Cautious", r["v_low"], "value"), ("Base", r["v_base"], "value"),
                ("Fair", r["v_high"], "value"), ("Sell · 1.5× cautious", r["call_level"], "sell")]

    def curve(self, ax, r, c, cfg):
        """What you earn a year at each purchase price, base and cautious."""
        base = [(p, a) for p, a, _ in r["irr_curve"] if a is not None]
        cautious = [(p, b) for p, _, b in r["irr_curve"] if b is not None]
        ax.plot([p for p, _ in base], [a * 100 for _, a in base], color=S.SIGNAL["blue"], lw=1.6, label="Base")
        ax.plot([p for p, _ in cautious], [b * 100 for _, b in cautious], color=S.SIGNAL["blue"], lw=1.3, ls=(0, (4, 2)),
                label="Cautious")
        plot.price_line(ax, r["price"], r["price_ccy"], vertical=True)
        ax.axhline(10, color=S.MUTED, lw=0.8, ls=":")
        ax.set_xlabel(f"Price paid per share ({S.CURRENCY_SYMBOL.get(r['price_ccy'], '')})")
        ax.set_ylabel("Return a year (%)")
        ax.legend(loc="upper right")
        plot.title(ax, "What you earn a year at each purchase price")
        return True

    def heat_grid(self, r, c, cfg):
        returns, resids, grid = r["sens_return_resid"]
        return ("Return wanted × site value when the leases end (base case)", [f"return {x*100:.0f}%" for x in returns],
                [f"{y}x NOI" for y in resids], grid)

    def extra_chart(self, r, path):
        """Where the base-case value per share comes from."""
        parts = r.get("parts", {}).get("Base")
        if not parts:
            return None
        fig, ax = plot.new_figure(plot.PANEL_SIZE)
        labels, values = list(parts), [v / r["shares_m"] for v in parts.values()]
        n_projects = len(labels) - 5   # the last five parts are bitcoin, bitcoin stake, cash, other operations, other debt
        running = 0.0
        for i, v in enumerate(values):
            colour = S.SIGNAL["red"] if v < 0 else S.SIGNAL["blue"] if i < n_projects else "#4FA884"
            ax.bar(i, v, bottom=running, color=colour, width=0.62)
            ax.text(i, running + max(v, 0) + 0.4, f"{v:+.1f}".replace("-", "−"), ha="center", fontsize=6.5)
            running += v
        ax.bar(len(labels), running, color=S.INK, width=0.62)
        ax.text(len(labels), running + 0.4, f"{running:.1f}", ha="center", fontsize=7, fontweight="semibold")
        plot.price_line(ax, r["price"], r["price_ccy"])
        ax.set_xticks(range(len(labels) + 1), [x.replace(" ", "\n", 1) for x in labels] + ["Value"], fontsize=6.2)
        plot.per_share_axis(ax, r["price_ccy"])
        plot.title(ax, "Where the base-case value comes from")
        return plot.save(fig, path)

    def value_lines(self, r):
        return [(r.get("buy_level"), "Buy", "buy", S.VALUE_LIGHT, True),
                (r.get("nav") or r.get("v_low"), "Value", "value", S.VALUE_DARK, True),
                (r.get("call_level"), "Sell zone", "sell", S.SIGNAL["red"], True)]
