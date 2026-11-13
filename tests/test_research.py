"""Private research captures: levels, rules, comparison, the public split and the publishing guard. No network."""
import datetime as dt

import pytest
import yaml

from valuescreen import loader
from valuescreen import research as R

WEEK = {
    "date": dt.date(2026, 11, 8), "title": "t",
    "if_then": [{"asset": "AAA", "when": "below", "level": 48, "then": "add"},
                {"asset": "AAA", "when": "above", "level": [100, 120], "then": "trim"}],
    "assets": {"AAA": {"name": "A", "stance": "bullish", "support": [45, [48, 50]], "resistance": [60, {"price": 90, "public": False}]},
               "BBB": {"stance": "at target weight, not adding", "support": [9.5]}},
}


def test_levels_zones_and_nearest():
    lv = R.levels(WEEK["assets"]["AAA"])
    assert [(x["lo"], x["hi"], x["kind"], x["public"]) for x in lv] == [
        (45, 45, "support", True), (48, 50, "support", True), (60, 60, "resistance", True), (90, 90, "resistance", False)]
    s, r = R.nearest(49, WEEK["assets"]["AAA"])
    assert (s["lo"], s["hi"]) == (48, 50) and r["lo"] == 60          # inside a zone: it is the support
    assert R.distance(49, 48, 50) == 0 and R.distance(49, 60, 60) == pytest.approx(11 / 49)


def test_rule_status():
    below, above = WEEK["if_then"]
    assert R.rule_status(below, 49)["status"] == "near"          # 2% above the $48 trigger
    assert R.rule_status(below, 47)["status"] == "triggered"
    assert R.rule_status(below, 70)["status"] == "waiting"
    assert R.rule_status(above, 101)["status"] == "triggered"     # inside the 100–120 band counts
    assert R.rule_status(above, None)["status"] == "no price"


def test_compare_agree_and_conflict():
    ours = {"signal": "red", "action": "Expensive", "buy": 49.0}
    notes = R.compare(WEEK["assets"]["AAA"], ours, 49)
    assert any(n.startswith("agree") for n in notes) and any(n.startswith("conflict") for n in notes)
    assert R.compare(WEEK["assets"]["BBB"], {"signal": "green", "action": "Buy"}, 10) == ["conflict: we see value, they are not adding"]
    assert R.compare(WEEK["assets"]["AAA"], {}, 49) == []


def test_public_levels_are_plain_and_respect_public_false():
    pub = R.public_levels([WEEK], "AAA")
    assert pub == [{"lo": 45, "hi": 45, "kind": "support"}, {"lo": 48, "hi": 50, "kind": "support"},
                   {"lo": 60, "hi": 60, "kind": "resistance"}]               # the private 90 stays out; no stance, no notes
    assert R.public_levels([WEEK], "ZZZ") == []


def test_changes_between_weeks():
    later = {"date": dt.date(2026, 11, 15), "assets": {"AAA": dict(WEEK["assets"]["AAA"], support=[46], stance="neutral"),
                                                      "CCC": {"support": [1]}}}
    ch = R.changes(later, WEEK)
    assert "new support 46.00" in ch["AAA"] and "dropped support 45.00" in ch["AAA"]
    assert any(c.startswith("stance: neutral") for c in ch["AAA"]) and ch["CCC"] == ["new this week"]


def test_evaluate_and_report(tmp_path):
    rows = R.evaluate(WEEK, {"AAA": 49.0}, {"AAA": {"signal": "red", "action": "Expensive", "buy_level": 49.0, "model": "producer"}})
    assert rows[0]["rules"][0]["status"] == "near" and rows[1]["price"] is None
    path = R.build_html(WEEK, rows, {}, {}, {}, tmp_path / "private" / "r.html", [WEEK])
    assert "PRIVATE" in path.read_text()


def test_load_weeks(tmp_path):
    (tmp_path / "2026-11-08.yaml").write_text(yaml.safe_dump({"date": "2026-11-08", "assets": {"X": {"support": [1]}}}))
    weeks = R.load_weeks(tmp_path)
    assert weeks[0]["date"] == dt.date(2026, 11, 8) and R.load_weeks(tmp_path / "none") == []


def test_publish_refuses_private_paths(tmp_path):
    f = tmp_path / "private" / "research.html"
    f.parent.mkdir()
    f.write_text("x")
    with pytest.raises(loader.ValidationError):
        loader.publish(f, "research", ".html")


def test_weekly_steps_cover_the_routine():
    import importlib.util
    spec = importlib.util.spec_from_file_location("weekly", loader.ROOT / "tools" / "weekly.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    full, quick = [s for s, _ in w.steps(False)], [s for s, _ in w.steps(True)]
    assert full[0].startswith("prices") and full[-1] == "tests" and "model portfolios" in full
    assert any(s.startswith("report – core") for s in full) and "screen – miners" in full
    assert "screen – miners" not in quick and "report – nifty50" not in quick
