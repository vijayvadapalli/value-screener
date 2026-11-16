"""The backtest (valuescreen/backtest.py): only what was known on the start date, the same rules, returns since."""
import datetime as dt

import pytest

from valuescreen import backtest, loader, pricedb


def company(t, eps, years, promoters=None, quarters=None):
    return {"ticker": t, "name": f"{t} Ltd", "yahoo": f"{t}.NS", "sector": "Capital Goods",
            "v2": {"eps_annual": eps, "years": years,
                   "shareholding": {"quarters": quarters or [], "promoters": promoters or []}}}


def bars(con, sym, prices):
    """prices: {date: (close, adj_close)} – a daily row on each date."""
    pricedb.save_bars(con, sym, [(d, c, c, c, c, a, 1000) for d, (c, a) in prices.items()])
    pricedb.save_symbol(con, sym, "INR", "test")


def test_only_results_out_by_the_start_date_count():
    years = [f"Mar {y}" for y in range(2016, 2027)]
    v2 = {"years": years, "eps_annual": list(range(1, 12))}
    known = backtest.known_eps(v2, dt.date(2021, 5, 1))          # FY2021 results not out yet (60 days after 31 March)
    assert known[-1] == ("Mar 2020", 5.0)
    assert backtest.known_eps(v2, dt.date(2021, 6, 1))[-1] == ("Mar 2021", 6.0)
    assert backtest.known_eps({"years": ["Mar 2017\n   (S)"], "eps_annual": [2.0]}, dt.date(2018, 1, 1)) == [("Mar 2017", 2.0)]


def test_a_pick_its_returns_and_the_benchmarks(tmp_path):
    con = pricedb.connect(tmp_path / "p.sqlite")
    start, today = dt.date(2022, 11, 16), dt.date(2026, 11, 16)
    years = [f"Mar {y}" for y in range(2016, 2027)]
    grower = company("GROW", [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 4.0, 4.8, 5.8, 7.0], years)   # ~22%/yr, the future too
    flat = company("FLAT", [5.0] * 11, years)
    late = company("LATE", [1.0] * 11, years)
    for sym, p0, p1 in (("GROW.NS", 33.0, 99.0), ("FLAT.NS", 60.0, 66.0)):
        bars(con, sym, {"2016-01-04": (p0, p0), start.isoformat(): (p0, p0 * 0.9), today.isoformat(): (p1, p1)})
    bars(con, "LATE.NS", {"2024-01-02": (10.0, 10.0), today.isoformat(): (12.0, 12.0)})
    bars(con, "^NSEI", {"2016-01-04": (100.0, 100.0), start.isoformat(): (100.0, 100.0), today.isoformat(): (150.0, 150.0)})
    entries = [{"ticker": t} for t in ("GROW", "FLAT", "LATE")] + [{"ticker": "IDX", "market": True}]
    cos = {"GROW": grower, "FLAT": flat, "LATE": late}
    b = backtest.run_start(entries, cos, loader.load_config(), con, start, today, "^NSEI")
    assert [r["ticker"] for r in b["picks"]] == ["GROW"] and b["screened"] == 2 and b["skipped"]["not listed then"] == ["LATE"]
    pick = b["picks"][0]
    assert pick["last_fy"] == "Mar 2022" and pick["pe"] == pytest.approx(33.0 / 3.3)   # FY2022 EPS, nothing later
    assert pick["price_return"] == pytest.approx(2.0) and pick["total_return"] == pytest.approx(99.0 / (33.0 * 0.9) - 1)
    assert b["index_price"] == pytest.approx(0.5) and b["picks_total"] == pytest.approx(pick["total_return"])
    assert b["all_price"] == pytest.approx((2.0 + 0.1) / 2)


def test_one_year_short_of_history_uses_four_years(tmp_path):
    con = pricedb.connect(tmp_path / "p.sqlite")
    start, today = dt.date(2021, 11, 16), dt.date(2026, 11, 16)
    years = [f"Mar {y}" for y in range(2017, 2027)]                  # the data starts at FY2017
    c = company("GROW", [1.0, 1.3, 1.7, 2.2, 2.9, 3.5, 4.2, 5.0, 6.0, 7.2], years)
    bars(con, "GROW.NS", {"2016-01-04": (20.0, 20.0), start.isoformat(): (20.0, 20.0), today.isoformat(): (60.0, 60.0)})
    b = backtest.run_start([{"ticker": "GROW"}], {"GROW": c}, loader.load_config(), con, start, today, None)
    assert b["short_history"] == 1 and b["picks"][0]["growth_years"] == 4
    assert b["picks"][0]["eps_cagr_5y"] == pytest.approx((2.9 / 1.0) ** 0.25 - 1)   # FY2017 → FY2021 over 4 years


def test_promoter_holding_as_known_then():
    v2 = {"shareholding": {"quarters": ["Jun 2024", "Sep 2024", "Dec 2024"], "promoters": [0.70, 0.65, 0.60]}}
    assert backtest.promoters_then(v2, dt.date(2024, 11, 16)) == 0.65      # Dec 2024 not filed yet
    assert backtest.promoters_then(v2, dt.date(2020, 1, 1)) is None
