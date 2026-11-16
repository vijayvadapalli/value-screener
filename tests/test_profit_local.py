"""Profit vs price from the company file's Screener EPS and the stored prices (growth_data.local_record)."""
import datetime as dt

from valuescreen import growth_data
from valuescreen import profit_vs_price as pvp

D = dt.date


def company(**v2):
    base = {"years": ["Mar 2022", "Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026"],
            "eps_annual": [5.0, 8.0, 10.0, 20.0, 30.0], "eps_quarters": [7.0, 8.0, 9.0, 10.0], "roe_5y": 0.2}
    return {"ticker": "X", "yahoo": "X.NS", "currency": "INR", "name": "X Ltd", "period": {"end": "2026-09-30"},
            "price": {"value": 300.0, "date": "2026-11-16"}, "v2": {**base, **v2}}


CLOSES = [(D(2023, 3, 31), 100.0), (D(2024, 3, 28), 150.0), (D(2025, 11, 14), 250.0), (D(2026, 11, 16), 300.0)]


def test_ttm_against_the_year_about_three_years_back():
    r = growth_data.local_record(company(), CLOSES)
    assert r["eps_now"] == 34.0 and r["latest_label"] == "TTM Sep 26"
    assert r["base_label"] == "FY24" and r["eps_then"] == 10.0 and r["price_then"] == 150.0
    assert round(r["years"], 1) == 2.5
    assert round(r["price_change_1y"], 2) == 0.2
    e = pvp.evaluate(r)
    assert e["grade"] == "A"   # EPS 10 → 34 while the price only doubled


def test_loss_base_year_starts_from_the_next_profitable_year():
    r = growth_data.local_record(company(eps_annual=[5.0, 8.0, -2.0, 20.0, 30.0]), CLOSES)
    assert r["base_label"] == "FY25" and "loss" in r["note"]


def test_odd_labels_are_skipped_and_no_prices_is_not_comparable():
    r = growth_data.local_record(company(years=["Mar 2022", "Mar 202315m", "Mar 2024", "Mar 2025", "Mar 2026"]), CLOSES)
    assert r["base_label"] == "FY24"
    r = growth_data.local_record(company(), [])
    assert pvp.evaluate(r)["grade"] == "n/m" and r["nm_reason"] == "no price history"


def test_no_yearly_eps_gives_no_record():
    assert growth_data.local_record(company(eps_annual=[]), CLOSES) is None
