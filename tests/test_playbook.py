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


def test_a_history_break_drops_the_5_year_average():
    """A demerger (TMPV): the old years belong to another company or hold the one-off gain, so only the 12 months count."""
    cfg = cfg_with()
    c = indian([15, 20, 10, 200, -9, 15, 2, -15], kind="cyclical", eps_annual=[-34, 7, 94, 76, 224],
               history_not_comparable="demerger")
    w = v2.base_eps(c, cfg)
    assert w["eps"] == pytest.approx(-7) and w["eps_5y_avg"] is None and "demerger" in w["how"]
    r = run({"TEST": c}, ["TEST"], cfg)["TEST"]
    assert r["signal"] == "red" and r["implied_growth"] is None


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
    assert pdf.file_name("core", dt.date(2026, 11, 12)) == "Core_Value_vs_Price_12Nov2026.pdf"


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
    c["v2"].update(kind="cyclical", history_not_comparable="demerger")
    again = fs.update_file(c, entry, d, dt.date(2026, 11, 13))
    assert again["v2"]["kind"] == "cyclical" and again["v2"]["history_not_comparable"] == "demerger"


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
    demerged = pvp.evaluate({"source": "screener", "profit_growth_3y": 2.32, "price_growth_3y": 0.05, "not_comparable": "demerger"})
    assert demerged["grade"] == "n/m" and "demerger" in demerged["nm_reason"] and demerged["price_growth"] == 0.05


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


# ------------------------------------------------------------------------------------------------- miners screen
def test_etf_tickers_become_yahoo_symbols():
    from valuescreen import etf_holdings as eh
    assert eh.split_ticker("NST AU") == ("NST", "AU") and eh.split_ticker("NEM") == ("NEM", "US")
    assert eh.yahoo_symbol("NST", "AU") == "NST.AX" and eh.yahoo_symbol("APM", "CN") == "APM.TO"
    assert eh.yahoo_symbol("1164", "HK") == "1164.HK" and eh.yahoo_symbol("X", "ZZ") is None
    assert eh.name_key("Barrick Mining Corp") == eh.name_key("BARRICK MINING CORP.")


def _miner_raw(**changes):
    raw = {"name": "Test Gold", "currency": "CAD", "report_ccy": "USD", "fx": 1.4, "usd": 0.7, "price": 20.0,
           "price_date": "2026-11-12", "shares": 100e6, "sales_now": 900e6, "profit_now": 150e6, "ocf_ttm": 300e6,
           "capex_ttm": -100e6, "ebitda": 400e6, "book_value_ps": 8.0, "cash": 200e6, "debt": 100e6, "ttm_label": "TTM Sep 26",
           "years": 3.0, "eps_then": 0.5, "eps_now": 1.5, "price_then": 10.0, "price_change_1y": 0.4}
    return {**raw, **changes}


def test_miner_screen_values_a_producer():
    from valuescreen import miner_screen as ms
    r = ms.evaluate(_miner_raw(), {"ticker": "TST.TO", "metals": ["gold"], "etfs": ["GDXJ"]})
    eps, nc = 150e6 * 1.4 / 100e6, (200e6 - 100e6) * 1.4 / 100e6          # 2.10 and 1.40 a share in C$
    assert r["stage"] == "producer" and r["v12"] == pytest.approx(12 * eps + nc)
    assert r["mos"] == pytest.approx(1 - 20 / (12 * eps + nc)) and r["signal"] == "green"
    assert r["fcf_yield"] == pytest.approx(200e6 * 1.4 / 100e6 / 20)
    assert r["market_value_usd"] == pytest.approx(20 * 100e6 * 0.7 / 1e9)
    assert any("converted" in f for f in r["flags"])


def test_miner_screen_does_not_value_explorers_and_shortlists_producers():
    from valuescreen import miner_screen as ms
    explorer = ms.evaluate(_miner_raw(sales_now=0.0, profit_now=-20e6), {"ticker": "EXP.V"})
    assert explorer["stage"] == "developer / explorer" and explorer["signal"] == "grey"
    raw = {"TST.TO": _miner_raw(), "DEAR": _miner_raw(price=200.0)}
    rows = ms.with_grades([ms.evaluate(raw[t], {"ticker": t}) for t in raw], raw)
    assert [r["ticker"] for r in ms.shortlist(rows)] == ["TST.TO"]


def test_miner_drafts_are_valid_company_files(tmp_path):
    from valuescreen import miner_screen as ms
    raw = {"TST.TO": _miner_raw()}
    row = ms.evaluate(raw["TST.TO"], {"ticker": "TST.TO", "yahoo": "TST.TO", "metals": ["gold"], "etfs": ["GDXJ"]})
    written, _ = ms.write_drafts([row], raw, tmp_path, dt.date(2026, 11, 13))
    c = loader.validate_company(yaml.safe_load((tmp_path / "tst.to.yaml").read_text()))
    assert written == ["TST.TO"] and c["currency"] == "CAD" and c["earnings"]["net_income"] == pytest.approx(210.0)
    assert ms.write_drafts([row], raw, tmp_path, dt.date(2026, 11, 13)) == ([], ["TST.TO"])   # never overwritten


def test_physical_holders_are_not_valued_as_producers():
    from valuescreen import miner_screen as ms
    r = ms.evaluate(_miner_raw(name="Yellow Cake plc"), {"ticker": "YCA.L"})
    assert r["stage"] == "physical holder" and r["signal"] == "grey"


# ------------------------------------------------------------------------------------------------- US screen (SEC figures)
def _sec_facts():
    """A made-up filer: fiscal years = calendar years, 10-Qs with year-to-date cash flow, a 2-for-1 split in 2025."""
    def dur(start, end, val, form="10-Q", filed=None):
        return {"start": start, "end": end, "val": val, "form": form, "filed": filed or end, "accn": f"a-{end}-{start}"}

    def inst(end, val, form="10-Q"):
        return {"end": end, "val": val, "form": form, "filed": end, "accn": f"i-{end}"}
    ni, ocf = [], []
    for y in range(2021, 2027):
        if y < 2026:
            ni.append(dur(f"{y}-01-01", f"{y}-12-31", 400.0 + 40 * (y - 2021), "10-K", f"{y + 1}-02-15"))
            ocf.append(dur(f"{y}-01-01", f"{y}-12-31", 500.0, "10-K", f"{y + 1}-02-15"))
        for q, end in ((1, f"{y}-03-31"), (2, f"{y}-06-30"), (3, f"{y}-09-30")):
            ni.append(dur(f"{y}-{3*q-2:02d}-01", end, 100.0 + 10 * (y - 2021)))
            ocf.append(dur(f"{y}-01-01", end, 125.0 * q))            # year to date
    eps = [dur(f"{y}-01-01", f"{y}-12-31", (400.0 + 40 * (y - 2021)) / (50 if y < 2025 else 100), "10-K", f"{y + 1}-02-15")
           for y in range(2021, 2026)]
    return {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": ni}}, "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
        "Revenues": {"units": {"USD": [dict(f, val=f["val"] * 5) for f in ni]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [inst("2026-09-30", 300.0)]}},
        "LongTermDebt": {"units": {"USD": [inst("2026-09-30", 100.0)]}},
        "StockholdersEquity": {"units": {"USD": [inst(f"{y}-12-31", 2000.0, "10-K") for y in range(2021, 2026)] + [inst("2026-09-30", 2400.0)]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [inst("2026-09-30", 100.0)]}}}}}


def test_sec_quarters_ttm_and_balance():
    from valuescreen.us_fundamentals import summarize
    s = summarize(_sec_facts())
    # TTM to Sep 2026 = Q4 2025 (the year 560 − its three quarters 3 × 140) + Q1–Q3 2026 (3 × 150)
    assert s["ttm_end"] == dt.date(2026, 9, 30) and s["ttm_complete"]
    assert s["ttm"]["net_income"] == pytest.approx(560 - 420 + 450)
    assert s["ttm"]["ocf"] == pytest.approx(500 - 375 + 375)          # Q4 2025 from year-to-date + 2026 Q1–Q3 (125 each)
    assert s["balance"]["cash_and_st"] == 300 and s["balance"]["debt"] == 100 and s["shares"] == 100


def test_sec_database_round_trip_and_point_in_time(tmp_path):
    from valuescreen import factsdb
    from valuescreen.us_fundamentals import wanted_tags
    con = factsdb.connect(tmp_path / "f.sqlite")
    factsdb.save_facts(con, 42, _sec_facts(), wanted_tags())
    full = factsdb.load_facts(con, 42)
    early = factsdb.load_facts(con, 42, filed_by="2024-06-30")
    n = lambda f: len(f["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"])  # noqa: E731
    assert n(full) == len(_sec_facts()["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]) and n(early) < n(full)
    factsdb.save_prices(con, "TST", [("2023-12-29", 40.0), ("2026-11-12", 30.0)], [("2025-06-02", 2.0)])
    assert factsdb.split_factor_since(con, "TST", "2023-12-31") == 2.0 and factsdb.split_factor_since(con, "TST", "2025-12-31") == 1.0


def test_us_screen_values_a_company_and_applies_splits():
    from valuescreen import us_screen as us
    from valuescreen.us_fundamentals import summarize
    entry = {"ticker": "TST", "yahoo": "TST", "name": "Test Inc", "sector": "Information Technology", "industry": "Software",
             "indexes": [], "cik": 42}   # not an index member: the sample's tiny numbers would trip the index sanity check
    px = {"price": 30.0, "date": "2026-11-12", "change_1y": 0.1, "on": lambda day: 40.0,
          "split_since": lambda day: 2.0 if day < "2025-06-02" else 1.0}
    r = us.evaluate_sec(entry, summarize(_sec_facts()), px, cfg_with())
    assert r["eps"] == pytest.approx(5.9)                                # 590 ÷ 100 shares
    assert r["v0"] == pytest.approx(5.9 * dcf_factor(0.0, cfg_with(), 0.10) + 2.0)
    assert r["implied_growth"] is not None and r["implied_growth"] < 0 and r["signal"] == "green"
    # EPS three years back (FY2023: 480 ÷ 50 = 9.6 a share before the split = 4.8 now) vs 5.9 now, price 40 → 30
    assert r["pe_change"] == pytest.approx((30 / 40) / (5.9 / 4.8) - 1, rel=1e-6) and r["grade"] == "A"
    fin = us.evaluate_sec({**entry, "sector": "Financials"}, summarize(_sec_facts()), px, cfg_with())
    assert fin["nc"] == 0.0 and fin.get("pb") is not None


def test_stale_sec_figures_fall_back_and_old_share_counts_are_ignored():
    from valuescreen.us_fundamentals import problem, shares_outstanding, summarize
    facts = _sec_facts()
    assert problem(summarize(facts, dt.date(2026, 11, 13)), dt.date(2026, 11, 13)) is None
    assert "SEC figures end" in problem(summarize(facts, dt.date(2027, 9, 1)), dt.date(2027, 9, 1))
    old = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2010-10-27", "val": 1.2e8, "filed": "2010-11-02", "accn": "x"}]}}}}}
    assert shares_outstanding(old, dt.date(2026, 11, 13)) is None              # stopped tagging years ago
    two_classes = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-10-20", "val": 5.8e9, "filed": "2026-10-30", "accn": "q3"},
        {"end": "2026-10-20", "val": 6.5e9, "filed": "2026-10-30", "accn": "q3"}]}}}}}
    assert shares_outstanding(two_classes, dt.date(2026, 11, 13)) == ("2026-10-20", 12.3e9)   # classes added up


def test_split_adjustment_only_when_the_old_figure_is_pre_split():
    from valuescreen.us_screen import split_multiplier
    assert split_multiplier(50e6, 600e6, 10.0) == 10.0     # 50m before a 10-for-1 split ≈ 500m now: adjust
    assert split_multiplier(520e6, 600e6, 10.0) == 1.0     # already restated: leave it
    assert split_multiplier(500e6, 600e6, 1.0) == 1.0


def test_impossible_figures_for_an_index_member_are_held_back():
    from valuescreen import us_screen as us
    from valuescreen.us_fundamentals import summarize
    entry = {"ticker": "FOX", "yahoo": "FOX", "name": "Fox", "sector": "Communication Services", "industry": "", "indexes": ["S&P 500"], "cik": 1}
    px = {"price": 58.71, "date": "2026-11-12", "change_1y": 0.1, "on": lambda day: 40.0, "split_since": lambda day: 1.0}
    r = us.evaluate_sec(entry, summarize(_sec_facts()), px, cfg_with())       # 100 shares × $58.71 – not a real index member
    assert r["signal"] == "grey" and any(f.startswith("data check") for f in r["flags"]) and r not in us.shortlist([r])
