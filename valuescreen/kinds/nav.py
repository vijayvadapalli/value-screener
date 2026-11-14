"""Models valued on net asset value: developers (the study's after-tax NPV at today's metal price) and physical holders
(metal at spot + other net assets). nav_zone is shared with the lease model, which is judged on its cautious value."""
from __future__ import annotations

import numpy as np

from .. import plot
from .. import style as S
from ..fmt import esc, money
from ..settings import fx
from ..models import interp, net_cash_ps
from .base import NO_LEVELS, Kind


def nav_zone(r, buy, sell):
    """Price ÷ NAV (or ÷ the cautious value): BUY at or below `buy`, WATCH up to 1.0, SELL at or above `sell`."""
    p = r["pnav"]
    if p is None or r["nav"] <= 0:
        return dict(band="NO VALUE", **NO_LEVELS)
    band = "BUY" if p <= buy else "WATCH" if p <= 1.0 else "SELL" if p >= sell else "HOLD"
    return dict(band=band, margin_of_safety=1 - p, put_level=buy * r["nav"], call_level=sell * r["nav"],
                buy_level=buy * r["nav"], add_level=None)


def nav_curve(ax, r, xs, navs, metal, spot):
    """NAV per share against the metal price, with the metal price at which NAV equals the share price."""
    ccy = r["price_ccy"]
    ax.plot(xs, navs, color=S.SIGNAL["blue"], lw=1.6)
    plot.price_line(ax, r["price"], ccy)
    ax.axvline(spot, color=S.MUTED, lw=0.8, ls=":")
    ax.text(spot, 1.0, f" spot {spot:,.0f}" if spot >= 100 else f" spot {spot:.2f}", transform=ax.get_xaxis_transform(),
            fontsize=6.5, color=S.MUTED, va="top")
    crossing = next((x for x, a, b in zip(xs, navs, navs[1:]) if (a - r["price"]) * (b - r["price"]) <= 0), None)
    if crossing is not None:
        plot.mark(ax, crossing, r["price"], f"{crossing:,.1f}")
    ax.set_xlabel(f"{metal.title()} price (US$)")
    plot.per_share_axis(ax, ccy)
    plot.title(ax, f"NAV per share against the {metal} price")
    ax.text(0, -0.30, "Dot: the metal price at which NAV equals today's share price.", transform=ax.transAxes,
            fontsize=6.3, color=S.MUTED)
    return True


class NavKind(Kind):
    """What developers and physical holders share: everything except the zone thresholds, the steps and the curve."""
    zone_keys = ("developer_buy_pnav", "developer_sell_pnav")

    def zone(self, r, z):
        return nav_zone(r, z[self.zone_keys[0]], z[self.zone_keys[1]])

    def headline(self, r, cfg, at, act, name, mos):
        text = (f"{at} {name} trades at <b>{r['pnav']:.2f}× NAV</b> (NAV {money(r['nav'], r['price_ccy'])} a share). "
                f"Margin of safety <b>{mos}</b> – {act}.")
        if r.get("implied_metal_hi"):
            text += f" The price matches NAV at about <b>{r['implied_metal_hi']:,.1f}</b>."
        return text

    def example(self, r, c):
        ccy = r["price_ccy"]
        return (f"<b>Worked example:</b> price {money(r['price'], ccy)} ÷ NAV {money(r['nav'], ccy)} = <b>{r['pnav']:.2f}× NAV</b>; "
                f"buy at or below {money(r['buy_level'], ccy)}.")

    def figures(self, r):
        ccy = r["price_ccy"]
        rows = [("NAV per share", money(r["nav"], ccy), False), ("Price ÷ NAV", f"{r['pnav']:.2f}", False),
                ("Margin of safety", S.pct(r.get("margin_of_safety")), True)]
        if r.get("implied_metal_hi"):
            rows.append(("Metal price at which NAV = price", f"{r['implied_metal_hi']:,.1f}", False))
        rows += [(f"{esc(p['name'])} (not in the headline value)", money(p["value_ps"], ccy), False) for p in r.get("projects", [])]
        return rows + [("Buy level", money(r["buy_level"], ccy), False), ("Sell level", money(r["call_level"], ccy), False)]

    def value_cards(self, r, mos, mos_colour):
        return [("Value (NAV)", money(r["nav"], r["price_ccy"]), "per share · what you get", S.SIGNAL["blue"]),
                ("Margin of safety", S.pct(mos), f"{r['pnav']:.2f}× NAV · your cushion", mos_colour)]

    def extra_card(self, r):
        if not r.get("implied_metal_hi"):
            return None
        return ("Metal priced in", f"{r['implied_metal_hi']:,.1f}", "NAV = price at this metal price", S.INK2)

    def summary_detail(self, r):
        return f"{r['pnav']:.2f}× NAV"

    def value_cell(self, r):
        return money(r["nav"], r["price_ccy"]), "NAV"

    def band_points(self, r):
        return [("Buy level", r["buy_level"], "buy"), ("NAV", r["nav"], "value"), ("Sell level", r["call_level"], "sell")]

    def heat_grid(self, r, c, cfg):
        shares = [0.5, 0.7, 0.8, 1.0, 1.2]
        metal = (c.get("npv_curve") or c["holdings"])["metal"]
        return ("Value if the market pays a share of NAV, by metal price", [f"{k:.1f}× NAV" for k in shares],
                [f"{metal} {cfg['spot'][metal] * (1 + s):,.0f}" for s in cfg["metal_scenarios"]],
                [[k * nav for nav, _ in r["scenarios"]] for k in shares])

    def value_lines(self, r):
        return [(r.get("buy_level"), "Buy", "buy", S.VALUE_LIGHT, True),
                (r.get("nav") or r.get("v_low"), "NAV", "value", S.VALUE_DARK, True),
                (r.get("call_level"), "Sell zone", "sell", S.SIGNAL["red"], True)]


class DeveloperKind(NavKind):
    label = "Developer – study NAV"
    buy_rule = "0.8× NAV"
    profit_note = "a developer, valued on its study NAV, not profits"
    zone_keys = ("developer_buy_pnav", "developer_sell_pnav")

    def check(self, c):
        return None if "npv_curve" in c else "developer model needs npv_curve"

    def steps(self, r, c):
        return ["<b>No earnings yet</b>: value comes from the feasibility study – the after-tax NPV at several metal prices.",
                "<b>Read the NPV at today's metal price</b> (straight line between the study's cases), × ownership.",
                "<b>Add cash, subtract debt</b>, divide by shares = NAV per share. The study NPV is a ceiling, not a floor.",
                "<b>Rule</b>: BUY ≤ 0.8× NAV, WATCH ≤ 1.0×, HOLD ≤ 1.5×, SELL above."]

    def curve(self, ax, r, c, cfg):
        npv = c["npv_curve"]
        metal, ccy = npv["metal"], r["price_ccy"]
        own, conv = npv.get("ownership", 1.0), fx(cfg, npv.get("currency", c["currency"]), ccy)
        hold = c.get("holdings")
        xs_pts = [p[0] for p in npv["points"]]
        xs = np.linspace(min(xs_pts) * 0.9, max(xs_pts) * 1.05, 60)

        def nav(x):
            held = hold["units"] * x * fx(cfg, "USD", ccy) if hold and hold["metal"] == metal else 0.0
            return (interp(npv["points"], x)[0] * own * conv + held) / c["shares_m"] + net_cash_ps(c, cfg)
        return nav_curve(ax, r, xs, [nav(x) for x in xs], metal, cfg["spot"][metal])


class PhysicalKind(NavKind):
    label = "Physical holder – NAV"
    buy_rule = "0.85× NAV"
    profit_note = "holds the metal; profits are revaluations, so it is valued on NAV"
    zone_keys = ("physical_buy_pnav", "physical_sell_pnav")

    def check(self, c):
        return None if "holdings" in c else "physical model needs holdings"

    def steps(self, r, c):
        return ["<b>The company holds the metal</b>: NAV = holdings × today's spot + other net assets, per share.",
                "<b>Rule</b>: BUY ≤ 0.85× NAV, WATCH ≤ 1.0×, HOLD ≤ 1.1×, SELL above."]

    def curve(self, ax, r, c, cfg):
        h = c["holdings"]
        spot = cfg["spot"][h["metal"]]
        metal_share = h["units"] * spot / (h["units"] * spot + c.get("other_net_assets", 0.0))
        xs = np.linspace(spot * 0.6, spot * 1.6, 50)
        return nav_curve(ax, r, xs, [r["nav"] * (1 + (x / spot - 1) * metal_share) for x in xs], h["metal"], spot)
