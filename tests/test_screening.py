"""The shared screening rules (valuescreen/screening.py): one copy for the full valuation and both quick screens."""
import pytest

from valuescreen import screening as S

ZONES = {"growth_watch": 0.15, "growth_sell": 0.25}


def test_earnings_basis_by_kind():
    assert S.earnings_basis("normal", 10.0, avg5=30.0) == (10.0, S.TWELVE_MONTHS, None)
    assert S.earnings_basis("cyclical", 10.0, avg5=30.0) == (20.0, S.CYCLICAL, None)
    assert S.earnings_basis("cyclical", 10.0, avg5=None) == (10.0, S.TWELVE_MONTHS, None)
    assert S.earnings_basis("cyclical", -6.7, avg5=73.3, history_break="demerger") == (-6.7, S.HISTORY_BREAK, None)
    eps, basis, normal = S.earnings_basis("financial", 10.0, book=100.0, roe=0.15, bad_loans=20.0)
    assert basis == S.FINANCIAL and normal == pytest.approx(12.0) and eps == pytest.approx(11.0)
    assert S.earnings_basis("financial", 10.0, book=100.0, roe=None)[1] == S.TWELVE_MONTHS
    assert S.earnings_basis("cyclical", None, avg5=5.0) == (None, S.TWELVE_MONTHS, None)


@pytest.mark.parametrize("g, band", [(None, "NO EARNINGS"), (0.03, "BUY"), (0.05, "BUY"), (0.10, "WATCH"),
                                     (0.20, "HOLD"), (0.25, "SELL"), (0.60, "SELL")])
def test_growth_bands(g, band):
    assert S.growth_band(g, 0.05, ZONES) == band


@pytest.mark.parametrize("price, eps, band", [(70, 1, "BUY"), (90, 1, "WATCH"), (110, 1, "HOLD"), (130, 1, "SELL"),
                                              (50, 0, "NO EARNINGS"), (50, -1, "NO EARNINGS")])
def test_multiple_bands(price, eps, band):
    assert S.multiple_band(price, eps, cautious=100, sell=125) == band
    assert S.multiple_band(50, 1, cautious=-5, sell=125) == "HOLD"   # heavy net debt: no margin of safety to measure


def test_caps_and_colours():
    assert S.caps(True, True, True) == ["cyclical", "cash conversion", "bad loans"] and S.caps(False, False, False) == []
    assert S.colour("BUY") == "green" and S.colour("BUY", ["cyclical"]) == "blue"
    assert [S.colour(b) for b in ("WATCH", "HOLD")] == ["blue"] * 2
    assert [S.colour(b) for b in ("SELL", "NO EARNINGS", "NO VALUE", "NOT VALUED")] == ["red"] * 4


def test_zone_text_is_written_from_the_fields():
    from valuescreen.rules import zone_text
    assert zone_text("BUY", "add") == "BUY (add)" and zone_text("BUY") == "BUY"
    assert zone_text("WATCH", high_cost=True) == "WATCH (high cost)"
    assert zone_text("BUY", "start", stale=True) == "STALE (would be BUY)"
    assert zone_text("HOLD", stale=True) == "HOLD · stale"
    assert zone_text("WATCH", stale=True, cyclical=True) == "WATCH · stale · cyclical: check the cycle"
    assert zone_text("BUY", cyclical=True) == "BUY · cyclical: check the cycle" and zone_text("SELL", cyclical=True) == "SELL"


def test_every_model_has_a_complete_kind():
    """A model the loader accepts must say its zone, headline and summary itself (kinds/<model>.py)."""
    from valuescreen import kinds, loader, models
    from valuescreen.kinds.base import Kind
    assert set(kinds.KINDS) == loader.MODELS == set(models.MODEL_FN)
    for name, kind in kinds.KINDS.items():
        for method in ("zone", "headline", "summary_detail"):
            assert getattr(type(kind), method) is not getattr(Kind, method), f"{name} must define {method}"
        assert kind.label, f"{name} needs a label"


@pytest.mark.parametrize("model, extra, message", [
    ("producer", {}, "shares_m is required for model producer"),
    ("growth", {}, "shares_m is required for model growth"),
    ("developer", {}, "developer model needs npv_curve"),
    ("physical", {}, "physical model needs holdings"),
    ("leases", {}, "leases model needs projects"),
    ("leases", {"projects": [], "scenarios": {"Cautious": {}, "Base": {}}, "balance": {}, "shares_m": 1.0},
     "leases model needs a Fair scenario"),
    ("liquid", {}, "liquid model needs liquid_assets"),
    ("liquid", {"liquid_assets": [{"label": "cash", "amount": 1.0}]}, "liquid model needs shares_m"),
])
def test_each_model_checks_its_company_file(model, extra, message):
    from valuescreen import loader
    c = {"ticker": "X", "name": "X", "model": model, "currency": "USD", "sources": ["s"],
         "period": {"label": "Q", "end": "2026-09-30"}, "price": {"value": 1.0, "currency": "USD", "date": "2026-11-13"}, **extra}
    with pytest.raises(loader.ValidationError, match=f"X: {message}"):
        loader.validate_company(c)


def test_the_result_type_declares_every_key_the_engine_produces():
    """valuescreen/types.py documents the result dict; a new key must be added there too."""
    from test_playbook import COS, EXTRA, cfg_with
    from valuescreen.engine import run
    from valuescreen.types import Result
    cos = {**COS, **EXTRA}
    produced = set().union(*(set(r) for r in run(cos, list(cos), cfg_with()).values()))
    assert produced <= set(Result.__annotations__), sorted(produced - set(Result.__annotations__))
