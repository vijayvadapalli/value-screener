"""Stage-1 acceptance: the engine must reproduce the published Nov 2026 reports to within 1%."""
import json
from pathlib import Path

import pytest

from valuescreen import loader
from valuescreen.engine import run, etf_lookthrough

HERE = Path(__file__).parent
EXP = json.loads((HERE / "expected_from_reports.json").read_text())
# The reports are a snapshot of 4 Nov 2026, so test against that data, not the live files that keep being updated.
CFG = loader.load_config(HERE / "fixtures" / "nov2026" / "config.yaml")
COS = loader.load_companies(HERE / "fixtures" / "nov2026" / "companies")
RES = run(COS, sorted(COS), CFG)


def close(a, b, tol=0.01):
    return abs(a - b) <= tol * max(abs(b), 1e-9)


@pytest.mark.parametrize("t", ["AEM", "NEM", "AGI", "SLB", "CCJ"])
def test_main_report_producers(t):
    r, e = RES[t], EXP[t]
    assert close(r["v_low"], e["v12"]) and close(r["v_high"], e["v15"])
    if "g15" in e:
        assert close(r["implied_metal_hi"], e["g15"])


def test_cvx_normal_oil():
    r, e = RES["CVX"], EXP["CVX"]
    assert close(r["v_low"], e["n10"]) and close(r["v_high"], e["n13"])


def test_ivanhoe_coverage():
    e = EXP["IVN"]
    assert close(RES["IVN"]["coverage_hi"], e["v15"] / e["price"])


def test_yellow_cake_nav():
    assert close(RES["YCA"]["nav"], EXP["YCA"]["nav"])


@pytest.mark.parametrize("t", ["CDE", "FSM", "IAG", "PAAS", "RGLD", "WPM", "FNV", "MTA"])
def test_companion_producers(t):
    r, e = RES[t], EXP[t]
    assert close(r["oe"], e["oe"]) and close(r["v_low"], e["v12"]) and close(r["v_high"], e["v15"])


def test_developers():
    assert close(RES["ABRA"]["nav"], EXP["ABRA"]["nav"])
    assert close(RES["NXE"]["nav"], EXP["NXE"]["nav"])


@pytest.mark.parametrize("t", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "QCOM", "AVGO", "ORCL", "TSM", "MU", "AMD", "ASML"])
def test_tech_growth(t):
    r, e = RES[t], EXP["T_" + t]
    assert close(r["v0"], e["v0"]) and abs(r["implied_growth"] - e["g"]) < 0.002


@pytest.mark.parametrize("t", ["HL", "AG", "DSV"])
def test_silver_report(t):
    r, e = RES[t], EXP["S_" + t]
    usd_px = {"HL": 13.98, "AG": 14.85, "DSV": 10.10 * 0.7159}[t]
    assert close(r["coverage_lo"], e["v12"] / usd_px) and close(r["coverage_hi"], e["v15"] / usd_px)
    if t != "DSV":
        assert close(r["implied_metal_hi"], e["impl"])


def test_urnm_lookthrough():
    lt = etf_lookthrough(loader.load_etf("URNM"), RES)
    assert close(lt["coverage_weight"], 67.97, 0.001)
    assert close(lt["ratio_lo"], 0.677, 0.01) and close(lt["ratio_hi"], 0.738, 0.01)
