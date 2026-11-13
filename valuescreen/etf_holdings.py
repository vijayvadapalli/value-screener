"""ETF holdings from the fund companies' own daily files – a maintained list of a sector without picking names by hand.

    holdings("GDX") → [{"etf", "ticker", "exchange", "name", "weight"}, ...]

Sources (free, no account): VanEck (Excel download; needs the page's cookies), Global X (dated CSV), Amplify (one CSV
for all its funds), Sprott (CSV embedded in the fund page). Tickers come in Bloomberg style ("NST AU", "APM CN");
yahoo_symbol() turns them into Yahoo symbols ("NST.AX", "APM.TO").
"""
from __future__ import annotations

import csv
import datetime as dt
import http.cookiejar
import io
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
FUNDS = {
    # ticker: (provider, page slug or fund code, metal)
    "GDX": ("vaneck", "gold-miners-etf-gdx", "gold"),
    "GDXJ": ("vaneck", "junior-gold-miners-etf-gdxj", "gold"),
    "SIL": ("globalx", "sil", "silver"),
    "COPX": ("globalx", "copx", "copper"),
    "SILJ": ("amplify", "SILJ", "silver"),
    "URNM": ("sprott", "urnm-sprott-uranium-miners-etf", "uranium"),
    "URNJ": ("sprott", "urnj-sprott-junior-uranium-miners-etf", "uranium"),
}
CASH_CODES = {"USD", "CAD", "AUD", "EUR", "GBP", "HKD", "MXN", "ZAR", "CNY", "JPY"}
# Bloomberg exchange code → Yahoo suffix. "CN" covers both Toronto exchanges; yahoo_symbol tries .TO first.
SUFFIX = {"US": "", "UN": "", "UW": "", "UQ": "", "CN": ".TO", "CT": ".TO", "CV": ".V", "AU": ".AX", "LN": ".L", "LI": ".IL",
          "HK": ".HK", "SJ": ".JO", "MM": ".MX", "PE": ".LM", "GR": ".DE", "SS": ".ST", "NO": ".OL", "JP": ".T", "IN": ".NS",
          "FP": ".PA", "SW": ".SW", "CI": ".SN", "BZ": ".SA", "KZ": ".IL", "IJ": ".JK", "PM": ".PS", "SP": ".SI",
          "PW": ".WA", "MF": ".MX", "FH": ".HE", "TI": ".IS", "KS": ".KS", "AB": ".SR"}


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _get(opener, url, referer=None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as resp:
        return resp.read()


def _xlsx_rows(data: bytes):
    """Rows of the first sheet of an .xlsx file, as lists of strings (standard library only)."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(f"{ns}t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{ns}si")]
    rows = []
    for r in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{ns}row"):
        vals = []
        for c in r.findall(f"{ns}c"):
            v = c.findtext(f"{ns}v", default="")
            if c.get("t") == "s":
                v = shared[int(v)]
            elif c.get("t") == "inlineStr":
                v = "".join(t.text or "" for t in c.iter(f"{ns}t"))
            vals.append(v)
        rows.append(vals)
    return rows


def _pct(text):
    try:
        return float(str(text).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def _vaneck(slug, etf):
    page = f"https://www.vaneck.com/us/en/investments/{slug}/holdings/"
    opener = _opener()
    _get(opener, page)   # sets the cookies the download needs
    rows = _xlsx_rows(_get(opener, page.replace("/holdings/", "/downloads/holdings/"), referer=page))
    head = next(i for i, r in enumerate(rows) if "Ticker" in r)
    cols = rows[head]
    out = []
    for r in rows[head + 1:]:
        d = dict(zip(cols, r))
        if d.get("Asset Class") == "Stock" and d.get("Ticker", "").strip():
            out.append({"etf": etf, "raw": d["Ticker"].strip(), "name": d.get("Holding Name", "").strip(), "weight": _pct(d.get("% of Net Assets"))})
    return out


def _globalx(code, etf):
    opener = _opener()
    for back in range(0, 7):   # the file is named after the last business day
        day = dt.date.today() - dt.timedelta(days=back)
        try:
            text = _get(opener, f"https://assets.globalxetfs.com/funds/holdings/{code}_full-holdings_{day:%Y%m%d}.csv").decode("utf-8", "replace")
        except urllib.error.HTTPError:
            continue
        lines = text.splitlines()
        head = next(i for i, line in enumerate(lines) if line.startswith("% of Net Assets"))
        return [{"etf": etf, "raw": d["Ticker"].strip(), "name": d["Name"].strip(), "weight": _pct(d["% of Net Assets"])}
                for d in csv.DictReader(lines[head:]) if (d.get("Ticker") or "").strip()]
    raise ValueError(f"no Global X holdings file for {etf} in the last week")


def _amplify(code, etf):
    text = _get(_opener(), "https://amplifyetfs.com/wp-content/uploads/feeds/AmplifyWeb.40XL.XL_Holdings.csv").decode("utf-8", "replace")
    return [{"etf": etf, "raw": d["StockTicker"].strip(), "name": d["SecurityName"].strip(), "weight": _pct(d["Weightings"])}
            for d in csv.DictReader(io.StringIO(text)) if d["Account"] == code and d.get("MoneyMarketFlag") != "Y" and d["StockTicker"].strip()]


def _sprott(slug, etf):
    html = _get(_opener(), f"https://sprottetfs.com/{slug}/").decode("utf-8", "replace")
    m = re.search(r'href="data:application/csv;charset=utf-8,([^"]+)"', html)
    if not m:
        raise ValueError(f"no holdings table on the Sprott page for {etf}")
    rows = csv.DictReader(io.StringIO(urllib.parse.unquote(m.group(1))))
    return [{"etf": etf, "raw": d["Symbol"].strip(), "name": d["Security"].strip(), "weight": _pct(d["Weight"])}
            for d in rows if d.get("Symbol", "").strip() and d.get("SEDOL", "").strip()]


PROVIDERS = {"vaneck": _vaneck, "globalx": _globalx, "amplify": _amplify, "sprott": _sprott}


def holdings(etf: str) -> list[dict]:
    provider, code, metal = FUNDS[etf.upper()]
    rows = PROVIDERS[provider](code, etf.upper())
    for r in rows:
        r["metal"] = metal
        r["ticker"], r["exchange"] = split_ticker(r["raw"])
    return rows


def split_ticker(raw: str) -> tuple[str, str]:
    """'NST AU' → ('NST', 'AU'); 'NEM' → ('NEM', 'US')."""
    parts = raw.replace("/", "-").replace("*", "").split()
    return (parts[0], parts[1].upper()) if len(parts) > 1 else (parts[0], "US")


def yahoo_symbol(ticker: str, exchange: str) -> str | None:
    """Yahoo symbol for a Bloomberg-style ticker, or None for an exchange this project does not map."""
    if exchange not in SUFFIX:
        return None
    if exchange == "HK":
        ticker = ticker.zfill(4)
    return ticker + SUFFIX[exchange]


_NOISE = r"\b(corp|corporation|inc|ltd|limited|plc|co|sa|ag|nv|the|tbk|pt|sab|de|cv|as|ab|holdings?|group|resources?|mining|mines|gold|silver|minerals?|energy|metals?)\b"


def name_key(name: str) -> str:
    """'Barrick Mining Corp' and 'BARRICK MINING CORP.' → the same key, to spot one company held by several ETFs."""
    words = re.sub(_NOISE, " ", re.sub(r"[^a-z0-9 ]", " ", name.lower())).split()
    return " ".join(words) or name.lower()


def universe(etfs: list[str]) -> list[dict]:
    """One entry per company across the ETFs: its Yahoo symbol (the US listing when an ETF holds that), name, the metals
    and ETFs it appears in, and its largest weight. Holdings on exchanges this project cannot map are left out."""
    by_company = {}
    for etf in etfs:
        for h in holdings(etf):
            symbol = yahoo_symbol(h["ticker"], h["exchange"])
            if symbol is None or h["ticker"] in CASH_CODES:   # unmapped exchange, or the fund's cash balance
                continue
            entry = by_company.setdefault(name_key(h["name"]), {"ticker": symbol, "yahoo": symbol, "name": h["name"],
                                                               "metals": [], "etfs": [], "weight": 0.0, "us": False})
            if h["exchange"] == "US" and not entry["us"]:
                entry.update(ticker=symbol, yahoo=symbol, us=True)
            if h["metal"] not in entry["metals"]:
                entry["metals"].append(h["metal"])
            if etf not in entry["etfs"]:
                entry["etfs"].append(etf)
            entry["weight"] = max(entry["weight"], h["weight"] or 0.0)
    out = sorted(by_company.values(), key=lambda e: -e["weight"])
    for e in out:
        e.pop("us")
    return out
