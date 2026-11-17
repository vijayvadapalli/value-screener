"""Price cases (valuescreen/price_cases.py): the value at fixed metal prices, the company's own model re-run."""
import copy
from pathlib import Path

import pytest

from valuescreen import loader, price_cases
from valuescreen.engine import run

FIXTURE = Path(__file__).parent / "fixtures" / "nov2026"
CFG = copy.deepcopy(loader.load_config(FIXTURE / "config.yaml"))
CFG["price_cases"] = {"gold": [3500, 4000, 5000], "silver": [40, 65], "uranium": [70, 120]}
COS = loader.load_companies(FIXTURE / "companies")


def _cases(*tickers):
    res = run(COS, list(tickers), CFG)
    price_cases.attach(res, COS, CFG)
    return res


def test_spot_row_matches_headline_value():
    res = _cases("AEM", "WPM", "DNN", "SPUT")
    for t in ("AEM", "WPM"):
        r = res[t]
        for table in r["price_cases"]:
            spot = next(x for x in table["rows"] if x["spot"])
            assert spot["values"] == pytest.approx((r["v_low"], r["v_high"], r["v_sell"]))
    for t in ("DNN", "SPUT"):
        spot = next(x for x in res[t]["price_cases"][0]["rows"] if x["spot"])
        assert spot["values"][0] == pytest.approx(res[t]["nav"])


def test_rows_sorted_and_rising_with_the_metal():
    table = _cases("AEM")["AEM"]["price_cases"][0]
    assert table["metal"] == "gold" and [x["price"] for x in table["rows"]] == [3500, 3930, 4000, 5000]
    lows = [x["values"][0] for x in table["rows"]]
    assert lows == sorted(lows) and lows[0] < lows[-1]


def test_small_by_products_get_no_table():
    """FSM's silver is a small share of its metal revenue; WPM's silver is large."""
    res = _cases("FSM", "WPM")
    assert [t["metal"] for t in res["FSM"]["price_cases"]] == ["gold"]
    assert {t["metal"] for t in res["WPM"]["price_cases"]} == {"gold", "silver"}


def test_no_sensitivity_no_table():
    """The fixture's CCJ (no price_sensitivity block) and IVN carry no pounds sold, oil names no oil price: nothing is
    invented for them."""
    res = _cases("CCJ", "IVN", "CVX", "MSFT")
    assert all(r["price_cases"] == [] for r in res.values())


# Cameco's own table (Q3-2026 MD&A, at 30 Sep 2026): expected realised price at each spot price
CAMECO = dict(metal="uranium", year=2028, spot=[40, 60, 80, 100, 120, 140, 160],
              realised={2026: [63, 65, 67, 68, 68, 69, 69], 2028: [50, 60, 72, 80, 83, 87, 90]},
              sales_mlb=28, purchases_mlb=3, royalty=0.077, tax_rate=0.25)


def _ccj(**change):
    cos = copy.deepcopy(COS)
    cos["CCJ"]["price_sensitivity"] = dict(CAMECO, **change)
    res = run(cos, ["CCJ"], CFG)
    price_cases.attach(res, cos, CFG)
    return res["CCJ"], cos["CCJ"]


def test_realised_price_curve_leaves_the_headline_alone():
    r, _ = _ccj()
    plain = run(COS, ["CCJ"], CFG)["CCJ"]
    assert (r["v_low"], r["v_high"]) == pytest.approx((plain["v_low"], plain["v_high"]))
    rows = r["price_cases"][0]["rows"]
    assert [x["price"] for x in rows] == [70, 92, 120]
    assert next(x for x in rows if x["spot"])["values"][0] == pytest.approx(r["v_low"])
    assert rows[0]["values"][0] < r["v_low"] < rows[-1]["values"][0]
    assert "2028 row" in r["price_cases"][0]["note"]


def test_realised_price_curve_reproduces_camecos_reported_sensitivity():
    """MD&A p. 23: spot +US$5/lb → adjusted net earnings −$7m (C$); the 2026 row with the same inputs: about −$8m."""
    from valuescreen.models import curve_delta_ps
    _, c = _ccj(year=2026, sales_mlb=30)
    cfg = copy.deepcopy(CFG)
    cfg["spot"]["uranium"] = 89.5
    cfg["fx_usd_per_unit"]["CAD"] = 1 / 1.35
    c["price"]["currency"] = "CAD"
    ane_up = curve_delta_ps(c, cfg, dict(cfg["spot"], uranium=94.5)) * c["shares_m"]
    assert -10 < ane_up < -6
    assert curve_delta_ps(c, cfg, cfg["spot"]) == 0.0
