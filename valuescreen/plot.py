"""The chart basics every chart shares: one style (Inter, no top/right spines, a faint grid), figure size in mm, the
resolution, saving, titles, money labels, the price line, a marked point and the per-share axis."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import style as S  # noqa: E402

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


DPI = {"value": 220}   # default; the HTML report sets its own (resolution) to keep the file small


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


def title(ax, text, pad=6):
    ax.set_title(text, loc="left", fontweight="semibold", color=S.INK, pad=pad)


def fmt_money(x, ccy):
    if x is None:
        return "–"
    nd = 0 if abs(x) >= 1000 else 2
    return f"{'−' if x < 0 else ''}{S.CURRENCY_SYMBOL.get(ccy, '')}{abs(x):,.{nd}f}"


def price_line(ax, price, ccy, vertical=False):
    if vertical:
        ax.axvline(price, color=S.PRICE, lw=1.4)
        ax.text(price, 1.0, f" price {fmt_money(price, ccy)}", transform=ax.get_xaxis_transform(), color=S.PRICE,
                fontsize=6.6, va="top")
    else:
        ax.axhline(price, color=S.PRICE, lw=1.4)
        ax.text(0.005, price, f"price {fmt_money(price, ccy)}", transform=ax.get_yaxis_transform(), color=S.PRICE,
                fontsize=6.6, va="bottom")


def mark(ax, x, y, text):
    ax.plot([x], [y], "o", ms=4.2, color=S.INK, zorder=5)
    ax.annotate(text, (x, y), xytext=(0, -10), textcoords="offset points", ha="center", fontsize=6.6)


def per_share_axis(ax, ccy):
    ax.set_ylabel(f"Per share ({S.CURRENCY_SYMBOL.get(ccy, ccy)})")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if abs(v) >= 10 else f"{v:,.1f}"))
