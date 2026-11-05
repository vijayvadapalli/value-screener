"""The first-pass screen: valuation rules, safety flags and draft files. No network calls."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml

from valuescreen import loader

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("screen_universe", ROOT / "tools" / "screen_universe.py")
su = importlib.util.module_from_spec(spec)
spec.loader.exec_module(su)

CFG = loader.load_config(Path(__file__).parent / "fixtures" / "nov2026" / "config.yaml")
ENTRY = {"ticker": "TCS", "yahoo": "TCS.NS", "name": "Tata Consultancy Services Ltd.", "industry": "Information Technology"}


def raw(**changes):
    """Rupee figures in the shape Yahoo returns them: TCS's last full year."""
    base = {"v": su.SCHEMA, "price": 2495.7, "price_date": "2026-11-05", "currency": "INR", "shares": 3.618e9,
            "period_end": "2026-03-31", "fx": 1.0, "statements_currency": "INR", "trailing_eps": 136.0,
            "net_income": 492.1e9, "da": 55.6e9, "capex": -41.5e9, "ocf": 520.9e9, "cash": 413.7e9, "debt": 112.8e9}
    return {**base, **changes}


def row(entry=ENTRY, **changes):
    kind, value = su.screen_one(entry, raw(**changes), CFG)
    assert kind == "row", value
    return value


def test_valued_with_the_growth_model():
    r = row()
    assert r["zone"] == "WATCH" and r["period"] == "FY26 (Mar)"
    assert 0.05 < r["implied_growth"] < 0.10
    assert r["pe"] == pytest.approx(17.7, abs=0.2)
    assert r["fcf_yield"] == pytest.approx((520.9 - 41.5) / (2495.7 * 3.618), rel=1e-3)
    assert r["flag"] is None


def test_cheap_price_is_buy_and_dear_price_is_sell():
    assert row(price=1500.0)["zone"] == "BUY"
    assert row(price=6000.0)["zone"] == "SELL"


@pytest.mark.parametrize("entry, changes, reason", [
    ({**ENTRY, "industry": "Financial Services"}, {}, "financial company"),
    (ENTRY, {"currency": "USD"}, "not INR"),
    (ENTRY, {"net_income": -1.0e9}, "not positive"),
    (ENTRY, {"net_income": None}, "no net income from Yahoo for the year ended 2026-03-31"),
    (ENTRY, {"cash": None}, "no cash"),
    (ENTRY, {"shares": None}, "no share count"),
    (ENTRY, {"error": "no price from Yahoo"}, "no price from Yahoo"),
])
def test_companies_that_cannot_be_valued_are_skipped_with_a_reason(entry, changes, reason):
    kind, message = su.screen_one(entry, raw(**changes), CFG)
    assert kind == "skip" and reason in message


def test_missing_debt_counts_as_none():
    assert row(debt=None)["zone"] == "WATCH"


@pytest.mark.parametrize("trailing, flagged", [(136.0, False), (100.0, False), (270.0, False), (-9.2, True), (5.0, True), (2000.0, True)])
def test_year_eps_far_from_yahoos_trailing_eps_is_flagged(trailing, flagged):
    assert bool(row(trailing_eps=trailing)["flag"]) is flagged


def test_no_trailing_eps_means_no_flag():
    assert row(trailing_eps=None)["flag"] is None


def test_flagged_companies_are_not_shortlisted():
    cheap, flagged = row(price=1500.0), row(price=1500.0, trailing_eps=-9.2)
    assert cheap["zone"] == "BUY" and flagged["zone"] == "BUY"
    assert su.shortlist([cheap, flagged]) == [cheap]
    assert su.shortlist([row(price=6000.0)]) == []  # SELL
    assert su.shortlist([row(price=3100.0)]) == []  # HOLD


def test_statements_in_usd_are_converted_when_eps_then_agrees():
    usd = raw(statements_currency="USD", currency="INR", trailing_eps=75.1, shares=4.05e9, net_income=3.313e9,
              da=0.6e9, capex=-0.3e9, ocf=4.0e9, cash=3.8e9, debt=1.0e9)
    converted = su.choose_fx(usd, 94.46)
    assert converted["fx"] == 94.46 and converted["net_income"] == pytest.approx(3.313e9 * 94.46)
    assert converted["shares"] == usd["shares"] and converted["price"] == usd["price"]


def test_a_wrong_usd_label_is_not_converted():
    inr = raw(statements_currency="USD", currency="INR", trailing_eps=67.6, shares=2.71e9, net_income=157.8e9)
    kept = su.choose_fx(inr, 94.46)
    assert kept["fx"] == 1.0 and kept["net_income"] == inr["net_income"] and "not converted" in kept["fx_note"]


def test_conversion_is_trusted_when_there_is_no_trailing_eps_to_check_it():
    assert su.choose_fx(raw(trailing_eps=None, statements_currency="USD"), 94.46)["fx"] == 94.46


def test_period_label():
    assert su.period_label("2026-03-31") == "FY26 (Mar)"
    assert su.period_label("2025-12-31") == "FY25 (Dec)"


def test_draft_file_is_a_valid_company_file_that_says_it_is_a_draft():
    draft = yaml.safe_load(su.draft_file(row(), dt.date(2026, 11, 5)))
    company = loader.validate_company(draft)
    assert company["ticker"] == "TCS" and company["yahoo"] == "TCS.NS" and company["model"] == "growth"
    assert company["period"]["label"] == "FY26 (Mar)" and company["period"]["per_year"] == 1
    assert company["earnings"]["net_income"] == pytest.approx(492100.0)  # millions of rupees
    assert company["shares_m"] == pytest.approx(3618.0)
    assert any("DRAFT" in x for x in company["assumptions"]) and "unverified" in company["sources"][0]


def test_draft_file_round_trips_through_the_company_file_format():
    text = su.draft_file(row(), dt.date(2026, 11, 5))
    assert yaml.safe_dump(yaml.safe_load(text), sort_keys=False, allow_unicode=True, width=140) == text


def test_promote_writes_new_files_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(su, "COMPANIES", tmp_path)
    existing = tmp_path / "itc.yaml"
    existing.write_text("ticker: ITC\n# hand-checked\n")
    itc = row({**ENTRY, "ticker": "ITC", "yahoo": "ITC.NS", "name": "ITC Ltd."}, price=100.0)
    written, kept = su.promote([row(), itc], dt.date(2026, 11, 5))
    assert written == ["TCS"] and kept == ["ITC"]
    assert existing.read_text() == "ticker: ITC\n# hand-checked\n"
    assert loader.validate_company(yaml.safe_load((tmp_path / "tcs.yaml").read_text()))["ticker"] == "TCS"


def test_old_cache_entries_are_fetched_again(tmp_path, monkeypatch):
    monkeypatch.setattr(su, "OUT", tmp_path)
    calls = []
    monkeypatch.setattr(su, "fetch", lambda symbol: calls.append(symbol) or raw())
    entries = [ENTRY, {**ENTRY, "ticker": "ITC", "yahoo": "ITC.NS"}]
    su.load_raw(entries, "t", refresh=False)
    assert sorted(calls) == ["ITC.NS", "TCS.NS"]
    calls.clear()
    su.load_raw(entries, "t", refresh=False)
    assert calls == []  # today's cache is used
    su.load_raw(entries, "t", refresh=True)
    assert len(calls) == 2


def test_update_results_knows_how_to_replace_a_draft():
    ur_spec = importlib.util.spec_from_file_location("update_results", ROOT / "tools" / "update_results.py")
    ur = importlib.util.module_from_spec(ur_spec)
    ur_spec.loader.exec_module(ur)
    assigned = yaml.safe_load(su.draft_file(row(), dt.date(2026, 11, 5)))["assumptions"]
    assert any(x.startswith("DRAFT") for x in assigned) and "starts with DRAFT" in ur.CONVENTIONS


def test_a_flagged_draft_carries_its_warning_and_a_conversion_note():
    flagged = row(price=1500.0, trailing_eps=-9.2)
    draft = yaml.safe_load(su.draft_file(flagged, dt.date(2026, 11, 5)))
    assert draft["assumptions"][0].startswith("CHECK before relying on it") and "-9.2" in draft["assumptions"][0]
    assert any(x.startswith("DRAFT") for x in draft["assumptions"])
    loader.validate_company(draft)
    usd = row(statements_currency="USD", fx=94.46, trailing_eps=136.0)
    assert yaml.safe_load(su.draft_file(usd, dt.date(2026, 11, 5)))["notes"] == ["statements converted from USD at 94.46"]


def test_promote_all_covers_every_valued_company_including_flagged_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(su, "COMPANIES", tmp_path)
    rows = [row(price=1500.0), row({**ENTRY, "ticker": "ITC", "yahoo": "ITC.NS", "name": "ITC Ltd."}, price=6000.0),
            row({**ENTRY, "ticker": "TMPV", "yahoo": "TMPV.NS", "name": "Tata Motors PV"}, trailing_eps=-9.2)]
    assert [r["zone"] for r in rows] == ["BUY", "SELL", "WATCH"]
    written, _ = su.promote(rows, dt.date(2026, 11, 5))
    assert written == ["TCS", "ITC", "TMPV"] and len(loader.load_companies(tmp_path)) == 3
