"""Model portfolios: eligibility, momentum entry, sizing within sleeves, ETF fill and the two profiles. No network calls."""
import datetime as dt

import pytest

from valuescreen import model_portfolio as mp


def stock(key, sleeve, value=0.8, quality=0.8, vol=0.30, full=True, reasons=()):
    return {"key": key, "ticker": key, "yahoo": key, "name": key, "source": "US screen", "sleeve": sleeve, "signal": "green",
            "action": "Cheap", "price": 10.0, "ccy": "USD", "buy_level": None, "flags": [], "value_text": "v", "quality_text": "q",
            "value_score": value, "quality_score": quality, "momentum_score": 0.7 if full else 0.2, "vol": vol,
            "entry": "full" if full else "third", "exit_rule": "x", "reasons": list(reasons)}


def etfs():
    out = []
    for s in mp.ETFS:
        c = mp.etf_candidate(s)
        c.update(momentum_score=0.5, vol=0.2, entry="full")
        out.append(c)
    return out


def universe():
    return ([stock(f"US{i}", "us", vol=0.2 + i / 50) for i in range(12)] + [stock(f"M{i}", "mining", vol=0.5) for i in range(3)]
            + [stock("E0", "energy", full=False), stock("BAD", "us", value=1.0, quality=1.0, reasons=["grade D"])] + etfs())


@pytest.mark.parametrize("profile", list(mp.PROFILES))
def test_weights_add_up_and_respect_the_cap(profile):
    r = mp.build(universe(), profile)
    assert sum(c["weight"] for c in r["holdings"]) == pytest.approx(1.0)
    cap = mp.PROFILES[profile]["max_weight"]
    assert all(c["target_weight"] <= cap + 1e-9 for c in r["holdings"] if not c.get("etf"))
    assert "BAD" not in {c["key"] for c in r["holdings"]}   # excluded however good its scores


def test_thirds_wait_in_tbills():
    r = mp.build(universe(), "balanced")
    e0 = next(c for c in r["holdings"] if c["key"] == "E0")
    assert e0["weight"] == pytest.approx(e0["target_weight"] / 3)
    sgov = next(c for c in r["holdings"] if c["key"] == "SGOV")
    assert sgov["weight"] == pytest.approx(mp.PROFILES["balanced"]["defensive"]["SGOV"] + r["waiting"])
    assert r["waiting"] == pytest.approx(e0["target_weight"] * 2 / 3)


def test_short_sleeves_are_filled_by_their_etf():
    r = mp.build(universe(), "resources")
    by = {c["key"]: c for c in r["holdings"]}
    assert "GDX" in by and "URNM" in by and "XLE" in by   # 3 of 8 miners, no uranium, 1 of 4 energy
    assert by["URNM"]["weight"] == pytest.approx(0.10)
    mining = sum(c["target_weight"] for c in r["holdings"] if c["sleeve"] == "mining")
    assert mining == pytest.approx(0.40)


def test_lower_volatility_gets_more_weight():
    r = mp.build(universe(), "balanced")
    us = sorted((c for c in r["holdings"] if c["sleeve"] == "us" and not c.get("etf")), key=lambda c: c["vol"])
    assert us[0]["target_weight"] >= us[-1]["target_weight"]


def test_profiles_rank_differently():
    cands = [stock("VAL", "us", value=1.0, quality=0.0), stock("QUAL", "us", value=0.5, quality=1.0)] + etfs()
    top = lambda p: next(c["key"] for c in mp.build(cands, p)["holdings"] if c["sleeve"] == "us")  # noqa: E731
    assert top("resources") == "VAL"
    assert top("balanced") == "QUAL"


def test_candidates_are_not_changed_by_build():
    cands = universe()
    mp.build(cands, "balanced")
    assert all("score" not in c for c in cands)


def test_momentum_rule():
    up = [100 + i * 0.1 for i in range(300)]
    c = {}
    mp.momentum(c, mp.price_stats(up))
    assert c["entry"] == "full"
    down = [130 - i * 0.1 for i in range(300)]
    mp.momentum(c, mp.price_stats(down))
    assert c["entry"] == "third"
    mp.momentum(c, mp.price_stats(down[:50]))   # too little history
    assert c["entry"] == "third" and c["momentum_text"] == "no price history"


def test_us_screen_rows_need_cash_and_low_debt():
    row = {"ticker": "X", "yahoo": "X", "name": "X", "sector": "Utilities", "industry": "", "signal": "green", "action": "Cheap",
           "price": 10.0, "implied_growth": -0.1, "grade": "A", "flags": [], "cik": 1, "nc": -8.0, "fcf_yield": -0.05}
    reasons = mp.from_us_screen(row)["reasons"]
    assert "net debt above half the market value" in reasons and "negative free cash flow" in reasons
    ok = mp.from_us_screen(dict(row, nc=1.0, fcf_yield=0.06))
    assert ok["reasons"] == [] and ok["sleeve"] == "us"
    assert mp.from_us_screen(dict(row, sector="Energy", nc=1.0, fcf_yield=0.06))["sleeve"] == "energy"


def test_merge_prefers_full_files():
    a = dict(stock("NEM", "mining"), source="core list")
    b = dict(stock("NEM", "mining"), source="US screen", cik=5)
    c = dict(stock("NEMX", "mining"), source="US screen", cik=5)   # another share class of the same company
    out = mp.merge([a], [b, c])
    assert [x["source"] for x in out] == ["core list"]   # b dropped by symbol; c, sharing b's CIK, by CIK


def test_report_writes(tmp_path):
    r = mp.build(universe(), "resources")
    path = mp.report(r, {"vol": 0.1, "max_fall": -0.08, "return_1y": 0.05, "covered": 1.0}, tmp_path / "m.html",
                     dt.date(2026, 11, 13), ["a note"])
    text = path.read_text()
    assert "resources, value first" in text and "Start a third" in text and "60% value" in text
