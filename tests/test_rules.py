import copy
import datetime as dt
from pathlib import Path

from valuescreen import loader
from valuescreen.engine import run
from valuescreen.models import interp, dcf_factor

FIXTURE = Path(__file__).parent / "fixtures" / "nov2026"  # a fixed snapshot, so updating live data can't break these
CFG = loader.load_config(FIXTURE / "config.yaml")
COS = loader.load_companies(FIXTURE / "companies")


def test_stale_never_buy():
    cos = copy.deepcopy(COS)
    cfg = copy.deepcopy(CFG)
    cfg["as_of"] = dt.date(2027, 6, 1)          # everything is old by then
    res = run(cos, sorted(cos), cfg)
    assert not any(r["zone"] == "BUY" for r in res.values())
    assert all(r["stale"] for r in res.values())


def test_q2_files_are_stale_today():
    res = run(COS, ["IAG", "CDE", "AG"], CFG)
    assert all(r["stale"] for r in res.values())


def test_higher_gold_raises_value():
    lo = run(COS, ["AEM"], CFG)["AEM"]["v_low"]
    cfg = copy.deepcopy(CFG); cfg["spot"]["gold"] = 4500
    hi = run(COS, ["AEM"], cfg)["AEM"]["v_low"]
    assert hi > lo


def test_interp_and_extrapolation():
    assert interp([[0, 0], [10, 100]], 5) == (50, False)
    y, ext = interp([[0, 0], [10, 100]], 12)
    assert ext and abs(y - 120) < 1e-9


def test_no_growth_factor_is_about_13x():
    assert abs(dcf_factor(0.0, CFG) - 13.105) < 0.01


def test_high_cost_blocks_buy():
    cos = copy.deepcopy(COS)
    c = cos["IAG"]; c["period"]["end"] = dt.date(2026, 10, 1); c["period"].pop("next_report", None)
    c["price"]["value"] = 10.0                 # big margin of safety…
    c["metals"][0]["aisc"] = 3000               # …but AISC is 76% of spot
    r = run(cos, ["IAG"], CFG)["IAG"]
    assert r["zone"].startswith("WATCH (high cost)")
