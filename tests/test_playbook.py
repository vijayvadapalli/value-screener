"""The Valuation Playbook rules: India's 12% rate, tiers, signals and flags, Nifty v2, the lease and liquid-asset
models, last-12-month earnings, the gold stress test, technicals, run history and the PDF. No network calls."""
import copy
import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml

from valuescreen import history, loader, pdf, screener, technicals, v2
from valuescreen.engine import run
from valuescreen.models import dcf_factor

HERE = Path(__file__).parent
ROOT = HERE.parent
FIXTURE = HERE / "fixtures" / "nov2026"
BASE_CFG = loader.load_config(FIXTURE / "config.yaml")
LIVE_CFG = loader.load_config(ROOT / "config.yaml")
COS = loader.load_companies(FIXTURE / "companies")
EXTRA = loader.load_companies(HERE / "fixtures" / "playbook")


def cfg_with(**changes):
    """The 4 Nov snapshot config plus the playbook settings from the live config.yaml."""
    cfg = copy.deepcopy(BASE_CFG)
    for key in ("tiers", "nifty_v2", "market_cap_shades_usd_bn", "stress_gold", "price_stale_days"):
        cfg[key] = copy.deepcopy(LIVE_CFG[key])
    cfg["growth_dcf"]["discount_rate_by_currency"] = {"INR": 0.12}
    cfg["zones"].update(growth_buy_tier_a=0.10, min_cash_conversion=0.70)
    cfg["stale_days"].update(leases=100, liquid=100)
    cfg["fx_usd_per_unit"]["INR"] = LIVE_CFG["fx_usd_per_unit"]["INR"]
    cfg.update(changes)
    return cfg


def indian(eps_quarters, kind=None, price=250.0, **v2_extra):
    c = {"ticker": "TEST", "name": "Test Ltd", "sector": "Fast Moving Consumer Goods", "model": "growth", "currency": "INR",
         "period": {"label": "TTM", "end": "2026-09-30", "per_year": 4},
         "price": {"value": price, "currency": "INR", "date": "2026-11-04"}, "shares_m": 1000.0,
         "balance": {"net_cash": 0.0}, "sources": ["test"],
         "v2": {"eps_quarters": eps_quarters, **v2_extra}}
    if kind:
        c["v2"]["kind"] = kind
    return loader.validate_company(c)


# ------------------------------------------------------------------------------------------------- discount rates
def test_no_growth_multiple_is_13_1_for_the_us_and_12_1_for_india():
    assert dcf_factor(0.0, BASE_CFG) == pytest.approx(13.105, abs=0.01)
    assert dcf_factor(0.0, BASE_CFG, rate=0.12) == pytest.approx(12.116, abs=0.01)


def test_indian_companies_are_discounted_at_12_percent():
    r = run({"TEST": indian([4, 4, 4, 4, 4, 4, 4, 4])}, ["TEST"], cfg_with())["TEST"]
    assert r["discount_rate"] == 0.12
    assert r["v0"] == pytest.approx(16 * 12.116, rel=1e-3)


# ------------------------------------------------------------------------------------------------- tiers
@pytest.mark.parametrize("where, zone, signal", [(0.95, "BUY (add)", "green"), (1.10, "BUY (start)", "green"),
                                                 (1.5, "HOLD", "blue"), (2.5, "SELL", "red")])
def test_tier_a_starts_at_15x_and_adds_at_12x(where, zone, signal):
    """NEM's 4 Nov values are about 96 (12x), 120 (15x) and 200 (25x); `where` × the 12x value sets the price."""
    cos = copy.deepcopy(COS)
    v12 = run(cos, ["NEM"], cfg_with())["NEM"]["v_low"]
    cos["NEM"]["price"]["value"] = where * v12
    r = run(cos, ["NEM"], cfg_with())["NEM"]
    assert r["tier"] == "A" and r["zone"] == zone and r["signal"] == signal
    assert r["buy_level"] == pytest.approx(r["v_high"]) and r["add_level"] == pytest.approx(r["v_low"])


def test_tier_b_keeps_the_20_percent_rule():
    r = run(COS, ["CDE"], cfg_with(as_of=dt.date(2026, 7, 1)))["CDE"]
    assert r["tier"] == "B" and r["buy_level"] == pytest.approx(0.8 * r["v_low"])


def test_without_tiers_in_config_nothing_changes():
    assert run(COS, ["NEM"], BASE_CFG)["NEM"]["tier"] is None


# ------------------------------------------------------------------------------------------------- signals and flags
def test_stale_buy_is_blue_and_flagged():
    cos = copy.deepcopy(COS)
    cos["ABRA"]["period"]["end"] = dt.date(2025, 1, 1)
    r = run(cos, ["ABRA"], cfg_with())["ABRA"]
    assert r["zone"].startswith("STALE") and r["signal"] == "blue" and "STALE" in r["flags"]


def test_old_and_undated_prices_are_flagged():
    cos = copy.deepcopy(COS)
    cfg = cfg_with(as_of=dt.date(2026, 11, 20))
    r = run(cos, ["AEM"], cfg)["AEM"]
    assert "price 17 days old" in r["flags"]   # priced 3 Nov
    cos["AEM"]["price"]["undated"] = True
    assert "undated price" in run(cos, ["AEM"], cfg)["AEM"]["flags"]


def test_cheap_cyclical_is_capped_at_blue():
    c = indian([4] * 8, kind="cyclical", price=20.0, eps_annual=[16, 16, 16, 16, 16])
    r = run({"TEST": c}, ["TEST"], cfg_with())["TEST"]
    assert r["zone"].startswith("BUY") and r["signal"] == "blue" and "cyclical" in r["signal_caps"]


def test_low_cash_conversion_caps_the_signal_at_blue():
    c = indian([4] * 8, price=20.0, cfo_annual=[5, 5, 5, 5, 5], profit_annual=[10, 10, 10, 10, 10])
    r = run({"TEST": c}, ["TEST"], cfg_with())["TEST"]
    assert r["cash_conversion"] == pytest.approx(0.5)
    assert r["signal"] == "blue" and any("cash conversion 50%" in f for f in r["flags"])


def test_growth_tier_a_is_green_up_to_10_percent():
    cos = copy.deepcopy(COS)
    cfg = cfg_with(tiers={"A": ["MSFT"]})
    r = run(cos, ["MSFT"], cfg)["MSFT"]
    price = r["value_fn"](0.08)
    cos["MSFT"]["price"]["value"] = price
    r = run(cos, ["MSFT"], cfg)["MSFT"]
    assert r["implied_growth"] == pytest.approx(0.08, abs=1e-4) and r["signal"] == "green"


# ------------------------------------------------------------------------------------------------- Nifty v2
def test_one_off_quarter_is_replaced_by_its_neighbours_average():
    cleaned, changes = v2.clean_quarters([4, 4, 4, 4, 4, 4, 15, 4])
    assert cleaned[6] == 4 and changes == [(6, 15.0, 4.0)]


def test_a_rising_trend_is_not_a_one_off():
    q = [2, 3, 4, 5, 6, 7, 8, 9]
    assert v2.clean_quarters(q) == ([float(x) for x in q], [])


def test_cyclical_and_financial_earnings():
    cfg = cfg_with()
    cyc = v2.base_eps(indian([5] * 8, kind="cyclical", eps_annual=[10, 10, 10, 10, 10]), cfg)
    assert cyc["ttm"] == 20 and cyc["eps"] == 15
    fin = v2.base_eps(indian([5] * 8, kind="financial", book_value_ps=100.0, roe_5y=0.15), cfg)
    assert fin["eps"] == pytest.approx((20 + 15) / 2)


def test_financials_get_no_net_cash_and_a_price_to_book_check():
    c = indian([5] * 8, kind="financial", book_value_ps=100.0, roe_5y=0.15)
    c["balance"] = {"net_cash": 50000.0}
    r = run({"TEST": c}, ["TEST"], cfg_with())["TEST"]
    assert r["nc"] == 0 and r["pb"] == pytest.approx(2.5) and r["fair_pb"] == pytest.approx(0.15 * 12.116, rel=1e-3)


def test_kind_and_flags_come_from_the_config_lists():
    cfg = cfg_with()
    c = indian([5] * 8)
    c.update(ticker="LT", sector="Metals & Mining")
    assert v2.kind_of(c, cfg) == "cyclical" and v2.flags_of(c, cfg) == ["conglomerate"]


# ------------------------------------------------------------------------------------------------- new models
def test_lease_model_matches_the_11_nov_report():
    cfg = cfg_with(as_of=dt.date(2026, 11, 10))
    r = run(EXTRA, ["HUT"], cfg)["HUT"]
    assert r["v_low"] == pytest.approx(36.69, rel=0.005)
    assert r["v_base"] == pytest.approx(52.10, rel=0.005)
    assert r["v_high"] == pytest.approx(70.10, rel=0.005)
    assert r["zone"] == "HOLD" and r["buy_level"] == pytest.approx(0.8 * r["v_low"])


def test_liquid_assets_as_a_share_of_market_value():
    r = run(EXTRA, ["UEC"], cfg_with())["UEC"]
    expected = (495 + 149 + 1.256 * BASE_CFG["spot"]["uranium"]) / (8.83 * 515.3)
    assert r["liquid_ratio"] == pytest.approx(expected, rel=1e-6)
    assert r["zone"].startswith("NOT VALUED") and r["signal"] == "red"


def test_last_twelve_months_add_up_four_quarters():
    c = copy.deepcopy(COS["AEM"])
    q = {"adj_net_income": 1000.0, "da": 400.0, "sustaining_capex": 300.0}
    c["ltm"] = [dict(q, metals=[{"metal": "gold", "units": 0.8, "realised": p}]) for p in (4000, 4100, 4200, 4300)]
    loader.apply_ltm(c)
    assert c["earnings"]["adj_net_income"] == 4000 and c["period"]["per_year"] == 1
    assert c["metals"] == [{"metal": "gold", "units": pytest.approx(3.2), "realised": pytest.approx(4150)}]


def test_gold_stress_values():
    r = run(COS, ["AEM"], cfg_with())["AEM"]
    gold = next(t for t in r["terms"] if t["metal"] == "gold")
    g, v12, _ = r["stress"][0]
    assert g == 3000 and v12 == pytest.approx((r["oe"] + gold["sens"] * (3000 - gold["spot"])) * 12 + r["nc"])


# ------------------------------------------------------------------------------------------------- technicals, history
def test_technical_indicators():
    up = [float(i) for i in range(1, 260)]
    assert technicals.sma(up, 200) == pytest.approx(sum(up[-200:]) / 200)
    assert technicals.rsi(up) == 100.0
    assert technicals.macd(up)[0] > 0
    read = technicals.read(up[::-1])
    assert read["below_200"] and "buy in thirds" in read["note"]


def test_previous_run_is_the_latest_earlier_date(tmp_path):
    runs = tmp_path / "runs.json"
    history.save(runs, dt.date(2026, 11, 1), {"AEM": {"implied_growth": None, "margin_of_safety": -0.2, "zone": "HOLD"}})
    history.save(runs, dt.date(2026, 11, 4), {"AEM": {"margin_of_safety": -0.3}})
    prev = history.previous(runs, dt.date(2026, 11, 4))
    assert prev["_date"] == "2026-11-01" and prev["AEM"]["margin_of_safety"] == -0.2


# ------------------------------------------------------------------------------------------------- reports
def test_pdf_has_a_summary_and_a_bookmarked_section_per_company(tmp_path):
    cfg = cfg_with()
    cos = {**copy.deepcopy(COS), **copy.deepcopy(EXTRA),
           "TEST": indian([4, 4, 4, 4, 4, 4, 15, 4], kind="cyclical", eps_annual=[10, 12, 14, 15, 16],
                          cfo_annual=[9, 10, 12, 14, 15], profit_annual=[10, 12, 14, 15, 16], years=["2022", "2023", "2024", "2025", "2026"])}
    tickers = ["ABRA", "AEM", "CCJ", "HUT", "MSFT", "TEST", "UEC", "YCA"]
    res = run(cos, tickers, cfg)
    out = pdf.build(res, cos, cfg, tmp_path / "r.pdf", "Test")
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and data.count(b"/Title") >= len(tickers)
    assert pdf.file_name("portfolio", dt.date(2026, 11, 12)) == "Portfolio_Value_vs_Price_12Nov2026.pdf"


def test_screener_page_parsing():
    spec = importlib.util.spec_from_file_location("fetch_screener", ROOT / "tools" / "fetch_screener.py")
    fs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fs)
    quarters = "".join(f"<th>{m} {y}</th>" for y in (2024, 2025) for m in ("Mar", "Jun", "Sep", "Dec"))
    years = "".join(f"<th>Mar {y}</th>" for y in range(2020, 2026)) + "<th>TTM</th>"
    html = f"""<div id="top-ratios"><li>Market Cap ₹ 1,000 Cr.</li><li>Current Price ₹ 100</li><li>Book Value ₹ 50.0</li></div>
    <section id="quarters"><table class="data-table"><thead><tr><th></th>{quarters}</tr></thead><tbody>
      <tr><td>EPS in Rs</td>{''.join(f'<td>{x}</td>' for x in [1, 1, 1, 1, 2, 2, 2, 2])}</tr></tbody></table></section>
    <section id="profit-loss"><table class="data-table"><thead><tr><th></th>{years}</tr></thead><tbody>
      <tr><td>Net Profit +</td>{''.join(f'<td>{x}</td>' for x in [10, 11, 12, 13, 14, 15, 16])}</tr>
      <tr><td>EPS in Rs</td>{''.join(f'<td>{x}</td>' for x in [1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6])}</tr></tbody></table></section>
    <section id="cash-flow"><table class="data-table"><thead><tr><th></th>{years.replace('<th>TTM</th>', '')}</tr></thead><tbody>
      <tr><td>Cash from Operating Activity +</td>{''.join(f'<td>{x}</td>' for x in [9, 10, 11, 12, 13, 14])}</tr></tbody></table></section>
    <table class="ranges-table"><tr><th>Return on Equity</th></tr><tr><td>5 Years:</td><td>18%</td></tr></table>"""
    d = screener.parse_v2(html)
    assert d["price"] == 100 and d["book_value_ps"] == 50 and d["roe_5y"] == pytest.approx(0.18)
    assert d["eps_quarters"][-4:] == [2, 2, 2, 2] and d["eps_annual"][-1] == 1.5 and d["cfo_annual"][-1] == 14
    entry = {"ticker": "TEST", "yahoo": "TEST.NS", "name": "Test Ltd", "industry": "Power"}
    c = fs.update_file(None, entry, d, dt.date(2026, 11, 12))
    assert c["period"]["end"] == "2025-12-31" and c["shares_m"] == pytest.approx(100.0)
    loader.validate_company(yaml.safe_load(yaml.safe_dump(c)))


def test_cash_conversion_is_not_used_for_financials():
    c = indian([5] * 8, kind="financial", book_value_ps=100.0, roe_5y=0.15, cfo_annual=[-5] * 5, profit_annual=[10] * 5)
    assert v2.base_eps(c, cfg_with())["cash_conversion"] is None


def test_as_of_today_means_the_current_date(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text((FIXTURE / "config.yaml").read_text().replace("as_of: 2026-11-04", "as_of: today"))
    assert loader.load_config(p)["as_of"] == dt.date.today()


def test_profit_vs_price_grades():
    from valuescreen import profit_vs_price as pvp
    assert [pvp.grade(x) for x in (-0.3, -0.1, 0.2, 0.5, None)] == ["A", "B", "C", "D", "n/m"]
    r = pvp.evaluate({"source": "yahoo", "years": 3.0, "eps_then": 1.0, "eps_now": 1.331, "price_then": 10.0, "price": 13.31})
    assert r["profit_growth"] == pytest.approx(0.10) and r["pe_change"] == pytest.approx(0.0, abs=1e-9) and r["grade"] == "B"
    loss = pvp.evaluate({"source": "yahoo", "years": 3.0, "eps_then": -1.0, "eps_now": 2.0, "price_then": 10.0, "price": 20.0})
    assert loss["grade"] == "n/m"
    nav = pvp.evaluate({"source": "yahoo", "years": 3.0, "eps_then": 1.0, "eps_now": 2.0, "price_then": 10.0, "price": 11.0,
                        "value": {"model": "physical"}})
    assert nav["grade"] == "n/m" and "NAV" in nav["nm_reason"]


def test_combined_html_links_every_company(tmp_path):
    from valuescreen import html_report
    from valuescreen import profit_vs_price as pvp
    cfg = cfg_with()
    cos = {**copy.deepcopy(COS), **copy.deepcopy(EXTRA)}
    tickers = ["AEM", "HUT", "MSFT", "UEC", "YCA"]
    res = run(cos, tickers, cfg)
    raw = {"MSFT": {"source": "yahoo", "years": 3.0, "eps_then": 9.0, "eps_now": 14.0, "price_then": 330.0, "price": 555.8,
                    "currency": "USD", "report_ccy": "USD", "price_date": "2026-11-04", "base_label": "FY23", "latest_label": "TTM Sep 26"}}
    rows = pvp.rows([{"ticker": t} for t in tickers], raw, res, cos)
    out = html_report.build(res, cos, cfg, rows, tmp_path / "r.html", "Test")
    page = out.read_text()
    for t in tickers:
        assert f'href="#c-{t}"' in page and f'id="c-{t}"' in page
    assert 'class="c grade gB"' in page or 'class="c grade gC"' in page   # MSFT graded from the figures above
    assert "data:image/png;base64," in page
