"""Bad loans at banks and other lenders (valuescreen/asset_quality.py) – India from Screener.in, US from SEC facts."""
import copy

import pytest
from test_playbook import _sec_facts, cfg_with, indian

from valuescreen import asset_quality, screener, v2, wording
from valuescreen.engine import run

# Five quarters: gross NPA 1.0% → 1.8% (up 0.8 points), net NPA 0.9% on ₹1,00,000 cr of loans
STRESSED = {"quarters": ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
            "gross_npa_pct": [1.0, 1.1, 1.2, 1.5, 1.8], "net_npa_pct": [0.3, 0.3, 0.4, 0.6, 0.9],
            "loans_cr": 100000.0, "loans_basis": "test"}
CLEAN = dict(STRESSED, gross_npa_pct=[1.2, 1.2, 1.1, 1.1, 1.1], net_npa_pct=[0.3, 0.3, 0.3, 0.3, 0.3])


def test_india_bad_loans_per_share_and_warning_signs():
    aq = asset_quality.india(STRESSED, 1000.0, cfg_with())
    assert aq["bad_loans_ps"] == pytest.approx(9.0)          # 0.9% × ₹1,00,000 cr = ₹900 cr ÷ 1,000m shares
    assert aq["coverage"] == pytest.approx(0.5) and aq["gross_npa_change"] == pytest.approx(0.008)
    assert any(f.startswith("provision coverage") for f in aq["flags"])
    assert any(f.startswith("gross NPA up") for f in aq["flags"])
    assert not any(f.startswith("net NPA") for f in aq["flags"])   # 0.9% is under the 2% limit
    assert asset_quality.india(CLEAN, 1000.0, cfg_with())["flags"] == []
    assert asset_quality.india({"gross_npa_pct": [None], "net_npa_pct": [None]}, 1000.0, cfg_with()) is None


def test_financial_value_uses_book_less_bad_loans():
    c = indian([5] * 8, kind="financial", book_value_ps=100.0, roe_5y=0.15, asset_quality=STRESSED)
    w = v2.base_eps(c, cfg_with())
    assert w["adjusted_book_ps"] == pytest.approx(91.0) and w["normal_eps"] == pytest.approx(91.0 * 0.15)
    assert w["eps"] == pytest.approx((20 + 13.65) / 2) and "adjusted book" in w["how"]
    no_aq = indian([5] * 8, kind="financial", book_value_ps=100.0, roe_5y=0.15)
    assert v2.base_eps(no_aq, cfg_with())["normal_eps"] == pytest.approx(15.0)   # no NPA figures: book as reported


def test_bad_loan_warning_caps_a_cheap_lender_at_blue():
    cfg = cfg_with()
    cheap = dict(kind="financial", book_value_ps=100.0, roe_5y=0.15, price=60.0)
    cos = {"BAD": indian([5] * 8, asset_quality=STRESSED, **cheap), "OK": indian([5] * 8, asset_quality=CLEAN, **cheap)}
    cos["BAD"]["ticker"], cos["OK"]["ticker"] = "BAD", "OK"
    res = run(cos, ["BAD", "OK"], cfg)
    assert res["OK"]["signal"] == "green"
    assert res["BAD"]["signal"] == "blue" and "bad loans" in res["BAD"]["signal_caps"]
    assert any(f.startswith("provision coverage") for f in res["BAD"]["flags"])
    assert res["BAD"]["pb"] == pytest.approx(60 / 91) and res["BAD"]["pb_reported"] == pytest.approx(0.6)
    labels = [label for label, _, _ in wording.key_figures(res["BAD"])]
    assert "Bad loans not provided for, per share" in labels and any(x.startswith("Price ÷ adjusted book") for x in labels)


def test_screener_npa_rows():
    quarters = "".join(f"<th>{m} 2026</th>" for m in ("Mar", "Jun", "Sep"))
    html = f"""<div data-company-id="1298"></div>
    <section id="quarters"><table class="data-table"><thead><tr><th></th>{quarters}</tr></thead><tbody>
      <tr><td>EPS in Rs</td><td>1</td><td>1</td><td>1</td></tr>
      <tr><td>Gross NPA %</td><td>1.2</td><td>1.17</td><td>1.11</td></tr>
      <tr><td>Net NPA %</td><td>0.4</td><td>0.41</td><td>0.37</td></tr></tbody></table></section>
    <section id="balance-sheet"><table class="data-table"><thead><tr><th></th><th>Mar 2026</th><th>Sep 2026</th></tr></thead><tbody>
      <tr><td>Other Assets +</td><td>900</td><td>1,000</td></tr><tr><td>Total Assets</td><td>1,200</td><td>1,300</td></tr>
    </tbody></table></section>"""
    aq = screener.parse_asset_quality(html)
    assert aq["gross_npa_pct"][-1] == 1.11 and aq["net_npa_pct"][-1] == 0.37 and aq["company_id"] == "1298"
    assert aq["other_assets"] == 1000 and aq["total_assets"] == 1300 and aq["balance_label"] == "Sep 2026"
    blank = html.replace("<td>1.2</td><td>1.17</td><td>1.11</td>", "<td></td><td></td><td></td>").replace(
        "<td>0.4</td><td>0.41</td><td>0.37</td>", "<td></td><td></td><td></td>")
    assert screener.parse_asset_quality(blank) is None      # banks' consolidated pages leave the rows empty


def test_screener_loans_sanity_check(monkeypatch):
    aq = {"company_id": "1", "other_assets": 1000.0, "total_assets": 1300.0, "balance_label": "Sep 2026"}
    good = '{"Loans n Advances": {"Mar 2026": "12", "Sep 2026": "900"}, "Cash Equivalents": {"Sep 2026": "100"}}'
    monkeypatch.setattr(screener, "get", lambda url: good)
    assert screener.loans_cr(aq, False)[0] == 900
    odd = '{"Loans n Advances": {"Sep 2026": "12"}, "Cash Equivalents": {"Sep 2026": "100"}}'   # misclassified
    monkeypatch.setattr(screener, "get", lambda url: odd)
    loans, basis = screener.loans_cr(aq, False)
    assert loans == 900 and "upper bound" in basis                                      # 1,000 other assets − 100 cash


# ------------------------------------------------------------------------------------------------- US
def _bank_facts(nonaccrual=60.0, nco_now=5.0, nco_before=5.0):
    """The made-up filer as a lender: 1,000 of loans, 40 of allowance, quarterly net charge-offs."""
    f = copy.deepcopy(_sec_facts())
    gaap = f["facts"]["us-gaap"]
    inst = lambda end, val: {"end": end, "val": val, "form": "10-Q", "filed": end, "accn": f"i-{end}"}  # noqa: E731
    gaap["FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss"] = {"units": {"USD": [inst("2026-09-30", 1000.0)]}}
    gaap["FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest"] = {"units": {"USD": [inst("2026-09-30", 40.0)]}}
    gaap["FinancingReceivableExcludingAccruedInterestNonaccrual"] = {"units": {"USD": [inst("2026-09-30", nonaccrual)]}}
    quarters = [("2024-10-01", "2024-12-31"), ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30"),
                ("2025-10-01", "2025-12-31"), ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"), ("2026-07-01", "2026-09-30")]
    gaap["FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery"] = {"units": {"USD": [
        {"start": s, "end": e, "val": nco_before if i < 4 else nco_now, "form": "10-Q", "filed": e, "accn": f"n-{e}"}
        for i, (s, e) in enumerate(quarters)]}}
    return f


def test_us_lender_shortfall_and_flags():
    from valuescreen import us_screen as us
    from valuescreen.us_fundamentals import summarize
    entry = {"ticker": "BNK", "yahoo": "BNK", "name": "Bank", "sector": "Financials", "industry": "Regional Banks",
             "indexes": [], "cik": 7}
    px = {"price": 30.0, "date": "2026-11-12", "change_1y": 0.1, "on": lambda day: 40.0, "split_since": lambda day: 1.0}
    s = summarize(_bank_facts(nco_now=10.0))
    assert s["credit"]["nco_ttm"] == 40.0 and s["credit"]["nco_prev_ttm"] == 20.0
    r = us.evaluate_sec(entry, s, px, cfg_with())
    aq = r["asset_quality"]
    assert aq["nonaccrual"] == pytest.approx(0.06) and aq["bad_loans_ps"] == pytest.approx(0.2)   # (60 − 40) ÷ 100 shares
    assert r["pb"] == pytest.approx(30 / (24.0 - 0.2))
    assert any(x.startswith("nonaccrual loans") for x in r["flags"]) and any(x.startswith("charge-offs up") for x in r["flags"])
    assert any(x.startswith("allowance covers") for x in r["flags"]) and r not in us.shortlist([r])
    healthy = us.evaluate_sec(entry, summarize(_bank_facts(nonaccrual=10.0)), px, cfg_with())
    assert healthy["asset_quality"]["flags"] == [] and healthy["asset_quality"]["bad_loans_ps"] == 0.0
    non_lender = us.evaluate_sec({**entry, "industry": "Software", "sector": "Information Technology"}, s, px, cfg_with())
    assert non_lender.get("asset_quality") is None
