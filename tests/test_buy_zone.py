"""Buy-zone and review lists (valuescreen/buy_zone.py) and the private decision log."""
import datetime as dt

from valuescreen import buy_zone as B
from valuescreen import page

CFG = {"buy_zone": {"near_support": 0.05, "max_rsi": 30}}


def chart(last, rsi, supports=(), watched=()):
    return {"currency": "USD", "summary": {"last": last, "rsi": rsi, "date": "2026-11-17"},
            "levels": [{"price": p, "kind": "support", "touches": 2} for p in supports] + [{"price": last * 1.2, "kind": "resistance", "touches": 3}],
            "watched": [{"lo": lo, "hi": hi, "kind": "support", "tf": "D"} for lo, hi in watched]}


def result(t, signal):
    return {"ticker": t, "display_ticker": t, "name": t.title(), "signal": signal, "action": "x"}


def test_all_three_is_buy_zone_two_is_review():
    results = {"AAA": result("AAA", "green"), "BBB": result("BBB", "green"), "CCC": result("CCC", "blue"),
               "DDD": result("DDD", "red"), "EEE": result("EEE", "green")}
    charts = {"AAA": chart(100, 25, supports=[97]),          # all three
              "BBB": chart(100, 45, supports=[98]),          # RSI too high → review
              "CCC": chart(100, 22, supports=[99]),          # not green → review
              "DDD": chart(100, 50, supports=[80]),          # one of three
              # EEE: no price history → left out
              }
    rows = B.rows(results, charts, CFG)
    assert [r["ticker"] for r in rows][:3] == ["AAA", "CCC", "BBB"] and "EEE" not in {r["ticker"] for r in rows}
    buy, review = B.split(rows)
    assert [r["ticker"] for r in buy] == ["AAA"]
    assert {r["ticker"] for r in review} == {"BBB", "CCC"}
    assert next(r for r in review if r["ticker"] == "BBB")["missing"] == ["RSI below 30"]
    assert next(r for r in review if r["ticker"] == "CCC")["missing"] == ["valuation green"]


def test_nearest_support_uses_watched_zones_and_ignores_broken_levels():
    assert B.nearest_support(chart(100, 40, supports=[90, 96])) == (96, "auto")
    assert B.nearest_support(chart(100, 40, supports=[90], watched=[(97, 99)])) == (99, "watched")
    assert B.nearest_support(chart(100, 40, watched=[(98, 103)])) == (100, "watched")   # inside the zone: distance 0
    assert B.nearest_support(chart(100, 40)) == (None, "")                              # below every support
    r = B.evaluate(result("X", "green"), chart(100, 20, supports=[94]), B.settings(CFG))
    assert not r["conditions"]["support"] and abs(r["distance"] - (100 / 94 - 1)) < 1e-12   # 6.4% above: not near


def test_decision_log_round_trip_and_only_public_entries_are_published(tmp_path):
    B.append_decision("core", {"date": dt.date(2026, 11, 10), "ticker": "AAA", "decision": "wait", "note": "RSI 34"}, tmp_path)
    B.append_decision("core", {"date": dt.date(2026, 11, 17), "ticker": "AAA", "decision": "buy", "price": 97.5,
                               "note": "at support: a third", "public": True}, tmp_path)
    text = (tmp_path / "core.yaml").read_text()
    assert text.startswith("# Decision log for the core list") and "PRIVATE" in text
    log = B.load_decisions("core", tmp_path)
    assert [(d["date"], d["decision"], d["public"]) for d in log] == [(dt.date(2026, 11, 17), "buy", True),
                                                                      (dt.date(2026, 11, 10), "wait", False)]
    rows = B.rows({"AAA": result("AAA", "green")}, {"AAA": chart(100, 25, supports=[97])}, CFG)
    public = B.section_html(rows, log, CFG)
    assert "at support: a third" in public and "RSI 34" not in public and "last decision 17 Nov: buy" in public
    private = B.section_html(rows, log, CFG, private=True)
    assert "RSI 34" in private and "at support: a third" in private
    assert B.load_decisions("tech", tmp_path) == []


def test_every_page_ends_with_the_disclaimer_and_copyright():
    html = page.document("T", "", "<p>body</p>")
    assert "not investment advice" in html and f"© {dt.date.today().year} {page.COPYRIGHT_HOLDER}" in html
    assert html.index("<p>body</p>") < html.index('<footer class="legal">') < html.index("</main>")
