"""One look for the reports and charts: the Inter typeface (SIL Open Font License, valuescreen/fonts) and a small palette.

Signals: green = buy / start a position, blue = watch / hold, red = expensive or no valid value.
Rows are tinted in the signal's colour; the tint is darkest for tier A (or the largest market values) and lightest for C.
"""
from __future__ import annotations

from pathlib import Path

FONTS = Path(__file__).parent / "fonts"

INK = "#14171C"
INK2 = "#4B5361"
MUTED = "#8B93A1"
LINE = "#E3E6EB"
SOFT = "#F5F6F8"
WHITE = "#FFFFFF"
PRICE = "#E2722F"        # the market price, everywhere

SIGNAL = {"green": "#17895F", "blue": "#2F64CF", "red": "#C8463D"}
SIGNAL_TEXT = {"green": "Green", "blue": "Blue", "red": "Red"}
# tints by strength: 0 = darkest (tier A / ≥ $100bn) … 3 = lightest
TINT = {
    "green": ["#CBEBDC", "#DCF2E7", "#EAF7F0", "#F4FBF7"],
    "blue": ["#D3E0F8", "#E1EAFA", "#ECF2FC", "#F5F8FE"],
    "red": ["#F5D5D1", "#F9E2DF", "#FBEDEB", "#FDF6F5"],
}
TIER_STRENGTH = {"A": 0, "B": 1, "C": 2}
SHADE_STRENGTH = {"darkest": 0, "medium": 1, "light": 2, "lightest": 3}
BAND = {"buy": "#DDF1E7", "watch": "#E3EBFA", "hold": "#EEF0F3", "sell": "#F8E0DD"}

_registered = {}


def font_family() -> str:
    """Registers Inter with matplotlib once; falls back to DejaVu Sans if the font files are missing."""
    if "mpl" in _registered:
        return _registered["mpl"]
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    from matplotlib import font_manager as fm  # noqa: PLC0415
    family = "DejaVu Sans"
    files = [FONTS / f"Inter-{w}.ttf" for w in ("Regular", "Medium", "SemiBold", "Bold")]
    if all(f.exists() for f in files):
        for f in files:
            fm.fontManager.addfont(str(f))
        family = "Inter"
    _registered["mpl"] = family
    return family


def tint(signal: str, strength: int | None) -> str:
    return TINT.get(signal, TINT["blue"])[3 if strength is None else max(0, min(3, strength))]


CURRENCY_SYMBOL = {"USD": "$", "CAD": "C$", "AUD": "A$", "EUR": "€", "GBP": "£", "INR": "₹", "TWD": "NT$", "HKD": "HK$", "KZT": "₸"}


def money(x, ccy="USD", nd=2):
    """$1,234.56 · C$12.30 · 534p for pence-quoted GBP prices below 100 are shown in £."""
    if x is None:
        return "–"
    sym = CURRENCY_SYMBOL.get(ccy, ccy + " ")
    sign = "−" if x < 0 else ""
    return f"{sign}{sym}{abs(x):,.{nd}f}"


def pct(x, nd=0, signed=True):
    if x is None:
        return "–"
    if x < -2:
        return "< −200%"
    s = f"{x*100:+.{nd}f}%" if signed else f"{x*100:.{nd}f}%"
    return s.replace("-", "−")
