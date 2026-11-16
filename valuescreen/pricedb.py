"""Daily price history: one SQLite file (output/prices.sqlite – rebuildable from Yahoo, so not committed).

Tables
  bars(ticker, date, open, high, low, close, adj_close, volume)   one row per trading day. Open/high/low/close are
        split-adjusted as Yahoo gives them (not dividend-adjusted); adj_close also takes dividends into account.
  actions(ticker, date, kind, value)     kind = 'split' (ratio, e.g. 4.0 for a 4-for-1) or 'dividend' (per share)
  symbols(ticker, currency, first_date, last_date, updated, lists)
        currency is Yahoo's: 'GBp' and 'ZAc' are pence and cents – a price in those is 100x the pound or rand figure.

`ticker` is the Yahoo symbol (NEM, YCA.L, ABRA.TO). Pure storage and reading here; downloading is in
tools/update_history.py, so this module never touches the network.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from . import loader

DB = loader.output_folder() / "prices.sqlite"
SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, adj_close REAL,
                                 volume REAL, PRIMARY KEY (ticker, date));
CREATE TABLE IF NOT EXISTS actions (ticker TEXT, date TEXT, kind TEXT, value REAL, PRIMARY KEY (ticker, date, kind));
CREATE TABLE IF NOT EXISTS symbols (ticker TEXT PRIMARY KEY, currency TEXT, first_date TEXT, last_date TEXT,
                                    updated TEXT, lists TEXT);
CREATE TABLE IF NOT EXISTS depth (ticker TEXT PRIMARY KEY, years INTEGER);   -- how far back a symbol was downloaded
"""
MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def depth(con, ticker: str) -> int | None:
    """How many years of history were asked for when the symbol was (re)loaded; None if not recorded (10 by default)."""
    row = con.execute("SELECT years FROM depth WHERE ticker = ?", (ticker,)).fetchone()
    return row[0] if row else None


def set_depth(con, ticker: str, years: int):
    con.execute("INSERT OR REPLACE INTO depth VALUES (?, ?)", (ticker, years))


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


# ------------------------------------------------------------------------------------------------- writing
def save_bars(con, ticker: str, rows) -> int:
    """rows: (date 'YYYY-MM-DD', open, high, low, close, adj_close, volume); existing days are replaced."""
    rows = [(ticker, *r) for r in rows if r[4] is not None]
    con.executemany("INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def replace_bars(con, ticker: str, rows) -> int:
    """All of a ticker's history at once – used after a split, when Yahoo restates every earlier price."""
    con.execute("DELETE FROM bars WHERE ticker = ?", (ticker,))
    return save_bars(con, ticker, rows)


def save_actions(con, ticker: str, actions) -> int:
    """actions: (date, kind, value) with kind 'split' or 'dividend'."""
    con.executemany("INSERT OR REPLACE INTO actions VALUES (?, ?, ?, ?)", [(ticker, *a) for a in actions])
    return len(actions)


def save_symbol(con, ticker: str, currency: str | None, lists: str):
    first, last = con.execute("SELECT MIN(date), MAX(date) FROM bars WHERE ticker = ?", (ticker,)).fetchone()
    old = info(con, ticker)
    con.execute("INSERT OR REPLACE INTO symbols VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, currency or (old or {}).get("currency"), first, last, dt.date.today().isoformat(), lists))


# ------------------------------------------------------------------------------------------------- reading
def info(con, ticker: str) -> dict | None:
    row = con.execute("SELECT ticker, currency, first_date, last_date, updated, lists FROM symbols WHERE ticker = ?",
                      (ticker,)).fetchone()
    return dict(zip(("ticker", "currency", "first_date", "last_date", "updated", "lists"), row)) if row else None


def last_date(con, ticker: str) -> str | None:
    return con.execute("SELECT MAX(date) FROM bars WHERE ticker = ?", (ticker,)).fetchone()[0]


def bars(con, ticker: str, start: str | None = None, end: str | None = None) -> list[dict]:
    """Daily bars, oldest first: [{date, open, high, low, close, adj_close, volume}]."""
    sql, args = "SELECT date, open, high, low, close, adj_close, volume FROM bars WHERE ticker = ?", [ticker]
    if start:
        sql += " AND date >= ?"
        args.append(start)
    if end:
        sql += " AND date <= ?"
        args.append(end)
    keys = ("date", "open", "high", "low", "close", "adj_close", "volume")
    return [dict(zip(keys, r)) for r in con.execute(sql + " ORDER BY date", args)]


def closes(con, ticker: str, start: str | None = None) -> list[float]:
    return [b["close"] for b in bars(con, ticker, start)]


def actions(con, ticker: str, kind: str | None = None) -> list[dict]:
    sql, args = "SELECT date, kind, value FROM actions WHERE ticker = ?", [ticker]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    return [dict(zip(("date", "kind", "value"), r)) for r in con.execute(sql + " ORDER BY date", args)]


def symbols(con) -> list[dict]:
    keys = ("ticker", "currency", "first_date", "last_date", "updated", "lists")
    return [dict(zip(keys, r)) for r in con.execute(f"SELECT {', '.join(keys)} FROM symbols ORDER BY ticker")]


def resample(daily: list[dict], period: str) -> list[dict]:
    """Daily bars → weekly ('W', weeks ending Friday) or monthly ('M') bars: first open, highest high, lowest low,
    last close, summed volume; dated by the period's last trading day."""
    if period not in ("W", "M"):
        raise ValueError("period must be 'W' or 'M'")
    out, key_of = [], (lambda d: d.isocalendar()[:2]) if period == "W" else (lambda d: (d.year, d.month))
    for b in daily:
        k = key_of(dt.date.fromisoformat(b["date"]))
        if out and out[-1]["_k"] == k:
            o = out[-1]
            o.update(date=b["date"], high=max(o["high"], b["high"]), low=min(o["low"], b["low"]), close=b["close"],
                     adj_close=b["adj_close"], volume=(o["volume"] or 0) + (b["volume"] or 0))
        else:
            out.append(dict(b, _k=k))
    for o in out:
        del o["_k"]
    return out


def needs_full_refresh(new_split_dates, stored_last: str | None) -> bool:
    """A split after the last stored day means Yahoo has restated every earlier price – reload the whole history."""
    return bool(stored_last) and any(d > stored_last for d in new_split_dates)


def to_major(price: float, currency: str | None) -> tuple[float, str | None]:
    """A price in pence or cents → pounds or rand (534 GBp → 5.34 GBP)."""
    if currency in MINOR_UNITS:
        major, div = MINOR_UNITS[currency]
        return price / div, major
    return price, currency
