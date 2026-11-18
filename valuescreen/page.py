"""The page shell every report shares, and the CSS / JavaScript kept as files in valuescreen/assets/.

    document(title, css, body, scripts="", head="", main_attrs="")  → a whole HTML page
    asset(name)        → the text of valuescreen/assets/<name>
    report_css()       → assets/report.css with the palette filled in (the base style of every page)
    chart_scripts()    → Lightweight Charts, the average colours and assets/charts.js, for pages with price charts
    write_shared(folder), shared_style(prefix), shared_scripts(prefix)   → the same as files, for multi-page reports

assets/report.css uses $NAME placeholders for the colours in style.py (CSS itself never uses $).
"""
from __future__ import annotations

import datetime as dt
import hashlib
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


# ---- multi-page reports: the styles and scripts as files every page shares (the browser loads them once)

@lru_cache(maxsize=1)
def shared_files() -> dict[str, str]:
    """The shared files by name: the filled-in stylesheet, the table script, the chart script, the charting library
    and the moving-average colours."""
    from .price_chart import SMA_COLOURS  # noqa: PLC0415
    files = {"report.css": report_css(), "report.js": asset("report.js"), "charts.js": asset("charts.js"),
             "sma-colours.js": f"window.PC_SMA_COLOURS = {json.dumps({str(k): v for k, v in SMA_COLOURS.items()})};"}
    if VENDOR.exists():
        files["lightweight-charts.js"] = VENDOR.read_text(encoding="utf-8")
    return files


def write_shared(folder: Path) -> Path:
    """Writes the shared files into `folder` (reports/assets/ when published)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in shared_files().items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def _src(prefix: str, name: str) -> str:
    """A shared file's address with its content's short hash (`report.css?v=1a2b3c4d`): GitHub Pages lets browsers keep
    these files for 10 minutes, and a changed file gets a new address, so a new page never runs with an old stylesheet."""
    return f"{prefix}{name}?v={hashlib.sha1(shared_files()[name].encode()).hexdigest()[:8]}"


def shared_style(prefix: str) -> str:
    return f'<link rel="stylesheet" href="{_src(prefix, "report.css")}">'


def shared_scripts(prefix: str, charts: bool = True, table: bool = False) -> str:
    """Script tags for the shared files; `prefix` is the path to the assets folder ("assets/" or "../assets/")."""
    out = f'<script src="{_src(prefix, "report.js")}"></script>' if table else ""
    if charts and VENDOR.exists():
        out += "".join(f'<script src="{_src(prefix, n)}"></script>' for n in ("lightweight-charts.js", "sma-colours.js", "charts.js"))
    return out


COPYRIGHT_HOLDER = "Vijay Vadapalli"
DISCLAIMER = ("<b>Disclaimer.</b> For education and research only – not investment advice, a recommendation, or an offer to buy "
              "or sell any security. Figures come from company filings and public data providers and may be wrong, late or "
              "incomplete; values come from a mechanical model and are not forecasts. Past results, backtests included, do not "
              "predict future returns. Do your own research, and talk to a licensed adviser before you invest. The author may "
              "hold positions in companies shown.")


def legal_footer() -> str:
    """The disclaimer and copyright line that closes every page (the README carries the same text)."""
    return (f'<footer class="legal"><p>{DISCLAIMER}</p>'
            f'<p>© {dt.date.today().year} {COPYRIGHT_HOLDER}. All rights reserved.</p></footer>')


def document(title: str, css: str, body: str, scripts: str = "", head: str = "", main_attrs: str = "") -> str:
    """A whole page: `title` is already escaped HTML, `head` goes before the title (e.g. a robots tag). Every page
    ends with the disclaimer and copyright line (legal_footer)."""
    return (f"{HEAD}{head}<title>{title}</title><style>{css}</style></head><body><main{main_attrs}>{body}"
            f"{legal_footer()}</main>{scripts}</body></html>")
