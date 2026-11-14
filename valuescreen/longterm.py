"""Long-term monthly price series kept in data/longterm (World Bank gold and silver from 1960, IMF uranium from 1992,
Cameco's month-end uranium spot price from 1988) – for the monthly charts before Yahoo's daily futures history begins,
and for uranium, which has no daily series on Yahoo. See data/longterm/README.md for the sources.

    series(name) → [(YYYY-MM-01, price)] for "gold", "silver", "uranium" or "uranium_spot", oldest first ([] if missing)

    python -m valuescreen.longterm      # refresh uranium_spot from Cameco's uranium price page (part of the weekly)
"""
from __future__ import annotations

import csv
import html as htmllib
import re
import sys
import urllib.request

from . import loader

FOLDER = loader.ROOT / "data" / "longterm"
COLUMNS = {"gold": ("gold_silver_monthly.csv", "gold_usd_oz"), "silver": ("gold_silver_monthly.csv", "silver_usd_oz"),
           "uranium": ("uranium_monthly.csv", "uranium_usd_lb"),
           "uranium_spot": ("uranium_spot_monthly.csv", "uranium_spot_usd_lb")}
NOTES = {"uranium": "IMF monthly uranium price (not spot – runs below it), 1992 onwards; spot-based levels are not drawn",
         "uranium_spot": "Uranium spot price, US$/lb, month-end, from Cameco (UxC / TradeTech average), 1988 onwards"}
CAMECO_URL = "https://www.cameco.com/invest/markets/uranium-price"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def series(name: str) -> list[tuple[str, float]]:
    file, column = COLUMNS[name.lower()]
    path = FOLDER / file
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v = row.get(column)
            if v not in (None, ""):
                out.append((f"{row['month']}-01", float(v)))
    return out


def parse_cameco(page: str) -> list[tuple[str, float]]:
    """[(YYYY-MM, spot)] from the first table on Cameco's uranium price page: date (YYYY/MM/DD), spot, long-term.
    One value per month – the last one given for that month."""
    table = re.search(r"<table.*?</table>", page, re.S)
    if not table:
        raise ValueError("no price table on the Cameco page")
    months = {}
    for row in re.findall(r"<tr.*?</tr>", table.group(0), re.S):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if len(cells) >= 2 and re.fullmatch(r"\d{4}/\d{2}/\d{2}", cells[0]) and re.fullmatch(r"\d+(\.\d+)?", cells[1]):
            months[cells[0][:7].replace("/", "-")] = float(cells[1])
    if len(months) < 120:
        raise ValueError(f"only {len(months)} months found on the Cameco page – has the layout changed?")
    return sorted(months.items())


def refresh_uranium_spot(fetch=None) -> tuple[int, str]:
    """Downloads Cameco's month-end spot prices into data/longterm/uranium_spot_monthly.csv. Returns (months, last month)."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
    rows = parse_cameco(fetch(CAMECO_URL))
    file, column = COLUMNS["uranium_spot"]
    with (FOLDER / file).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", column])
        w.writerows(rows)
    return len(rows), rows[-1][0]


def main() -> int:
    n, last = refresh_uranium_spot()
    print(f"uranium spot (Cameco): {n} months to {last} → {FOLDER / COLUMNS['uranium_spot'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
