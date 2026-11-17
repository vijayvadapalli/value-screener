"""Charts for the HTML report. Each public function writes a PNG and returns its path, or None when it does not apply.
The valuation band, the heatmap and the EPS history are drawn here; the main curve, the band's points and the heatmap's
grid come from the model (kinds/<model>.py). Style and helpers: plot.py.

One style throughout: Inter, no top/right spines, a faint grid, the market price in orange, values in blue,
the buy zone green and the sell zone red.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import kinds  # noqa: E402
from . import style as S  # noqa: E402
from .plot import (CURVE_SIZE, DPI, GAP_CMAP, PANEL_SIZE, new_figure, resolution, save,  # noqa: F401 (re-exported)
                   fmt_money as _fmt, title as _title)


# ------------------------------------------------------------------------------------------- the valuation band
def band_points(r):
    """[(label, value, kind)] for the valuation band. kind: buy | value | sell."""
    return kinds.of(r["model"]).band_points(r)


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
def curve(r, c, cfg, path):
    """The model's main chart (value against the metal price, NAV curve, growth curve, ...), or None."""
    fig, ax = new_figure(CURVE_SIZE)
    if not kinds.of(r["model"]).curve(ax, r, c, cfg):
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
    return kinds.of(r["model"]).heat_grid(r, c, cfg)


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


def extra(r, path):
    """A model's second chart (the lease value bridge), or None."""
    return kinds.of(r["model"]).extra_chart(r, path)


def bridge(r, path):
    """Lease model: where the base-case value per share comes from."""
    return kinds.of("leases").extra_chart(r, path)


def backtest_curve(cv: dict, index_name: str, dividends: bool, path):
    """The backtest's growth of 1 since its earliest start with picks: the picks and all screened (equal-weighted,
    buy and hold) and the index (dashed, a reference). Each line labelled at its end."""
    import datetime as dt  # noqa: PLC0415
    if not cv or len(cv["days"]) < 2:
        return None
    days = [dt.date.fromisoformat(d) for d in cv["days"]]
    fig, ax = new_figure((180, 62))
    ret = "with dividends" if dividends else "price only"
    lines = [(f"Picks ({cv['n_picks']})", cv["picks"], S.SIGNAL["green"], "-", 1.8),
             (f"All screened ({cv['n_all']})", cv["all"], S.SIGNAL["blue"], "-", 1.2),
             (index_name, cv["index"], S.INK, (0, (4, 2)), 1.1)]
    ends = []
    for label, ys, color, ls, lw in lines:
        pts = [(d, y) for d, y in zip(days, ys) if y is not None]
        if not pts or label.startswith("Picks (0)"):
            continue
        ax.plot([d for d, _ in pts], [y for _, y in pts], color=color, ls=ls, lw=lw, label=label)
        ends.append([pts[-1][1], f"{(pts[-1][1] - 1) * 100:+.0f}%", color, pts[-1][1]])
    ax.axhline(1, color=S.LINE, lw=0.8)
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.07
    ends.sort(key=lambda x: x[0])
    for i in range(1, len(ends)):   # keep the end labels apart
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + gap)
    for y, label, color, actual in ends:
        ax.plot([days[-1]], [actual], marker="o", ms=3, color=color, clip_on=False)
        ax.annotate(label, (days[-1], y), xytext=(5, 0), textcoords="offset points", va="center", fontsize=6.5,
                    color=S.INK2, annotation_clip=False)
    ax.set_ylabel(f"Growth of 1 ({ret})")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(ends), fontsize=6.5, borderaxespad=0.2)   # above the lines
    ax.margins(x=0.01)
    ax.spines["right"].set_visible(False)
    _title(ax, f"Since {days[0]:%d %b %Y}: " + ("picks against all screened" if cv["n_picks"] else "all screened (no picks)")
           + f" and the {index_name}", pad=18)
    return save(fig, path)
