"""The US screen's database: one SQLite file (output/us/us_facts.sqlite – rebuildable, so not committed).

Tables
  companies(cik, ticker, yahoo, name, sector, industry, indexes, foreign)
  facts(cik, ns, tag, unit, start, end, val, form, fy, fp, filed, accn)   one row per reported figure. Restatements are
        kept beside the original (different accession number), and `filed` says when each became public – so a later
        back-test can use only what was known on a given day.
  prices(ticker, date, close)          daily closes from Yahoo (split-adjusted, not dividend-adjusted)
  splits(ticker, date, ratio)          share splits, to put old per-share figures on today's share basis
  runs(run_date, ticker, …)            each screen run's verdict, for judging the signals later
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (cik INTEGER, ticker TEXT PRIMARY KEY, yahoo TEXT, name TEXT, sector TEXT, industry TEXT,
                                      indexes TEXT, foreign_filer INTEGER);
CREATE TABLE IF NOT EXISTS facts (cik INTEGER, ns TEXT, tag TEXT, unit TEXT, start TEXT, end TEXT, val REAL, form TEXT,
                                  fy INTEGER, fp TEXT, filed TEXT, accn TEXT,
                                  PRIMARY KEY (cik, ns, tag, unit, start, end, accn));
CREATE INDEX IF NOT EXISTS facts_by_company ON facts (cik, tag);
CREATE TABLE IF NOT EXISTS prices (ticker TEXT, date TEXT, close REAL, PRIMARY KEY (ticker, date));
CREATE TABLE IF NOT EXISTS splits (ticker TEXT, date TEXT, ratio REAL, PRIMARY KEY (ticker, date));
CREATE TABLE IF NOT EXISTS runs (run_date TEXT, ticker TEXT, price REAL, value REAL, implied_growth REAL, signal TEXT,
                                 grade TEXT, PRIMARY KEY (run_date, ticker));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT", "20-F", "40-F"}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))


def save_companies(con, entries):
    con.executemany("INSERT OR REPLACE INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(e.get("cik"), e["ticker"], e["yahoo"], e["name"], e.get("sector"), e.get("industry"), ",".join(e["indexes"]),
                      int(bool(e.get("foreign")))) for e in entries])


def save_facts(con, cik: int, facts: dict, tags: dict):
    """Stores the wanted tags ({namespace: {tag, ...}}) of one company's SEC facts, replacing what was there."""
    rows = []
    for ns, wanted in tags.items():
        for tag in wanted:
            for unit, items in facts.get("facts", {}).get(ns, {}).get(tag, {}).get("units", {}).items():
                for f in items:
                    if f.get("form") in FORMS:
                        rows.append((cik, ns, tag, unit, f.get("start"), f["end"], f["val"], f.get("form"), f.get("fy"),
                                     f.get("fp"), f.get("filed"), f.get("accn")))
    con.execute("DELETE FROM facts WHERE cik = ?", (cik,))
    con.executemany("INSERT OR IGNORE INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def load_facts(con, cik: int, filed_by: str | None = None) -> dict:
    """One company's stored facts in the SEC's own shape ({"facts": {ns: {tag: {"units": {unit: [...]}}}}}), optionally
    only those filed on or before `filed_by` (YYYY-MM-DD)."""
    sql = "SELECT ns, tag, unit, start, end, val, form, fy, fp, filed, accn FROM facts WHERE cik = ?"
    args = [cik]
    if filed_by:
        sql += " AND filed <= ?"
        args.append(filed_by)
    out = {"facts": {}}
    for ns, tag, unit, start, end, val, form, fy, fp, filed, accn in con.execute(sql, args):
        item = {"end": end, "val": val, "form": form, "fy": fy, "fp": fp, "filed": filed, "accn": accn}
        if start:
            item["start"] = start
        out["facts"].setdefault(ns, {}).setdefault(tag, {}).setdefault("units", {}).setdefault(unit, []).append(item)
    return out


def save_prices(con, ticker: str, closes: list[tuple[str, float]], splits: list[tuple[str, float]]):
    con.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?)", [(ticker, d, c) for d, c in closes])
    con.executemany("INSERT OR REPLACE INTO splits VALUES (?, ?, ?)", [(ticker, d, r) for d, r in splits])


def closes(con, ticker: str) -> list[tuple[str, float]]:
    return con.execute("SELECT date, close FROM prices WHERE ticker = ? ORDER BY date", (ticker,)).fetchall()


def split_factor_since(con, ticker: str, day: str) -> float:
    """How many of today's shares one share on `day` became (product of later splits)."""
    factor = 1.0
    for (ratio,) in con.execute("SELECT ratio FROM splits WHERE ticker = ? AND date > ?", (ticker, day)):
        factor *= ratio
    return factor


def price_info(con, ticker: str) -> dict | None:
    """The latest close, its date, the 1-year change, and lookups for an old close and splits since a date."""
    import datetime as dt  # noqa: PLC0415
    rows = closes(con, ticker)
    if not rows:
        return None
    last_day, last = rows[-1]

    def on(day):
        earlier = [c for d, c in rows if d <= day]
        return earlier[-1] if earlier else None
    year_ago = on((dt.date.fromisoformat(last_day) - dt.timedelta(days=365)).isoformat())
    return {"price": last, "date": last_day, "change_1y": last / year_ago - 1 if year_ago else None, "on": on,
            "split_since": lambda day: split_factor_since(con, ticker, day), "closes": rows}


def companies(con) -> list[dict]:
    """The stored universe, in the shape us_universe.universe() returns."""
    return [{"cik": cik, "ticker": t, "yahoo": y, "name": n, "sector": sec, "industry": ind, "indexes": idx.split(",") if idx else [],
             "foreign": bool(f), "isin": None}
            for cik, t, y, n, sec, ind, idx, f in con.execute("SELECT cik, ticker, yahoo, name, sector, industry, indexes, foreign_filer "
                                                              "FROM companies ORDER BY ticker")]


def save_run(con, run_date: str, rows):
    con.executemany("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(run_date, r["ticker"], r.get("price"), r.get("v0"), r.get("implied_growth"), r.get("signal"), r.get("grade"))
                     for r in rows])
