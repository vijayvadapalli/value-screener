"""Chart analytics (chart_levels), chart data (price_chart) and the chart in the HTML report. No network."""
import datetime as dt
import json
import math

import pytest

from valuescreen import chart_levels as L
from valuescreen import html_report, pricedb
from valuescreen import price_chart as PC


def make_bars(closes, start=dt.date(2025, 1, 1)):
    out, day = [], start
    for c in closes:
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        out.append({"date": day.isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "adj_close": c, "volume": 1000})
        day += dt.timedelta(days=1)
    return out


def test_sma_and_rsi():
    assert L.sma_series([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    up = L.rsi_series([float(i) for i in range(30)])
    assert up[13] is None and up[14] == 100.0
    down = L.rsi_series([float(30 - i) for i in range(30)])
    assert down[-1] == pytest.approx(0.0)
    zigzag = L.rsi_series([10 + (i % 2) for i in range(40)])
    assert 40 < zigzag[-1] < 60


def test_pivots_and_levels():
    # a wave between ~90 and ~110, ending at 100: support near 90, resistance near 110
    closes = [100 + 10 * math.sin(i / 8) for i in range(300)]
    bars = make_bars(closes)
    piv = L.pivots(bars, 5)
    assert any(s == "high" for _, s, _ in piv) and any(s == "low" for _, s, _ in piv)
    lv = L.levels(bars)
    assert lv["support"] and lv["resistance"]
    assert all(x["price"] < bars[-1]["close"] for x in lv["support"])
    assert all(x["price"] > bars[-1]["close"] for x in lv["resistance"])
    assert lv["resistance"][0]["price"] == pytest.approx(111, rel=0.02) and lv["resistance"][0]["touches"] >= 2
    assert L.levels(bars[:5]) == {"support": [], "resistance": []}


def test_trend_lines_rising_support_and_falling_resistance():
    rising = make_bars([50 + i * 0.1 + 4 * math.sin(i / 6) for i in range(260)])
    kinds = {t["kind"]: t for t in L.trend_lines(rising)}
    assert "support" in kinds and kinds["support"]["to"][1] > kinds["support"]["from"][1] and kinds["support"]["touches"] >= 3
    falling = make_bars([90 - i * 0.1 + 4 * math.sin(i / 6) for i in range(260)])
    kinds = {t["kind"]: t for t in L.trend_lines(falling)}
    assert "resistance" in kinds and kinds["resistance"]["to"][1] < kinds["resistance"]["from"][1]
    assert L.trend_lines(make_bars([50.0] * 10)) == []          # too short
    noise = make_bars([50 + (7 if i % 13 == 0 else 0) - (7 if i % 17 == 0 else 0) for i in range(260)])
    assert all(t["touches"] >= 3 for t in L.trend_lines(noise))  # never a two-point line


def test_value_lines_by_model():
    tier_a = {"model": "producer", "tier": "A", "mult_lo": 12, "mult_hi": 15, "v_low": 100.0, "v_high": 125.0,
              "buy_level": 125.0, "add_level": 100.0, "call_level": 200.0}
    lines = PC.value_lines(tier_a)
    assert [(x["price"], x["solid"]) for x in lines] == [(125.0, True), (100.0, True), (200.0, True)]
    assert lines[0]["label"] == "15x value · start" and lines[1]["label"] == "12x value · add"
    assert lines[0]["color"] == PC.LIGHT_GREEN and lines[1]["color"] == PC.DARK_GREEN
    growth = PC.value_lines({"model": "growth", "v0": 50.0, "buy_level": 60.0, "call_level": -5.0})
    assert [x["label"] for x in growth] == ["Buy (≤ 5% growth)", "Value, no growth"]          # a non-positive level is left out
    assert PC.value_lines({"model": "liquid"}) == []


@pytest.fixture
def con(tmp_path):
    c = pricedb.connect(tmp_path / "p.sqlite")
    bars = make_bars([500 + 40 * math.sin(i / 10) for i in range(700)], start=dt.date(2024, 1, 1))
    pricedb.save_bars(c, "YCA.L", [(b["date"], b["open"], b["high"], b["low"], b["close"], b["close"], b["volume"]) for b in bars])
    pricedb.save_actions(c, "YCA.L", [(bars[-30]["date"], "dividend", 10.0)])
    pricedb.save_symbol(c, "YCA.L", "GBp", "core")
    return c


def test_payload_converts_pence_and_keeps_value_lines(con):
    r = {"model": "physical", "nav": 6.0, "buy_level": 5.1, "call_level": 6.6, "price_ccy": "GBP", "signal": "green", "action": "Buy"}
    c = {"period": {"reported": dt.date(2026, 6, 30), "label": "Q1"}}
    p = PC.payload(con, "YCA.L", r, c)
    assert p["currency"] == "GBP" and p["same_currency"]
    assert 4 < p["D"][-1][4] < 6                                    # 500p-ish → £5-ish
    assert [x["label"] for x in p["values"]] == ["Buy", "NAV", "Sell zone"]
    assert {m["kind"] for m in p["markers"]} >= {"D"}
    assert next(m for m in p["markers"] if m["kind"] == "D")["text"] == "Dividend 0.1"
    assert len(p["W"]) < len(p["D"]) and len(p["M"]) < len(p["W"])
    usd = PC.payload(con, "YCA.L", dict(r, price_ccy="USD"), c)
    assert not usd["same_currency"] and usd["values"] == []         # never draw a value in the wrong currency
    assert "52-week" in PC.caption(p)
    assert PC.payload(con, "NONE", r, c) is None


def test_chart_block_and_static_png(con, tmp_path):
    r = {"model": "physical", "nav": 6.0, "buy_level": 5.1, "call_level": 6.6, "price_ccy": "GBP", "signal": "green", "action": "Buy"}
    p = PC.payload(con, "YCA.L", r, {"period": {}})
    html = html_report.chart_block("YCA", p)
    assert 'data-pc="pcd-YCA"' in html and 'data-rg="10Y"' in html
    data = html.split('<script type="application/json" id="pcd-YCA">')[1].split("</script>")[0]
    assert json.loads(data.replace("<\\/", "</"))["symbol"] == "YCA.L"
    assert html_report.chart_block("YCA", None) == ""
    assert PC.static_png(p, tmp_path / "c.png").exists()
    assert PC.static_png(None, tmp_path / "d.png") is None
