"""Ranked CSV, the signal log and the two cross-company scenario heatmaps.
The reports themselves are html_report.py (combined, linked) and pdf.py / profit_vs_price.py (for printing)."""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import numpy as np

from . import style as S
from .charts import GAP_CMAP, new_figure, save

CSV_COLS = ["group", "rank", "ticker", "name", "model", "sector", "tier", "period", "price", "price_ccy", "price_date", "oe_rep",
            "oe", "nc", "v_low", "v_high", "nav", "coverage_lo", "coverage_hi", "margin_of_safety", "pe", "primary_metal",
            "implied_metal_hi", "implied_growth", "cost_ratio", "zone", "signal", "buy_level", "add_level", "put_level",
            "call_level", "stale", "stale_reason", "flags"]
SIGNAL_LOG_COLS = ["run_date", "ticker", "price", "price_date", "value_low", "value_high", "zone", "put_level", "call_level", "stale"]


def _fmt(x, nd=2):
    if x is None or x == "":
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    if isinstance(x, list):
        return "; ".join(str(i) for i in x)
    return str(x)


def write_csv(vals, grow, path: Path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for group, rows in (("metals_energy", vals), ("growth", grow)):
            for r in rows:
                w.writerow([group] + [_fmt(r.get(k), 4) for k in CSV_COLS[1:]])


def append_signals(vals, grow, path: Path, run_at: dt.date):
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(SIGNAL_LOG_COLS)
        for r in vals + grow:
            w.writerow([run_at.isoformat(), r["ticker"], _fmt(r["price"], 4), r["price_date"], _fmt(r["v_low"], 4),
                        _fmt(r["v_high"], 4), r["zone"], _fmt(r.get("put_level"), 4), _fmt(r.get("call_level"), 4), r["stale"]])


# ------------------------------------------------------------------------------------------------- heatmaps
def heatmap(rows, cols, path: Path):
    """One row per company: (label, price, [(low, high) value per scenario column]), coloured by the gap to the price."""
    if not rows:
        return None
    rows = [(label, price, [(max(lo, 0), max(hi, 0)) for lo, hi in values]) for label, price, values in rows]
    gap = np.array([[((lo + hi) / 2) / price - 1 for lo, hi in values] for _, price, values in rows])
    fig, ax = new_figure((210, 11 * len(rows) + 30))
    ax.imshow(np.clip(gap, -0.6, 0.6), cmap=GAP_CMAP, vmin=-0.6, vmax=0.6, aspect="auto")
    for i, (_, _, values) in enumerate(rows):
        for j, (lo, hi) in enumerate(values):
            strong = abs(gap[i, j]) > 0.42
            text = f"{lo:,.2f}" if abs(hi - lo) < 1e-9 else f"{lo:,.2f}–{hi:,.2f}"
            ax.text(j, i - 0.13, text, ha="center", va="center", fontsize=6.6, fontweight="semibold",
                    color="white" if strong else S.INK)
            ax.text(j, i + 0.23, f"{gap[i, j]*100:+.0f}%", ha="center", va="center", fontsize=6,
                    color="white" if strong else S.INK2)
    ax.set_yticks(range(len(rows)), [f"{label}  ·  now {price:,.2f}" for label, price, _ in rows], fontsize=7)
    ax.set_xticks(range(len(cols)), cols, fontsize=6.8)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    ax.grid(which="minor", color="white", lw=2)
    ax.tick_params(which="minor", length=0)
    return save(fig, path)


def make_heatmaps(vals, grow, cfg, out: Path):
    sp = cfg["spot"]
    metal_cols = [(f"{s*100:+.0f}%" if s else "Spot") + f"\nAu {sp['gold']*(1+s):,.0f} · Ag {sp['silver']*(1+s):.1f}\nU {sp['uranium']*(1+s):.0f}"
                  for s in cfg["metal_scenarios"]]
    growth_cols = [f"{g*100:+.0f}%/yr" if g else "No growth" for g in cfg["growth_scenarios"]]
    label = lambda r: f"{r['rank']}. {r['ticker']}"  # noqa: E731
    metals = heatmap([(label(r), r["price"], r["scenarios"]) for r in vals], metal_cols, out / "heatmap_metals.png")
    growth = heatmap([(label(r), r["price"], r["scenarios"]) for r in grow], growth_cols, out / "heatmap_growth.png")
    return metals, growth
