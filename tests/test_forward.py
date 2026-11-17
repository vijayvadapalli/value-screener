"""Forward estimates (valuescreen/forward.py): owner earnings for coming years from the company's own estimates."""
import copy
from pathlib import Path

import pytest

from valuescreen import loader
from valuescreen.engine import run

FIXTURE = Path(__file__).parent / "fixtures" / "nov2026"
CFG = loader.load_config(FIXTURE / "config.yaml")
COS = loader.load_companies(FIXTURE / "companies")

CURVE = dict(metal="uranium", year=2028, spot=[40, 60, 80, 100, 120, 140, 160],
             realised={2028: [50, 60, 72, 80, 83, 87, 90]}, sales_mlb=28, purchases_mlb=3, royalty=0.077, tax_rate=0.25)
FORWARD = dict(tax_rate=0.25, usdcad=1.35, years=[
    dict(year=2026, basis="outlook", pre_tax=[dict(name="gross profit", amount=750.0), dict(name="admin", amount=-270.0)],
         after_tax=[dict(name="D&A", amount=271.0), dict(name="capex", amount=-350.0)]),
    dict(year=2028, basis="contract table", contract_sales=dict(sales_mlb=28, unit_cost=68.5, base_realised=93.5, royalty=0.077),
         pre_tax=[dict(name="admin", amount=-270.0)], after_tax=[]),
], checks=["a check"], consensus=[dict(year=2027, eps=2.41, analysts=18, currency="CAD", source="Yahoo", date="2026-11-17")])


def _ccj():
    cos = copy.deepcopy(COS)
    cos["CCJ"].update(price_sensitivity=CURVE, forward=FORWARD)
    return run(cos, ["CCJ"], CFG)["CCJ"], cos["CCJ"]


def test_lines_add_up_after_tax():
    r, c = _ccj()
    y = r["forward"][0]
    assert y["pre_tax"] == pytest.approx(480.0) and y["tax"] == pytest.approx(-120.0)
    assert y["oe_m"] == pytest.approx(480 * 0.75 + 271 - 350)
    conv = CFG["fx_usd_per_unit"]["CAD"] / CFG["fx_usd_per_unit"][c["price"]["currency"]]
    assert y["oe_ps"] == pytest.approx(y["oe_m"] / c["shares_m"] * conv)
    assert y["values"] == pytest.approx(tuple(y["oe_ps"] * k + r["nc"] for k in (r["mult_lo"], r["mult_hi"], r["sell_multiple"])))


def test_contract_sales_use_the_companys_table_at_spot():
    r, _ = _ccj()
    y = r["forward"][1]
    spot = CFG["spot"]["uranium"]
    realised = (72 + (80 - 72) * (spot - 80) / 20) * 1.35
    gp = 28 * (realised - (68.5 + 0.077 * (realised - 93.5)))
    assert y["lines"][0]["amount"] == pytest.approx(gp)
    assert y["pre_tax"] == pytest.approx(gp - 270)


def test_forward_and_consensus_never_move_the_headline():
    r, _ = _ccj()
    plain = run(COS, ["CCJ"], CFG)["CCJ"]
    assert (r["v_low"], r["v_high"], r["zone"]) == (plain["v_low"], plain["v_high"], plain["zone"])
    assert r["consensus"][0]["eps"] == 2.41 and r["forward_checks"] == ["a check"]
    assert "forward" not in plain
