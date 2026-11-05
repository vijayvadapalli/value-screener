"""Safety checks on Claude's proposed company file updates. These make no API calls."""
import copy
import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("update_results", ROOT / "tools" / "update_results.py")
ur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ur)

CURRENT = yaml.safe_load((Path(__file__).parent / "fixtures" / "nov2026" / "companies" / "aem.yaml").read_text(encoding="utf-8"))


def proposal():
    new = copy.deepcopy(CURRENT)
    new["period"].update(label="Q4-2026", end="2026-12-31", reported="2027-02-11")
    new["earnings"]["da"] = 470.0
    new["sources"].append("AEM Q4-2026 results")
    return new


def result(new, fields=("earnings.da",)):
    return {"status": "updated", "summary": "", "updated_yaml": yaml.safe_dump(new, sort_keys=False),
            "changes": [{"field": f, "source_url": "https://x", "quote": "q"} for f in fields], "unresolved": []}


def test_good_update_passes():
    new, problems, warnings = ur.review(CURRENT, result(proposal()))
    assert not problems and not warnings
    assert new["earnings"]["da"] == 470.0


def test_share_price_is_kept_from_the_current_file():
    p = proposal()
    p["price"]["value"] = 1.0
    new, problems, _ = ur.review(CURRENT, result(p))
    assert not problems and new["price"] == CURRENT["price"]


@pytest.mark.parametrize("edit, expected", [
    (lambda p: p.update(currency="CAD"), "currency changed"),
    (lambda p: p.update(ticker="NEM"), "ticker changed"),
    (lambda p: p["period"].update(end=CURRENT["period"]["end"]), "not newer"),
    (lambda p: p["period"].update(end="2020-01-01"), "not newer"),
    (lambda p: p.update(sources=CURRENT["sources"]), "no new source"),
    (lambda p: p.pop("metals"), "'metals' was removed"),
    (lambda p: p.pop("name"), "name changed"),
    (lambda p: p["metals"][0].pop("realised"), "needs 'realised'"),
])
def test_bad_updates_are_blocked(edit, expected):
    p = proposal()
    edit(p)
    _, problems, _ = ur.review(CURRENT, result(p))
    assert any(expected in x for x in problems), problems


@pytest.mark.parametrize("text", ["not: [valid", "- a list"])
def test_unusable_yaml_is_blocked(text):
    new, problems, _ = ur.review(CURRENT, {"updated_yaml": text, "changes": []})
    assert new is None and problems


def test_change_without_a_source_is_flagged():
    _, _, warnings = ur.review(CURRENT, result(proposal(), fields=()))
    assert any("earnings.da" in w and "no source" in w for w in warnings)


def test_big_move_is_flagged():
    p = proposal()
    p["shares_m"] = CURRENT["shares_m"] * 1000
    _, _, warnings = ur.review(CURRENT, result(p, fields=("earnings.da", "shares_m")))
    assert any("shares_m" in w and "check the units" in w for w in warnings)


def test_removed_field_is_flagged():
    p = proposal()
    p["metals"][0].pop("aisc")
    _, _, warnings = ur.review(CURRENT, result(p))
    assert any("metals[0].aisc" in w for w in warnings)


def test_unquoted_dates_stay_text():
    p = proposal()
    text = yaml.safe_dump(p, sort_keys=False).replace("'2026-12-31'", "2026-12-31")
    new, problems, _ = ur.review(CURRENT, {"updated_yaml": text, "changes": [{"field": "earnings.da"}]})
    assert not problems and new["period"]["end"] == "2026-12-31"


D = dt.date


def company(label="Q3-2026", end="2026-09-30", reported="2026-10-28", per_year=4, model="producer", next_report=None):
    period = {"label": label, "end": end, "per_year": per_year, "reported": reported}
    if next_report:
        period["next_report"] = next_report
    return {"ticker": "X", "model": model, "period": period}


@pytest.mark.parametrize("c, yahoo, today, due, reason", [
    # Yahoo has the next report, in the past or in the future
    (company(), [D(2026, 10, 28), D(2027, 2, 11)], D(2027, 2, 12), True, "2027-02-11 (Yahoo)"),
    (company(), [D(2026, 10, 28), D(2027, 2, 11)], D(2026, 11, 5), False, "next results expected 2027-02-11"),
    # a company reporting today may not have published yet
    (company(), [D(2027, 2, 11)], D(2027, 2, 11), False, "next results expected"),
    # Yahoo's date for the report already in the file can be a few days off (MU, FNV)
    (company(reported="2026-09-23"), [D(2026, 9, 30)], D(2026, 10, 15), False, "no date"),
    # the company file's date works when Yahoo has nothing (CDE, RGLD)
    (company(end="2026-06-30", reported="2026-08-06", next_report="2026-11-04"), [], D(2026, 11, 5), True, "company file"),
    # a next_report the file has already caught up with no longer counts
    (company(end="2026-09-30", reported="2026-11-04", next_report="2026-11-04"), [], D(2026, 11, 20), False, "no date"),
    # Yahoo dates from long ago are ignored (PDN has 2016)
    (company(), [D(2016, 5, 10)], D(2026, 11, 5), False, "no date"),
    # full-year files ignore quarterly reports, then wait for the next full year (AAPL)
    (company("FY26 (Sep)", "2026-09-26", "2026-10-30", 1), [D(2027, 1, 28)], D(2027, 2, 1), False, "no date"),
    (company("FY26 (Sep)", "2026-09-26", "2026-10-30", 1), [D(2027, 10, 29)], D(2027, 11, 1), True, "Yahoo"),
    # no date anywhere: fall back on how long ago the period ended
    (company(), [], D(2027, 2, 12), False, "no date"),
    (company(), [], D(2027, 2, 13), True, "136 days ago"),
    (company("1H-2026", "2026-06-30", "2026-08-21", 1), [], D(2026, 12, 1), False, "no date"),
    (company("1H-2026", "2026-06-30", "2026-08-21", 1), [], D(2027, 3, 1), True, "days ago"),
    # valued from a study or a NAV
    (company(model="developer"), [D(2027, 2, 11)], D(2027, 3, 1), False, "--force"),
    (company(model="physical"), [], D(2030, 1, 1), False, "--force"),
])
def test_check_due(c, yahoo, today, due, reason):
    got_due, got_reason = ur.check_due(c, yahoo, today)
    assert got_due is due and reason in got_reason, got_reason


@pytest.mark.parametrize("path", sorted((ROOT / "data" / "companies").glob("*.yaml")), ids=lambda p: p.stem)
def test_saving_keeps_the_existing_file_format(path):
    text = path.read_text(encoding="utf-8")
    assert ur.dump(yaml.safe_load(text)) == text
