"""Price history database and the update tool's offline parts (no network)."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from valuescreen import pricedb

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("update_history", ROOT / "tools" / "update_history.py")
uh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uh)


@pytest.fixture
def con(tmp_path):
    return pricedb.connect(tmp_path / "p.sqlite")


def bar(d, c, v=100.0):
    return (d, c - 1, c + 1, c - 2, c, c, v)


def test_save_read_and_overlap(con):
    pricedb.save_bars(con, "NEM", [bar("2026-01-05", 10), bar("2026-01-06", 11)])
    pricedb.save_bars(con, "NEM", [bar("2026-01-06", 12), bar("2026-01-07", 13)])   # overlapping update replaces the day
    assert [b["close"] for b in pricedb.bars(con, "NEM")] == [10, 12, 13]
    assert pricedb.last_date(con, "NEM") == "2026-01-07"
    assert pricedb.closes(con, "NEM", start="2026-01-06") == [12, 13]
    assert pricedb.last_date(con, "XXX") is None


def test_replace_after_split(con):
    pricedb.save_bars(con, "NVDA", [bar("2024-06-07", 1200), bar("2024-06-10", 121)])
    pricedb.replace_bars(con, "NVDA", [bar("2024-06-07", 120), bar("2024-06-10", 121)])
    assert pricedb.closes(con, "NVDA") == [120, 121]
    assert pricedb.needs_full_refresh(["2024-06-10"], "2024-06-07")
    assert not pricedb.needs_full_refresh(["2024-06-10"], "2024-06-10")   # already stored after the split
    assert not pricedb.needs_full_refresh([], "2024-06-07")
    assert not pricedb.needs_full_refresh(["2024-06-10"], None)            # first download is full anyway


def test_actions_and_symbols(con):
    pricedb.save_bars(con, "YCA.L", [bar("2026-11-12", 521), bar("2026-11-13", 515)])
    pricedb.save_actions(con, "YCA.L", [("2026-11-13", "dividend", 5.0)])
    pricedb.save_symbol(con, "YCA.L", "GBp", "core")
    assert pricedb.actions(con, "YCA.L", "dividend") == [{"date": "2026-11-13", "kind": "dividend", "value": 5.0}]
    info = pricedb.info(con, "YCA.L")
    assert (info["currency"], info["first_date"], info["last_date"], info["lists"]) == ("GBp", "2026-11-12", "2026-11-13", "core")
    pricedb.save_symbol(con, "YCA.L", None, "core")        # an update without a currency keeps the stored one
    assert pricedb.info(con, "YCA.L")["currency"] == "GBp"
    assert pricedb.to_major(515.0, "GBp") == (5.15, "GBP")
    assert pricedb.to_major(10.0, "USD") == (10.0, "USD")


def test_resample():
    daily = [{"date": d, "open": o, "high": h, "low": lo, "close": c, "adj_close": c, "volume": 10}
             for d, o, h, lo, c in [("2026-11-02", 10, 12, 9, 11), ("2026-11-03", 11, 15, 10, 14), ("2026-11-06", 14, 14, 8, 9),
                                    ("2026-11-09", 9, 10, 7, 8)]]
    w = pricedb.resample(daily, "W")
    assert [(x["date"], x["open"], x["high"], x["low"], x["close"], x["volume"]) for x in w] == [
        ("2026-11-06", 10, 15, 8, 9, 30), ("2026-11-09", 9, 10, 7, 8, 10)]
    assert len(pricedb.resample(daily, "M")) == 1
    with pytest.raises(ValueError):
        pricedb.resample(daily, "D")


def test_parse_download_frame():
    idx = pd.to_datetime(["2026-11-12", "2026-11-13"])
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"],
                                       ["NEM", "MU"]], names=["Price", "Ticker"])
    #           Open    High    Low     Close   Adj     Volume     Dividends  Splits   (NEM, MU each)
    data = pd.DataFrame([[1, 1, 3, 3, 2, 2, 2, 4, 2, 4, 100, 200, 0.25, 0, 0, 0],
                         [1, 1, 3, 3, 2, 2, 2, 4, 2, 4, 100, 210, 0, 0, 0, 4]], index=idx, columns=cols, dtype=float)
    data[("Close", "NEM")] = [2.0, float("nan")]
    rows, splits, divs = uh.parse(data, "NEM")
    assert rows == [("2026-11-12", 1.0, 3.0, 2.0, 2.0, 2.0, 100.0)]          # the day without a close is skipped
    assert divs == [("2026-11-12", "dividend", 0.25)] and splits == []
    _, mu_splits, _ = uh.parse(data, "MU")
    assert mu_splits == [("2026-11-13", "split", 4.0)]
    assert uh.parse(data, "AAPL") == ([], [], [])


def test_symbols_for_lists():
    s = uh.symbols_for(["core", "oil", "miners"])
    assert s["IVN.TO"] == ["core"] and s["CNQ.TO"] == ["oil"] and s["YCA.L"] == ["core"]
    assert "OGC" in s and "2899.HK" in s and "NST.AX" not in s   # miners: only companies with a full file
