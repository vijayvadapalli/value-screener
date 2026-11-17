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


# ---- the US version: each company rebuilt exactly as filed by the start date

SH = 1e9   # shares before the 2:1 split of 2023-06-01


def sec_facts():
    """A company growing EPS 20% a year (FY = calendar year), shares 1bn until a 2:1 split on 2023-06-01; FY2020's EPS
    restated to 0.50 in a filing of 2023 and a huge 2023 quarter – both after the start date, so both must be ignored."""
    eps = {y: 1.0 * 1.2 ** (y - 2016) for y in range(2016, 2023)}
    f = lambda start, end, val, form, filed, accn: {"start": start, "end": end, "val": val, "form": form, "filed": filed,  # noqa: E731
                                                   "accn": accn, "fy": int(end[:4]), "fp": "FY"}
    i = lambda end, val, form, filed, accn: {"end": end, "val": val, "form": form, "filed": filed, "accn": accn,  # noqa: E731
                                            "fy": int(end[:4]), "fp": "Q"}
    ni, ep, q = [], [], []
    for y in range(2016, 2022):
        filed, accn = f"{y + 1}-02-15", f"K{y}"
        ni.append(f(f"{y}-01-01", f"{y}-12-31", eps[y] * SH, "10-K", filed, accn))
        ep.append(f(f"{y}-01-01", f"{y}-12-31", eps[y], "10-K", filed, accn))
    ep.append(f("2020-01-01", "2020-12-31", 0.50, "10-K/A", "2023-03-01", "KA2020"))
    quarters = [("2021-10-01", "2021-12-31", 2021, "2022-02-15"), ("2022-01-01", "2022-03-31", 2022, "2022-05-05"),
                ("2022-04-01", "2022-06-30", 2022, "2022-08-05"), ("2022-07-01", "2022-09-30", 2022, "2022-11-01"),
                ("2022-10-01", "2022-12-31", 2022, "2023-02-15")]
    for s, e, y, filed in quarters:
        q.append(f(s, e, eps[y] / 4 * SH, "10-Q", filed, f"Q{e}"))
    q.append(f("2023-01-01", "2023-03-31", 50 * SH, "10-Q", "2023-05-05", "Q2023-03-31"))
    shares = [i("2022-10-25", SH, "10-Q", "2022-11-01", "Q2022-09-30"), i("2023-07-25", 2 * SH, "10-Q", "2023-08-01", "Q2023-06-30")]
    units = lambda items: {"units": {"USD": items}}  # noqa: E731
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": ni + q}},
                                  "EarningsPerShareDiluted": {"units": {"USD/shares": ep}},
                                  "CashAndCashEquivalentsAtCarryingValue": units([i("2022-09-30", 0.0, "10-Q", "2022-11-01", "Q2022-09-30")]),
                                  "LongTermDebt": units([i("2022-09-30", 0.0, "10-Q", "2022-11-01", "Q2022-09-30")]),
                                  "StockholdersEquity": units([i("2022-09-30", 10 * SH, "10-Q", "2022-11-01", "Q2022-09-30")])},
                      "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}}}}


def test_us_company_rebuilt_as_filed_by_the_start_date(tmp_path):
    from valuescreen import factsdb
    from valuescreen.us_fundamentals import wanted_tags
    fcon = factsdb.connect(tmp_path / "f.sqlite")
    factsdb.save_facts(fcon, 1, sec_facts(), wanted_tags())
    start, today = dt.date(2022, 11, 16), dt.date(2026, 11, 16)
    # stored closes are on today's share basis: 20 then is 40 on the share basis of then (the 2:1 split came later)
    factsdb.save_prices(fcon, "GRW", [("2020-11-13", 15.0), ("2021-11-16", 18.0), ("2022-11-16", 20.0), ("2026-11-16", 30.0)],
                        [("2023-06-01", 2.0)])
    pcon = pricedb.connect(tmp_path / "p.sqlite")
    pricedb.save_bars(pcon, "^GSPC", [(d, c, c, c, c, c, 0) for d, c in (("2020-11-13", 90.0), ("2022-11-16", 100.0), ("2026-11-16", 125.0))])
    entry = {"cik": 1, "ticker": "GRW", "yahoo": "GRW", "name": "Grower Inc", "sector": "Industrials", "industry": "Machinery",
             "indexes": ["S&P 500"], "foreign": False}
    res = backtest.run_us([entry], fcon, loader.load_config(), "^GSPC", years=(4,), today=today, pcon=pcon)
    b = res[0]
    assert b["start"] == start and b["screened"] == 1 and not b["dividends"] and b["ret"] == "price_return"
    r = b["picks"][0]
    assert r["price"] == pytest.approx(40.0)                       # the price then, on the share basis of then
    ttm = (1.2 ** 5 / 4 + 3 * 1.2 ** 6 / 4)                        # Q4 2021 + Q1–Q3 2022; the 2023 quarter not filed yet
    assert r["pe"] == pytest.approx(40.0 / ttm)
    assert r["eps_cagr_5y"] == pytest.approx(0.2) and r["eps_cagr_3y"] == pytest.approx(0.2)   # the 2023 restatement ignored
    assert r["price_return"] == pytest.approx(0.5) and b["index_price"] == pytest.approx(0.25)
    assert b["picks_ret"] == pytest.approx(0.5) and b["all_ret_median"] == pytest.approx(0.5)


def test_prices_as_of_splits_both_ways():
    rows = [("2021-01-04", 10.0), ("2022-11-16", 20.0), ("2026-11-16", 30.0)]
    splits = [("2021-06-01", 4.0), ("2023-06-01", 2.0), ("2024-06-01", 0.5)]   # a split before, and a split and a reverse split after
    px = backtest.prices_as_of(rows, splits, dt.date(2022, 11, 16))
    assert px["price"] == pytest.approx(20.0 * 2.0 * 0.5)            # both later ones undone
    assert px["on"]("2021-01-04") == pytest.approx(10.0)
    assert px["splits_since"]("2020-12-31") == [4.0] and px["split_since"]("2020-12-31") == 4.0   # only those up to the start
    assert px["splits_since"]("2021-12-31") == [] and px["split_since"]("2021-12-31") == 1.0
    assert backtest.prices_as_of(rows, splits, dt.date(2020, 11, 16)) is None   # not listed then


def test_curve_is_equal_weighted_buy_and_hold(tmp_path):
    con = pricedb.connect(tmp_path / "p.sqlite")
    days = [(dt.date(2022, 1, 3) + dt.timedelta(days=i)).isoformat() for i in range(11)]
    pricedb.save_bars(con, "^IDX", [(d, 1, 1, 1, 100.0 + i, 100.0 + i, 0) for i, d in enumerate(days)])
    series = {"A": [(d, 10.0 * (1 + i / 10)) for i, d in enumerate(days)], "B": [(d, 50.0) for d in days]}
    cv = backtest.curve(dt.date(2022, 1, 3), dt.date(2022, 1, 13), ["A"], ["A", "B"], "^IDX",
                        lambda s, since: series[s], con, step=5)
    assert cv["days"] == [days[0], days[5], days[10]]
    assert cv["picks"] == pytest.approx([1.0, 1.5, 2.0]) and cv["all"] == pytest.approx([1.0, 1.25, 1.5])
    assert cv["index"] == pytest.approx([1.0, 1.05, 1.10])


def test_us_backtest_section_is_price_only():
    from valuescreen import html_report
    row = {"ticker": "GRW", "name": "Grower", "pe": 13.0, "last_fy": "Sep 2022", "eps_cagr_5y": 0.2, "eps_cagr_3y": 0.2,
           "expected_return": 0.12, "price_return": 0.5, "total_return": None}
    b = {"start": dt.date(2022, 11, 16), "years": 4.0, "picks": [row], "screened": 1, "best": row, "worst": row,
         "picks_ret": 0.5, "all_ret": 0.5, "all_ret_median": 0.5, "index_price": 0.25, "short_history": 0,
         "skipped": {"not listed then": [], "no SEC figures then": ["X"]}, "dividends": False, "ret": "price_return",
         "rules": "us_growth_screen"}
    html = html_report.backtest_html([b], loader.load_config(), "S&P 500", href=lambda t: None)
    assert "Picks, price only" in html and "with dividends" not in html and 'href="#c-' not in html
    assert "filed on or before" in html and "1 no SEC figures then" in html and "settings panel" not in html
