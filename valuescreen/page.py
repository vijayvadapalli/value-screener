"""The page shell every report shares, and the CSS / JavaScript kept as files in valuescreen/assets/.

    document(title, css, body, scripts="", head="", main_attrs="")  → a whole HTML page
    asset(name)        → the text of valuescreen/assets/<name>
    report_css()       → assets/report.css with the palette filled in (the base style of every page)
    chart_scripts()    → Lightweight Charts, the average colours and assets/charts.js, for pages with price charts

assets/report.css uses $NAME placeholders for the colours in style.py (CSS itself never uses $).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from string import Template

from . import style as S

ASSETS = Path(__file__).parent / "assets"
VENDOR = Path(__file__).parent / "vendor" / "lightweight-charts.standalone.production.js"
HEAD = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n')


@lru_cache(maxsize=None)
def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def report_css() -> str:
    from .profit_vs_price import GRADE_COLOUR  # noqa: PLC0415 - the grade colours live with the grades
    return Template(asset("report.css")).substitute(
        INK=S.INK, INK2=S.INK2, LINE=S.LINE, MUTED=S.MUTED, PRICE=S.PRICE, SOFT=S.SOFT,
        BLUE=S.SIGNAL["blue"], GREEN=S.SIGNAL["green"], RED=S.SIGNAL["red"],
        TINT_BLUE=S.TINT["blue"][2], TINT_GREEN=S.TINT["green"][2], TINT_RED=S.TINT["red"][2],
        GRADE_A=GRADE_COLOUR["A"], GRADE_B=GRADE_COLOUR["B"], GRADE_C=GRADE_COLOUR["C"], GRADE_D=GRADE_COLOUR["D"])


def chart_scripts() -> str:
    """The scripts the interactive price charts need, or "" when the charting library is missing."""
    if not VENDOR.exists():
        return ""
    from .price_chart import SMA_COLOURS  # noqa: PLC0415
    return (f"<script>{VENDOR.read_text(encoding='utf-8')}</script>"
            f"<script>window.PC_SMA_COLOURS = {json.dumps({str(k): v for k, v in SMA_COLOURS.items()})};</script>"
            f"<script>{asset('charts.js')}</script>")


def document(title: str, css: str, body: str, scripts: str = "", head: str = "", main_attrs: str = "") -> str:
    """A whole page: `title` is already escaped HTML, `head` goes before the title (e.g. a robots tag)."""
    return (f"{HEAD}{head}<title>{title}</title><style>{css}</style></head><body><main{main_attrs}>{body}</main>"
            f"{scripts}</body></html>")
