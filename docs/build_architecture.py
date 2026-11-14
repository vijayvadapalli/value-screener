"""Draws docs/architecture.png – the overview in docs/ARCHITECTURE.md. Edit COLUMNS and run again:

    python docs/build_architecture.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "valuescreen" / "fonts"
for f in FONTS.glob("*.ttf"):
    fm.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Inter" if any(FONTS.glob("*.ttf")) else "DejaVu Sans"

INK, MUTED, LINE = "#1A202C", "#4A5568", "#A0AEC0"
BLUE, GREEN, RED, PURPLE, AMBER = "#2B6CB0", "#2F855A", "#C53030", "#6B46C1", "#B7791F"
BUILT, NEXT, PRIVATE = "built", "next", "private"

# (column title, colour, [(title, [lines], status)])
COLUMNS = [
    ("SOURCES", BLUE, [
        ("Company results", ["releases each quarter", "read by you or Claude"], BUILT),
        ("Yahoo Finance", ["prices, statements,", "dividends, FX"], BUILT),
        ("SEC EDGAR", ["bulk company facts", "weekly, US filings"], BUILT),
        ("Screener.in", ["Indian companies (Nifty v2),", "lenders' NPA"], BUILT),
        ("Index & ETF lists", ["Wikipedia, NSE, VanEck,", "Global X, Amplify, Sprott"], BUILT),
        ("Your weekly report", ["levels, targets, stance"], PRIVATE),
        ("Long-term series", ["Cameco uranium spot,", "World Bank, IMF (monthly)"], BUILT),
    ]),
    ("STORES", PURPLE, [
        ("Company files (YAML)", ["core, tech, oil, miners,", "nifty50 – in git"], BUILT),
        ("config.yaml + lists", ["spot, FX, tiers, zones"], BUILT),
        ("us_facts.sqlite", ["SEC facts, 6y closes, runs"], BUILT),
        ("Caches & history", ["screen caches, runs.json,", "signals_log.csv"], BUILT),
        ("prices.sqlite", ["10y daily OHLCV, splits,", "dividends"], BUILT),
        ("Research files", ["data/private/research,", "per stock, weekly"], PRIVATE),
    ]),
    ("ENGINE", AMBER, [
        ("Valuation models", ["producer, cash-flow, NAV,", "growth DCF, leases"], BUILT),
        ("Rules", ["zones, signals, tiers, caps,", "flags, Nifty v2, bad loans"], BUILT),
        ("Profit vs price", ["grades A–D"], BUILT),
        ("Quick screens", ["miners ~270, S&P 500 +", "Nasdaq-100, NSE"], BUILT),
        ("Model portfolios", ["balanced, resources", "value-first, ≤ 15 names"], BUILT),
        ("Chart analytics", ["SMA, RSI, trend lines,", "levels; markets (price only)"], BUILT),
        ("Research merge", ["their levels vs our value"], PRIVATE),
    ]),
    ("OUTPUTS", GREEN, [
        ("Full reports", ["HTML + PDF + profit vs", "price, per list"], BUILT),
        ("Screen reports", ["miners, US, Nifty"], BUILT),
        ("Model portfolio pages", ["sleeves, entry, risk,", "market value"], BUILT),
        ("Charts in reports", ["interactive in HTML,", "static in PDF"], BUILT),
        ("Private research", ["research.html +", "weekly brief"], PRIVATE),
    ]),
    ("PUBLISHED", GREEN, [
        ("reports/", ["latest at fixed names", "in git"], BUILT),
        ("GitHub Pages", ["README links,", "screenshots"], BUILT),
        ("/weekly routine", ["prices, results, news,", "screens, reports, brief"], BUILT),
    ]),
]

W, H = 19.6, 12.6
COL_W, GAP, TOP, BOX_H, VGAP = 3.25, 0.62, 11.2, 1.3, 0.22


def box(ax, x, y, title, lines, colour, status):
    face = {"private": "#FDECEC", "next": "#FFFFFF"}.get(status, "#F7F7F5")
    edge = RED if status == PRIVATE else colour
    ax.add_patch(FancyBboxPatch((x, y), COL_W, BOX_H, boxstyle="round,pad=0.02,rounding_size=0.12", lw=2.2,
                                ec=edge, fc=face, ls="--" if status in (NEXT, PRIVATE) else "-"))
    ax.text(x + 0.16, y + BOX_H - 0.3, title, fontsize=12.5, weight="bold", color=INK, va="center")
    for i, line in enumerate(lines):
        ax.text(x + 0.16, y + BOX_H - 0.66 - i * 0.3, line, fontsize=10.2, color=MUTED, va="center")
    if status != BUILT:
        tag = "PRIVATE" if status == PRIVATE else "NEXT"
        ax.text(x + COL_W - 0.12, y + BOX_H - 0.3, tag, fontsize=8.5, weight="bold", ha="right", va="center",
                color=RED if status == PRIVATE else BLUE)


def draw(path):
    fig, ax = plt.subplots(figsize=(W, H), dpi=110)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.text(0.3, H - 0.45, "Value Screener – architecture", fontsize=20, weight="bold", color=INK)
    ax.text(0.3, H - 0.9, "Value from reported numbers vs today's price · solid = built · dashed = next · red = private, "
            "never in git or on Pages", fontsize=11.5, color=MUTED)
    xs = [0.3 + i * (COL_W + GAP) for i in range(len(COLUMNS))]
    for x, (title, colour, boxes) in zip(xs, COLUMNS):
        ax.text(x, TOP + 0.15, title, fontsize=11.5, weight="bold", color=colour)
        for j, (t, lines, status) in enumerate(boxes):
            box(ax, x, TOP - (j + 1) * (BOX_H + VGAP) + VGAP, t, lines, colour, status)
    # flow arrows between columns
    for i, x in enumerate(xs[:-1]):
        for row in (1, 3, 5):   # between rows that exist in both columns
            if row < len(COLUMNS[i][2]) and row < len(COLUMNS[i + 1][2]):
                yy = TOP - (row + 1) * (BOX_H + VGAP) + VGAP + BOX_H / 2
                ax.annotate("", xy=(x + COL_W + GAP - 0.08, yy), xytext=(x + COL_W + 0.08, yy),
                            arrowprops=dict(arrowstyle="-|>", color=LINE, lw=2))
    # the private boundary: only plain levels cross to the public charts
    ax.text(0.3, 0.35, "Only plain support / resistance prices cross from the private report to the public charts "
            "(as unnamed 'watched levels'); targets, stance, notes and the source stay private. "
            "Educational framework, not investment advice.", fontsize=10, color=RED)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    draw(HERE / "architecture.png")
    print(HERE / "architecture.png")
