"""The growth-at-a-value-price screen (valuescreen/growth_screen.py), the shareholding parse and the net-cash filler."""
import copy
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from valuescreen import growth_screen as G
from valuescreen import loader, screener

CFG = {"growth_screen": loader.load_config()["growth_screen"]}
ROOT = Path(__file__).resolve().parent.parent


def result(pe=12.0, oe=10.0, nc=0.0, **kw):
    r = {"ticker": "TEST", "name": "Test Ltd", "model": "growth", "price": pe * oe + nc, "price_ccy": "INR", "oe": oe, "nc": nc,
         "pe": pe, "v2": {"ttm": oe, "kind": "normal"}, "cash_conversion": 0.9, "stale": False, "implied_growth": 0.03,
         "signal": "green", "action": "Buy", "cyclical": False}
    r.update(kw)
    return r


def company(eps=(4.0, 5.0, 6.5, 8.0, 10.0, 12.5), promoters=(0.65,) * 8, **v2):
    return {"ticker": "TEST", "v2": {"eps_annual": list(eps), "shareholding": {"quarters": [f"Q{i}" for i in range(8)],
                                                                              "promoters": list(promoters)}, **v2}}


def test_growth_needs_5_and_3_years_and_every_year_profitable():
    c5, c3, positive = G.eps_growth([4.0, 5.0, 6.5, 8.0, 10.0, 12.5])
    assert c5 == pytest.approx((12.5 / 4) ** 0.2 - 1) and c3 == pytest.approx((12.5 / 6.5) ** (1 / 3) - 1) and positive
    # a depressed start year (2021) flatters 5 years but not 3: the screen takes the lower of the two
    row = G.evaluate(result(), company(eps=(2.0, 6.0, 9.0, 9.5, 9.8, 10.0)), CFG)
    assert row["eps_cagr_5y"] > 0.30 and row["eps_cagr_3y"] < 0.06 and "growth" in row["missed"]
    assert G.eps_growth([1, 2, -1, 3, 4, 5])[2] is False and G.eps_growth([1, 2, 3])[0] is None


def test_expected_return_of_a_five_year_hold():
    s = CFG["growth_screen"]
    ret, assumed = G.expected_return(10.0, 0.0, 150.0, 0.24, s)   # P/E 15 in, 15 out: the return is the growth assumed
    assert assumed == pytest.approx(0.12) and ret == pytest.approx(0.12, abs=1e-9)
    assert G.expected_return(10.0, 0.0, 150.0, 0.60, s)[1] == pytest.approx(0.15)   # capped
    assert G.expected_return(-1.0, 0.0, 150.0, 0.30, s) == (None, None)


@pytest.mark.parametrize("pe, eps, tier, missed", [
    (12.0, (4.0, 5.0, 6.5, 8.0, 10.0, 12.5), "shortlist", []),
    (18.0, (4.0, 5.0, 6.5, 8.0, 10.0, 12.5), "near miss", ["pe", "return"]), # P/E up to 20 (return not held against it)
    (12.0, (5.0, 5.8, 6.7, 7.7, 8.9, 10.3), "near miss", ["growth"]),        # growth of 15–20%
    (25.0, (4.0, 5.0, 6.5, 8.0, 10.0, 12.5), "", ["pe", "return"]),          # two misses
    (12.0, (8.0, 8.4, 8.8, 9.3, 9.7, 10.2), "", ["growth", "return"]),       # growth far below 15%
    (22.0, (5.0, 5.8, 6.7, 7.7, 8.9, 10.3), "", ["pe", "growth", "return"]), # both relaxed: not a near miss
])
def test_tiers(pe, eps, tier, missed):
    row = G.evaluate(result(pe=pe), company(eps=eps), CFG)
    assert row["tier"] == tier and row["missed"] == missed


def test_guards_keep_a_company_off_the_shortlist():
    for extra in ({"cash_conversion": 0.5}, {"stale": True}, {"asset_quality": {"flags": ["net NPA 3%"]}}):
        assert G.evaluate(result(**extra), company(), CFG)["tier"] == ""
    assert G.evaluate(result(), company(history_not_comparable="demerger"), CFG)["guards"] == ["history not comparable"]
    assert "a loss year in the window" in G.evaluate(result(), company(eps=(4, -1, 6, 8, 10, 12)), CFG)["guards"]


def test_promoter_flags_and_tags():
    row = G.evaluate(result(), company(promoters=(0.70, 0.70, 0.70, 0.69, 0.66, 0.58, 0.57, 0.55)), CFG, extra="small cap – added by you")
    assert row["promoters"] == pytest.approx(0.55)
    assert any("promoters 55%" in f for f in row["flags"]) and any("down" in f for f in row["flags"])
    assert "small cap – added by you" in row["flags"] and row["tier"] == "shortlist"   # flags never block


def test_trailing_pe_uses_the_reported_quarters_not_the_cleaned_ones():
    c = company(eps_quarters=[1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 9.0, 2.0])      # 9.0: a one-off the valuation removes
    row = G.evaluate(result(pe=12.0, oe=10.0, v2={"ttm": 8.0, "kind": "normal"}), c, CFG)
    assert row["pe_trailing"] == pytest.approx(120.0 / 15.0)
    no_group = company(); no_group["v2"]["shareholding"]["promoters"] = None
    assert G.evaluate(result(), no_group, CFG)["flags"][0] == "no promoter group"


def test_rows_sort_shortlist_first_and_only_growth_companies():
    results = {"A": result(pe=25.0), "B": result(), "C": dict(result(), model="producer")}
    results = {k: dict(v, ticker=k) for k, v in results.items()}
    cos = {k: dict(company(), ticker=k) for k in results}
    rows = G.rows(results, cos, CFG)
    assert [r["ticker"] for r in rows] == ["B", "A"] and rows[0]["tier"] == "shortlist"


def test_shareholding_is_read_from_the_screener_page():
    quarters = "".join(f"<th>{q}</th>" for q in ("Jun 2026", "Sep 2026"))
    html = f"""<section id="shareholding"><table class="data-table"><thead><tr><th></th>{quarters}</tr></thead><tbody>
      <tr><td>Promoters +</td><td>61.46%</td><td>61.44%</td></tr><tr><td>FIIs +</td><td>19.00%</td><td>18.06%</td></tr>
      </tbody></table></section>"""
    sh = screener.parse_shareholding(screener.soup_of(html))
    assert sh["quarters"] == ["Jun 2026", "Sep 2026"] and sh["promoters"] == [0.6146, 0.6144] and sh["fii"][-1] == pytest.approx(0.1806)
    bank = html.replace("Promoters +", "Government")
    assert screener.parse_shareholding(screener.soup_of(bank))["promoters"] is None
    assert screener.parse_shareholding(screener.soup_of("<p>nothing</p>")) is None


def test_net_cash_note_is_dated_and_replaces_the_placeholder_note():
    spec = importlib.util.spec_from_file_location("fill_net_cash", ROOT / "tools" / "fill_net_cash.py")
    f = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(f)
    c = {"balance": {"net_cash": 0.0}, "assumptions": ["Net cash not yet added – set balance from StockAnalysis", "kept"]}
    out = f.apply(copy.deepcopy(c), {"cash": 2500.0, "debt": 1000.0, "date": dt.date(2026, 9, 30), "currency": "INR"})
    assert out["balance"] == {"cash": 2500.0, "debt": 1000.0}
    assert out["assumptions"][0] == "kept" and out["assumptions"][1].startswith("Net cash derived from Yahoo's balance sheet (30 Sep 2026)")
    assert "₹250 cr" in out["assumptions"][1] and c["balance"] == {"net_cash": 0.0}   # the input is not changed


def test_standalone_quarter_labels():
    assert screener.clean_label("Sep 2026\n            \n            (S)") == "Sep 2026"
    assert screener.month_end("Sep 2026 (S)") == dt.date(2026, 9, 30) and screener.month_end("Mar 2025") == dt.date(2025, 3, 31)


def test_state_owned_companies_are_flagged():
    cfg = {"growth_screen": dict(CFG["growth_screen"], state_owned=["TEST"])}
    assert "state-owned" in G.evaluate(result(), company(), cfg)["flags"]
    assert "state-owned" not in G.evaluate(result(), company(), CFG)["flags"] or "TEST" in CFG["growth_screen"].get("state_owned", [])


def test_multi_page_report_splits_companies_and_shares_assets(tmp_path):
    from test_playbook import COS, cfg_with
    from valuescreen import html_report
    from valuescreen.engine import run
    cfg = cfg_with()
    tickers = ["AEM", "CCJ", "YCA"]
    res = run(COS, tickers, cfg)
    (tmp_path / "single").mkdir()
    single = html_report.build(res, COS, cfg, [], tmp_path / "single" / "s.html", "Test")
    path = html_report.build(res, COS, cfg, [], tmp_path / "Test_16Nov2026.html", "Test", html_report.ReportExtras(pages="testlist"))
    summary = path.read_text()
    assert 'id="c-AEM"' not in summary and 'href="testlist/AEM.html"' in summary and 'href="assets/report.css"' in summary
    assert (tmp_path / "testlist.html").read_text() == summary
    aem = (tmp_path / "testlist" / "AEM.html").read_text()
    assert 'id="c-AEM"' in aem and 'href="../testlist.html#summary"' in aem and 'href="CCJ.html"' in aem
    assert {p.name for p in (tmp_path / "assets").iterdir()} >= {"report.css", "report.js", "charts.js", "sma-colours.js"}
    # the company's section is the one the single page has, apart from the links
    import re
    old = re.search(r'<section class="company" id="c-AEM">.*?</section>', single.read_text(), re.S).group(0)
    new = re.search(r'<section class="company" id="c-AEM">.*?</section>', aem, re.S).group(0)
    new = re.sub(r'href="([^"/#]+)\.html"', r'href="#c-\1"', new.replace('href="../testlist.html#summary"', 'href="#summary"'))
    assert new == old


def test_publishing_a_folder_replaces_it_and_refuses_private_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "reports_folder", lambda: tmp_path / "reports")
    src = tmp_path / "out" / "testlist"
    src.mkdir(parents=True)
    (src / "A.html").write_text("a")
    (tmp_path / "reports" / "testlist").mkdir(parents=True)
    (tmp_path / "reports" / "testlist" / "OLD.html").write_text("old")      # a company that left the list
    target = loader.publish_dir(src, "testlist")
    assert sorted(p.name for p in target.iterdir()) == ["A.html"]
    with pytest.raises(loader.ValidationError):
        loader.publish_dir(src, "private-notes")
