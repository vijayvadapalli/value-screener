"""Charts for the PDF report. Each public function writes a PNG and returns its path, or None when it does not apply.

One style throughout: Inter, no top/right spines, a faint grid, the market price in orange, values in blue,
the buy zone green and the sell zone red.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import style as S  # noqa: E402
from .loader import fx  # noqa: E402
from .models import dcf_factor, interp, net_cash_ps  # noqa: E402

MM = 1 / 25.4
GAP_CMAP = LinearSegmentedColormap.from_list("gap", ["#D9604F", "#F7E6E2", "#F7F7F5", "#DCEEE5", "#17895F"])
CURVE_SIZE = (128, 66)
PANEL_SIZE = (128, 58)


def _setup():
    plt.rcParams.update({
        "font.family": S.font_family(), "font.size": 8, "text.parse_math": False,
        "axes.edgecolor": S.LINE, "axes.labelcolor": S.INK2, "axes.titlesize": 8.5, "axes.labelsize": 7.5,
        "xtick.color": S.INK2, "ytick.color": S.INK2, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#EEF0F3",
        "grid.linewidth": 0.7, "axes.axisbelow": True, "legend.frameon": False, "legend.fontsize": 7,
        "savefig.bbox": "tight", "savefig.pad_inches": 0.04,
    })


def new_figure(size):
    _setup()
    return plt.subplots(figsize=(size[0] * MM, size[1] * MM))


DPI = {"value": 220}   # charts for the PDF; the HTML report uses less to keep the file small


@contextmanager
def resolution(dpi):
    """Draw the charts inside this block at `dpi`."""
    old, DPI["value"] = DPI["value"], dpi
    try:
        yield
    finally:
        DPI["value"] = old


def save(fig, path):
    fig.savefig(path, facecolor="white", dpi=DPI["value"])
    plt.close(fig)
    return Path(path)


def _title(ax, text, pad=6):
    ax.set_title(text, loc="left", fontweight="semibold", color=S.INK, pad=pad)


def _fmt(x, ccy):
    if x is None:
        return "–"
    nd = 0 if abs(x) >= 1000 else 2
    return f"{'−' if x < 0 else ''}{S.CURRENCY_SYMBOL.get(ccy, '')}{abs(x):,.{nd}f}"


def _price_line(ax, price, ccy, vertical=False):
    if vertical:
        ax.axvline(price, color=S.PRICE, lw=1.4)
        ax.text(price, 1.0, f" price {_fmt(price, ccy)}", transform=ax.get_xaxis_transform(), color=S.PRICE,
                fontsize=6.6, va="top")
    else:
        ax.axhline(price, color=S.PRICE, lw=1.4)
        ax.text(0.005, price, f"price {_fmt(price, ccy)}", transform=ax.get_yaxis_transform(), color=S.PRICE,
                fontsize=6.6, va="bottom")


def _mark(ax, x, y, text):
    ax.plot([x], [y], "o", ms=4.2, color=S.INK, zorder=5)
    ax.annotate(text, (x, y), xytext=(0, -10), textcoords="offset points", ha="center", fontsize=6.6)


def _per_share_axis(ax, ccy):
    ax.set_ylabel(f"Per share ({S.CURRENCY_SYMBOL.get(ccy, ccy)})")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if abs(v) >= 10 else f"{v:,.1f}"))


# ------------------------------------------------------------------------------------------- the valuation band
def band_points(r):
    """[(label, value, kind)] for the valuation band. kind: buy | value | sell."""
    m = r["model"]
    if m in ("producer", "cashflow"):
        if not r.get("oe") or r["oe"] <= 0:
            return []
        lo, hi = r["mult_lo"], r["mult_hi"]
        if r.get("tier") == "A":
            pts = [(f"{lo}x · add", r["v_low"], "buy"), (f"{hi}x · start", r["v_high"], "buy")]
        else:
            pts = [("Buy · 20% below 12x", r.get("buy_level"), "buy"), (f"{lo}x cautious", r["v_low"], "value"),
                   (f"{hi}x fair", r["v_high"], "value")]
        return pts + [(f"{r['sell_multiple']}x sell zone", r["v_sell"], "sell")]
    if m in ("developer", "physical"):
        return [("Buy level", r["buy_level"], "buy"), ("NAV", r["nav"], "value"), ("Sell level", r["call_level"], "sell")]
    if m == "leases":
        return [("Buy · 0.8× cautious", r["buy_level"], "buy"), ("Cautious", r["v_low"], "value"), ("Base", r["v_base"], "value"),
                ("Fair", r["v_high"], "value"), ("Sell · 1.5× cautious", r["call_level"], "sell")]
    if m == "growth" and r.get("implied_growth") is not None:
        return [(f"Buy · {r['growth_buy']*100:.0f}%/yr", r["v_buy"], "buy"), ("No growth", r["v0"], "value"),
                ("10%/yr", r["v10"], "value"), ("20%/yr", r["v20"], "value"), ("Sell · 25%/yr", r["v_sell"], "sell")]
    return []


def band(r, path, width_mm=262, height_mm=27):
    """Buy zone (green) → watch (blue) → sell zone (red) on one line, with the price marked."""
    pts = [p for p in band_points(r) if p[1] is not None]
    if not pts:
        return None
    ccy, price = r["price_ccy"], r["price"]
    buy = max([v for _, v, k in pts if k == "buy"], default=0.0)
    sell = min([v for _, v, k in pts if k == "sell"], default=max(v for _, v, _ in pts))
    low = min(0.0, min(v for _, v, _ in pts))
    top = max(max(v for _, v, _ in pts), price) * 1.10
    fig, ax = new_figure((width_mm, height_mm))
    for start, end, colour in ((low, buy, S.BAND["buy"]), (buy, sell, S.BAND["watch"]), (sell, top, S.BAND["sell"])):
        ax.barh(0, end - start, left=start, height=1.0, color=colour, lw=0)
    last = {"up": -np.inf, "down": -np.inf}   # put each label on the side whose previous label is further away
    for label, v, kind in sorted(pts, key=lambda p: p[1]):
        ax.plot([v, v], [-0.5, 0.5], color={"buy": S.SIGNAL["green"], "sell": S.SIGNAL["red"]}.get(kind, S.SIGNAL["blue"]), lw=1.4)
        up = v - last["up"] >= v - last["down"]
        last["up" if up else "down"] = v
        ax.text(v, 0.62 if up else -0.62, f"{label}\n{_fmt(v, ccy)}" if up else f"{_fmt(v, ccy)}\n{label}",
                ha="center", va="bottom" if up else "top", fontsize=6.6, color=S.INK2, linespacing=1.15)
    ax.plot([price, price], [-0.55, 0.55], color=S.PRICE, lw=2.2, zorder=4)
    ax.plot([price], [0], marker="D", ms=7, color=S.PRICE, mec="white", mew=1.2, zorder=5)
    to_right = price < (low + top) * 0.6
    ax.annotate(f"Price {_fmt(price, ccy)}", (price, 0), xytext=(8 if to_right else -8, 0), textcoords="offset points",
                ha="left" if to_right else "right", va="center", fontsize=7.4, color=S.INK, fontweight="semibold",
                bbox=dict(boxstyle="round,pad=0.28", fc="white", ec=S.PRICE, lw=0.8), zorder=6)
    ax.set_xlim(low, top)
    ax.set_ylim(-1.6, 1.6)
    ax.axis("off")
    return save(fig, path)


# ------------------------------------------------------------------------------------------- the main curve
def _curve_producer(ax, r, cfg):
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
    _price_line(ax, r["price"], ccy)
    ax.axvline(spot, color=S.MUTED, lw=0.8, ls=":")
    ax.text(spot, 1.0, f" spot {spot:,.0f}" if spot >= 100 else f" spot {spot:.2f}", transform=ax.get_xaxis_transform(),
            fontsize=6.5, color=S.MUTED, va="top")
    for key in ("implied_metal_hi", "implied_metal_lo"):
        x = r.get(key)
        if x and xs[0] <= x <= xs[-1]:
            _mark(ax, x, r["price"], f"{x:,.0f}")
    for g, v12, _ in r.get("stress", []):
        if xs[0] <= g <= xs[-1]:
            ax.plot([g], [v12], "s", ms=3.6, color=S.SIGNAL["red"], zorder=5)
    ax.legend(loc="upper left")
    ax.set_xlabel(f"{metal.title()} price (US$)")
    _per_share_axis(ax, ccy)
    _title(ax, f"Value per share against the {metal} price")
    ax.text(0, -0.30, f"Dots: the {metal} price the share price assumes at {hi}x and {lo}x."
            + (" Red squares: 12x value in the gold stress test." if r.get("stress") else ""),
            transform=ax.transAxes, fontsize=6.3, color=S.MUTED)
    return True


def _nav_curve(ax, r, xs, navs, metal, spot):
    ccy = r["price_ccy"]
    ax.plot(xs, navs, color=S.SIGNAL["blue"], lw=1.6)
    _price_line(ax, r["price"], ccy)
    ax.axvline(spot, color=S.MUTED, lw=0.8, ls=":")
    ax.text(spot, 1.0, f" spot {spot:,.0f}" if spot >= 100 else f" spot {spot:.2f}", transform=ax.get_xaxis_transform(),
            fontsize=6.5, color=S.MUTED, va="top")
    crossing = next((x for x, a, b in zip(xs, navs, navs[1:]) if (a - r["price"]) * (b - r["price"]) <= 0), None)
    if crossing is not None:
        _mark(ax, crossing, r["price"], f"{crossing:,.1f}")
    ax.set_xlabel(f"{metal.title()} price (US$)")
    _per_share_axis(ax, ccy)
    _title(ax, f"NAV per share against the {metal} price")
    ax.text(0, -0.30, "Dot: the metal price at which NAV equals today's share price.", transform=ax.transAxes,
            fontsize=6.3, color=S.MUTED)
    return True


def _curve_developer(ax, r, c, cfg):
    npv = c["npv_curve"]
    metal, ccy = npv["metal"], r["price_ccy"]
    own, conv = npv.get("ownership", 1.0), fx(cfg, npv.get("currency", c["currency"]), ccy)
    hold = c.get("holdings")
    xs_pts = [p[0] for p in npv["points"]]
    xs = np.linspace(min(xs_pts) * 0.9, max(xs_pts) * 1.05, 60)

    def nav(x):
        held = hold["units"] * x * fx(cfg, "USD", ccy) if hold and hold["metal"] == metal else 0.0
        return (interp(npv["points"], x)[0] * own * conv + held) / c["shares_m"] + net_cash_ps(c, cfg)
    return _nav_curve(ax, r, xs, [nav(x) for x in xs], metal, cfg["spot"][metal])


def _curve_physical(ax, r, c, cfg):
    h = c["holdings"]
    spot = cfg["spot"][h["metal"]]
    metal_share = h["units"] * spot / (h["units"] * spot + c.get("other_net_assets", 0.0))
    xs = np.linspace(spot * 0.6, spot * 1.6, 50)
    return _nav_curve(ax, r, xs, [r["nav"] * (1 + (x / spot - 1) * metal_share) for x in xs], h["metal"], spot)


def _curve_growth(ax, r, cfg):
    g = r.get("implied_growth")
    if g is None or not r.get("value_fn"):
        return False
    gs = np.linspace(-0.10, 0.35, 60)
    ax.axvspan(-10, r["growth_buy"] * 100, color=S.BAND["buy"], lw=0)
    ax.axvspan(cfg["zones"]["growth_sell"] * 100, 35, color=S.BAND["sell"], lw=0)
    ax.plot(gs * 100, [r["value_fn"](x) for x in gs], color=S.SIGNAL["blue"], lw=1.6)
    _price_line(ax, r["price"], r["price_ccy"])
    if -0.10 <= g <= 0.35:
        _mark(ax, g * 100, r["price"], f"needs {g*100:+.1f}%/yr")
    ax.set_xlabel("Earnings growth a year for 5 years (%)")
    _per_share_axis(ax, r["price_ccy"])
    _title(ax, f"Value per share by growth · {r['discount_rate']*100:.0f}% return, 15x exit")
    return True


def _curve_leases(ax, r):
    base = [(p, a) for p, a, _ in r["irr_curve"] if a is not None]
    cautious = [(p, b) for p, _, b in r["irr_curve"] if b is not None]
    ax.plot([p for p, _ in base], [a * 100 for _, a in base], color=S.SIGNAL["blue"], lw=1.6, label="Base")
    ax.plot([p for p, _ in cautious], [b * 100 for _, b in cautious], color=S.SIGNAL["blue"], lw=1.3, ls=(0, (4, 2)),
            label="Cautious")
    _price_line(ax, r["price"], r["price_ccy"], vertical=True)
    ax.axhline(10, color=S.MUTED, lw=0.8, ls=":")
    ax.set_xlabel(f"Price paid per share ({S.CURRENCY_SYMBOL.get(r['price_ccy'], '')})")
    ax.set_ylabel("Return a year (%)")
    ax.legend(loc="upper right")
    _title(ax, "What you earn a year at each purchase price")
    return True


def _bar_liquid(ax, r):
    ccy, mv = r["price_ccy"], r["market_value"]
    greens = ["#17895F", "#4FA884", "#8CC9AE", "#BFE2D2"]
    left = 0.0
    for (label, amount), colour in zip(r["liquid_items"], greens):
        ax.barh(0, amount, left=left, color=colour, height=0.5, label=f"{label}: {_fmt(amount, ccy)}m")
        left += amount
    rest = mv - left
    ax.barh(0, rest, left=left, color="#E9ECF1", height=0.5, label=f"Paid for projects and growth: {_fmt(rest, ccy)}m")
    ax.text(left + rest / 2, 0, f"{rest / mv * 100:.0f}% of the price", ha="center", va="center", fontsize=7.5, color=S.INK2)
    ax.set_yticks([])
    ax.set_ylim(-0.6, 1.4)
    ax.grid(False)
    ax.legend(loc="upper left", ncol=1, fontsize=6.6)
    ax.set_xlabel(f"Market value ({S.CURRENCY_SYMBOL.get(ccy, '')}m)")
    _title(ax, f"What the price buys: liquid assets cover {r['liquid_ratio']*100:.0f}%")
    return True


def curve(r, c, cfg, path):
    fig, ax = new_figure(CURVE_SIZE)
    m = r["model"]
    if m in ("producer", "cashflow"):
        drawn = bool(r.get("terms")) and (r.get("oe") or 0) > 0 and _curve_producer(ax, r, cfg)
    elif m == "developer":
        drawn = _curve_developer(ax, r, c, cfg)
    elif m == "physical":
        drawn = _curve_physical(ax, r, c, cfg)
    elif m == "growth":
        drawn = _curve_growth(ax, r, cfg)
    elif m == "leases":
        drawn = _curve_leases(ax, r)
    elif m == "liquid":
        drawn = _bar_liquid(ax, r)
    else:
        drawn = False
    if not drawn:
        plt.close(fig)
        return None
    return save(fig, path)


# ------------------------------------------------------------------------------------------- heatmap
def _heat(ax, data, price, rows, cols):
    fmt = (lambda v: f"{v:,.0f}") if price >= 100 else (lambda v: f"{v:,.2f}")
    gap = np.array(data) / price - 1
    ax.imshow(np.clip(gap, -0.6, 0.6), cmap=GAP_CMAP, vmin=-0.6, vmax=0.6, aspect="auto")
    for i in range(len(rows)):
        for j in range(len(cols)):
            strong = abs(gap[i, j]) > 0.42
            ax.text(j, i - 0.14, fmt(data[i][j]), ha="center", va="center", fontsize=6.9, fontweight="semibold",
                    color="white" if strong else S.INK)
            ax.text(j, i + 0.24, f"{gap[i, j]*100:+.0f}%".replace("-", "−"), ha="center", va="center", fontsize=6,
                    color="white" if strong else S.INK2)
    ax.set_xticks(range(len(cols)), cols)
    ax.set_yticks(range(len(rows)), rows)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    ax.grid(which="minor", color="white", lw=2)
    ax.tick_params(which="minor", length=0)


def heatmap_grid(r, c, cfg):
    """(title, rows, cols, values) for the model's sensitivity grid, or None."""
    m = r["model"]
    if m in ("producer", "cashflow") and (r.get("oe") or 0) > 0:
        mults, sc, exp = [10, 12, 15, 20, 25], cfg["metal_scenarios"], r.get("exp") or 0.0
        if not exp:
            return ("Value by multiple (no metal re-pricing)", [f"{k}x" for k in mults], ["at today's prices"],
                    [[r["oe"] * k + r["nc"]] for k in mults])
        metal = r["primary_metal"]
        return (f"Value by {metal} price and multiple", [f"{k}x" for k in mults],
                [f"{metal} {cfg['spot'][metal] * (1 + s):,.0f}" for s in sc],
                [[(r["oe"] + s * exp) * k + r["nc"] for s in sc] for k in mults])
    if m in ("developer", "physical"):
        shares = [0.5, 0.7, 0.8, 1.0, 1.2]
        metal = (c.get("npv_curve") or c["holdings"])["metal"]
        return ("Value if the market pays a share of NAV, by metal price", [f"{k:.1f}× NAV" for k in shares],
                [f"{metal} {cfg['spot'][metal] * (1 + s):,.0f}" for s in cfg["metal_scenarios"]],
                [[k * nav for nav, _ in r["scenarios"]] for k in shares])
    if m == "growth" and r.get("implied_growth") is not None:
        gs, exits = [-0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25], [12, 15, 18]
        return ("Value by growth a year and exit multiple", [f"exit {e}x" for e in exits],
                [f"{g*100:+.0f}%" if g else "0%" for g in gs],
                [[r["oe"] * dcf_factor(g, cfg, r["discount_rate"], e) + r["nc"] for g in gs] for e in exits])
    if m == "leases":
        returns, resids, grid = r["sens_return_resid"]
        return ("Return wanted × site value when the leases end (base case)", [f"return {x*100:.0f}%" for x in returns],
                [f"{y}x NOI" for y in resids], grid)
    return None


def heatmap(r, c, cfg, path):
    grid = heatmap_grid(r, c, cfg)
    if not grid:
        return None
    title, rows, cols, data = grid
    fig, ax = new_figure(PANEL_SIZE)
    _heat(ax, data, r["price"], rows, cols)
    _title(ax, title, pad=16)
    return save(fig, path)


# ------------------------------------------------------------------------------------------- extra panels
def eps_history(r, path):
    """Nifty v2: EPS by year (bars) and cash conversion (line, 70% floor dotted)."""
    raw = r.get("eps_annual") or []
    labels = (r.get("eps_years") or [str(i) for i in range(len(raw))])[-len(raw):]
    years, eps = zip(*[(y, e) for y, e in zip(labels, raw) if e is not None]) if raw else ((), ())
    if len(eps) < 2:
        return None
    fig, ax = new_figure(PANEL_SIZE)
    ax.bar(range(len(eps)), eps, color=[S.SIGNAL["blue"] if e >= 0 else S.SIGNAL["red"] for e in eps], width=0.62)
    ax.set_xticks(range(len(eps)), [str(y)[-4:] for y in years], fontsize=6.5)
    ax.set_ylabel(f"EPS ({S.CURRENCY_SYMBOL.get(r['price_ccy'], '')})")
    cfo, profit = r.get("cfo_annual") or [], r.get("profit_annual") or []
    n = min(len(cfo), len(profit), len(eps))
    if n:
        conv = [(len(eps) - n + i, a / p * 100) for i, (a, p) in enumerate(zip(cfo[-n:], profit[-n:])) if p > 0]
        ax2 = ax.twinx()
        ax2.plot([x for x, _ in conv], [v for _, v in conv], color=S.PRICE, marker="o", ms=3, lw=1.2)
        ax2.axhline(70, color=S.PRICE, lw=0.8, ls=":")
        ax2.set_ylabel("Cash conversion (%)", color=S.PRICE)
        ax2.tick_params(axis="y", colors=S.PRICE)
        ax2.spines["right"].set_visible(True)
        ax2.spines["right"].set_color(S.LINE)
        ax2.grid(False)
        ax2.set_ylim(0, max([150] + [v * 1.1 for _, v in conv]))
    _title(ax, "EPS by year (bars) and cash conversion (line, 70% floor dotted)")
    return save(fig, path)


def bridge(r, path):
    """Lease model: where the base-case value per share comes from."""
    parts = r.get("parts", {}).get("Base")
    if not parts:
        return None
    fig, ax = new_figure(PANEL_SIZE)
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
    _price_line(ax, r["price"], r["price_ccy"])
    ax.set_xticks(range(len(labels) + 1), [x.replace(" ", "\n", 1) for x in labels] + ["Value"], fontsize=6.2)
    _per_share_axis(ax, r["price_ccy"])
    _title(ax, "Where the base-case value comes from")
    return save(fig, path)
