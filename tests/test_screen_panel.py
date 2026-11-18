"""The settings panel's JavaScript (valuescreen/assets/screen.js) must judge exactly as growth_screen.py does. Runs the
page's own script in Node against random companies and many settings, and compares with Python. Skipped without Node."""
import copy
import datetime as dt
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from valuescreen import growth_screen as G
from valuescreen import html_report, loader

NODE = shutil.which("node")
SCRIPT = Path(__file__).resolve().parent.parent / "valuescreen" / "assets" / "screen.js"
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")


def companies(n=300, seed=7):
    """Random companies covering the cases: missing growth, loss years, guards, state-owned, cyclicals, extras."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        t = f"C{i:03d}"
        eps = rnd.choice([None, -1.0] + [rnd.uniform(0.5, 40) for _ in range(8)])
        start = rnd.uniform(1, 20)
        rate = rnd.uniform(-0.1, 0.45)
        hist = [start * (1 + rate) ** k for k in range(6)]
        if rnd.random() < 0.1:
            hist[rnd.randrange(6)] = -rnd.uniform(0.1, 2)
        if rnd.random() < 0.05:
            hist = hist[:4]
        pe = rnd.choice([None] + [rnd.uniform(3, 45) for _ in range(9)])
        nc = rnd.uniform(-50, 50)
        price = (pe or 15) * (eps if eps and eps > 0 else 5) + nc
        r = {"ticker": t, "name": f"Co {i}", "model": "growth", "price": max(price, 1.0), "price_ccy": "INR", "oe": eps, "nc": nc,
             "pe": pe, "v2": {"ttm": eps, "kind": "cyclical" if rnd.random() < 0.15 else "normal"},
             "cash_conversion": rnd.choice([None, 0.5, 0.9, 1.2]), "stale": rnd.random() < 0.05, "implied_growth": rnd.uniform(-0.2, 0.4),
             "signal": rnd.choice(["green", "blue", "red"]), "action": "Watch / hold", "cyclical": False,
             "asset_quality": {"flags": ["net NPA 3%"]} if rnd.random() < 0.05 else None}
        prom = None if rnd.random() < 0.1 else [rnd.uniform(0.3, 0.9)] * 8
        c = {"ticker": t, "v2": {"eps_annual": hist, "eps_quarters": [eps or 1.0] * 8,
                                 "shareholding": {"quarters": ["q"] * 8, "promoters": prom},
                                 **({"history_not_comparable": "demerger"} if rnd.random() < 0.03 else {})}}
        out.append((r, c, "small cap – added by you" if rnd.random() < 0.05 else None))
    return out


def py_rows(items, cfg):
    return [G.evaluate(copy.deepcopy(r), c, cfg, extra) for r, c, extra in items]


def py_screen(items, base_cfg, st):
    """Python's verdicts for panel settings `st`: the real evaluate()/judge() with the thresholds changed the way the
    panel changes them, plus the panel's own rules (promoters, government-owned, Midcap 150 only, cyclicals)."""
    cfg = copy.deepcopy(base_cfg)
    s, b = cfg["growth_screen"], base_cfg["growth_screen"]
    s.update(max_pe=st["pe"], min_eps_cagr=st["growth"], min_return=st["ret"], exit_multiple=st["exit"])
    s["near_max_pe"] = b["near_max_pe"] if st["pe"] == b["max_pe"] else st["pe"] + (b["near_max_pe"] - b["max_pe"])
    s["near_min_eps_cagr"] = (b["near_min_eps_cagr"] if st["growth"] == b["min_eps_cagr"]
                              else st["growth"] - (b["min_eps_cagr"] - b["near_min_eps_cagr"]))
    out = {}
    for row in py_rows(items, cfg):
        if (st["mid"] and row["extra"]) or (st["cyc"] and row["cyclical"]):
            continue
        excluded = (st["prule"] and (row["promoters"] is None or row["promoters"] < st["promoters"])) or (st["psu"] and row["state_owned"])
        out[row["ticker"]] = ("" if excluded else row["tier"], row["missed"], row["expected_return"])
    return out


def node(rows_json, rules, settings):
    prog = f"""
const S = require({json.dumps(str(SCRIPT))});
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = input.settings.map(st => {{
  const s = Object.assign({{}}, input.rules, st);
  return {{rows: S.screenAll(input.rows, s).map(r => [r.ticker, r.tier, r.missed, r.ret]), funnel: S.funnel(input.rows, s),
          url: S.writeSettings(s, input.rules), back: S.readSettings('?' + S.writeSettings(s, input.rules), input.rules)}};
}});
process.stdout.write(JSON.stringify(out));"""
    res = subprocess.run([NODE, "-e", prog], input=json.dumps({"rows": rows_json, "rules": rules, "settings": settings}),
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def embedded(rows, cfg):
    """The JSON exactly as the page embeds it."""
    html = html_report.screen_panel(rows, cfg["growth_screen"], lambda t: f"midcap150/{t}.html")
    get = lambda i: json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))  # noqa: E731
    return get("screen-data"), get("screen-rules")


def test_javascript_judges_exactly_like_python():
    cfg = {"growth_screen": loader.load_config()["growth_screen"]}
    items = companies()
    data, rules = embedded(py_rows(items, cfg), cfg)
    base = {k: rules[k] for k in ("pe", "growth", "ret", "exit", "promoters", "prule", "psu", "mid", "cyc")}
    rnd = random.Random(3)
    settings = [dict(base)] + [dict(base, pe=rnd.choice([10, 12, 15, 18, 20, 25]), growth=rnd.choice([0.1, 0.15, 0.2, 0.25]),
                                    ret=rnd.choice([0.08, 0.1, 0.12, 0.15]), exit=rnd.choice([12, 15, 18]),
                                    promoters=rnd.choice([0.4, 0.5, 0.6]), prule=rnd.random() < 0.5, psu=rnd.random() < 0.5,
                                    mid=rnd.random() < 0.5, cyc=rnd.random() < 0.5) for _ in range(40)]
    results = node(data, rules, settings)
    for st, res in zip(settings, results):
        py = py_screen(items, cfg, st)
        js = {t: (tier, missed, ret) for t, tier, missed, ret in res["rows"]}
        assert set(js) == set(py), st
        for t in py:
            assert js[t][0] == py[t][0] and js[t][1] == py[t][1], (st, t, js[t], py[t])
            assert (js[t][2] is None) == (py[t][2] is None) and (py[t][2] is None or abs(js[t][2] - py[t][2]) < 1e-8)   # the page keeps 9 digits
        # the funnel ends with exactly the shortlist
        assert res["funnel"][-1][1] == sum(1 for v in py.values() if v[0] == "shortlist")
        assert all(a[1] >= b[1] for a, b in zip(res["funnel"], res["funnel"][1:]))
        # the address round-trips
        assert all(res["back"][k] == pytest.approx(st[k]) for k in st)
    assert results[0]["url"] == ""   # the defaults leave the address clean


def test_expected_return_matches_for_other_holding_years():
    cfg = loader.load_config()["growth_screen"]
    prog = f"""const S = require({json.dumps(str(SCRIPT))});
process.stdout.write(JSON.stringify([3, 5, 7, 10].map(y => S.expectedReturn(10, 5, 150, 0.24, {{haircut: 0.5, cap: 0.15, years: y, exit: 15}}))));"""
    js = json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)
    for years, (ret, assumed) in zip([3, 5, 7, 10], js):
        py_ret, py_assumed = G.expected_return(10, 5, 150, 0.24, dict(cfg, years=years, exit_multiple=15))
        assert abs(ret - py_ret) < 1e-12 and assumed == py_assumed


# ---- the US variant (US screen page, tech report): no promoter or government-owned rule

def us_rows(n=250, seed=11):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        eps = rnd.choice([None, -0.5] + [rnd.uniform(0.5, 20) for _ in range(8)])
        rate = rnd.uniform(-0.1, 0.4)
        hist = [rnd.uniform(1, 10) * (1 + rate) ** k for k in range(6)]
        if rnd.random() < 0.1:
            hist[rnd.randrange(6)] = -1.0
        price = rnd.uniform(10, 400)
        r = {"ticker": f"U{i:03d}", "name": f"US {i}", "price": price, "eps": eps, "nc": rnd.uniform(-20, 20),
             "pe": rnd.uniform(5, 50), "eps_annual": hist, "implied_growth": rnd.uniform(-0.2, 0.4),
             "cash_conversion": rnd.choice([None, 0.5, 0.9, 1.2]), "cyclical": rnd.random() < 0.15, "signal": "blue",
             "action": "Watch / hold", "insiders": rnd.choice([None, 0.01, 0.2])}
        out.append(r)
    return out


def test_us_panel_judges_exactly_like_python():
    base = loader.load_config()
    rows = [G.evaluate_us(copy.deepcopy(r), base) for r in us_rows()]
    html = html_report.screen_panel(rows, base["us_growth_screen"], lambda t: None, "us")
    assert "Promoter rule" not in html and "government-owned" not in html and "Reset to the default rules" in html
    get = lambda i: json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))  # noqa: E731
    data, rules = get("screen-data"), get("screen-rules")
    rnd = random.Random(5)
    keys = ("pe", "growth", "ret", "exit", "cyc")
    settings = [{k: rules[k] for k in keys}] + [{"pe": rnd.choice([12, 15, 18, 22, 30]), "growth": rnd.choice([0.08, 0.12, 0.15, 0.2]),
                                                 "ret": rnd.choice([0.06, 0.1, 0.14]), "exit": rnd.choice([12, 15, 20]),
                                                 "cyc": rnd.random() < 0.5} for _ in range(30)]
    results = node(data, rules, settings)
    b = base["us_growth_screen"]
    for st, res in zip(settings, results):
        cfg = copy.deepcopy(base)
        s = cfg["us_growth_screen"]
        s.update(max_pe=st["pe"], min_eps_cagr=st["growth"], min_return=st["ret"], exit_multiple=st["exit"])
        s["near_max_pe"] = b["near_max_pe"] if st["pe"] == b["max_pe"] else st["pe"] + (b["near_max_pe"] - b["max_pe"])
        s["near_min_eps_cagr"] = (b["near_min_eps_cagr"] if st["growth"] == b["min_eps_cagr"]
                                  else st["growth"] - (b["min_eps_cagr"] - b["near_min_eps_cagr"]))
        py = {r["ticker"]: (r["tier"], r["missed"]) for r in (G.evaluate_us(copy.deepcopy(x), cfg) for x in us_rows())
              if not (st["cyc"] and r["cyclical"])}
        js = {t: (tier, missed) for t, tier, missed, _ in res["rows"]}
        assert js == {t: (tier, missed) for t, (tier, missed) in py.items()}, st
        assert [label for label, _ in res["funnel"]] == ["Start", "after guards", "+ growth", "+ P/E", "+ 5-yr return"]
        assert res["funnel"][-1][1] == sum(1 for v in py.values() if v[0] == "shortlist")


# ---- the backtest re-picked with the panel's settings (backtestAll) against backtest.run_start with the same rules

def backtest_world(tmp_path, n=70, seed=4):
    """Random Indian companies with prices from 2016: some short of history, cyclical, state-owned, low promoters."""
    from valuescreen import pricedb
    rnd = random.Random(seed)
    con = pricedb.connect(tmp_path / "p.sqlite")
    starts, today = [dt.date(2022, 11, 16), dt.date(2024, 11, 16)], dt.date(2026, 11, 16)
    companies, entries, state = {}, [], []
    for i in range(n):
        t = f"B{i:02d}"
        first = 2018 if rnd.random() < 0.3 else 2016   # from 2018: one year short of 5-year growth at the 2022 start
        years = [f"Mar {y}" for y in range(first, 2027)]
        rate = rnd.uniform(0.0, 0.45)
        eps = [rnd.uniform(1, 10) * (1 + rate) ** k for k in range(len(years))]
        if rnd.random() < 0.1:
            eps[rnd.randrange(len(eps))] = -1.0
        since = 2024 if rnd.random() < 0.35 else 2021   # from 2024: the holding at the 2022 start is unknown
        quarters = [f"{m} {y}" for y in range(since, 2027) for m in ("Mar", "Jun", "Sep", "Dec")]
        companies[t] = {"ticker": t, "name": f"Co {i}", "yahoo": f"{t}.NS", "sector": "Capital Goods",
                        "v2": {"eps_annual": eps, "years": years, "kind": "cyclical" if rnd.random() < 0.2 else "normal",
                               "shareholding": {"quarters": quarters, "promoters": [rnd.uniform(0.3, 0.8)] * len(quarters)}}}
        if rnd.random() < 0.15:
            state.append(t)
        entries.append({"ticker": t})
        bars = {"2016-01-04": rnd.uniform(5, 300)}
        for d in starts + [today]:
            c = rnd.uniform(5, 300)
            bars[d.isoformat()] = (c, c * rnd.uniform(0.8, 1.0))
        pricedb.save_bars(con, f"{t}.NS", [(d, *(v if isinstance(v, tuple) else (v, v))[:1] * 4,
                                            (v if isinstance(v, tuple) else (v, v))[1], 0) for d, v in bars.items()])
    pricedb.save_bars(con, "^NSEI", [(d, 1, 1, 1, c, c, 0) for d, c in (("2016-01-04", 80.0), ("2022-11-16", 100.0),
                                                                      ("2024-11-16", 120.0), ("2026-11-16", 150.0))])
    return con, companies, entries, starts, today, state


def test_backtest_repicked_in_the_browser_matches_python(tmp_path):
    from valuescreen import backtest
    con, cos, entries, starts, today, state = backtest_world(tmp_path)
    base = loader.load_config()
    base["growth_screen"]["state_owned"] = state
    run = lambda cfg: [backtest.run_start(entries, cos, cfg, con, st, today, "^NSEI") for st in starts]  # noqa: E731
    results = run(base)
    html = html_report.backtest_html(results, base, "Nifty 50", panel=True)
    bt = json.loads(re.search(r'<script type="application/json" id="bt-data">(.*?)</script>', html, re.S).group(1))
    rules = json.loads(re.search(r'id="screen-rules">(.*?)</script>',
                                 html_report.screen_panel([], base["growth_screen"], lambda t: None), re.S).group(1))
    rnd = random.Random(9)
    keys = ("pe", "growth", "ret", "exit", "promoters", "prule", "psu", "cyc")
    settings = [{k: rules[k] for k in keys}] + [
        {"pe": rnd.choice([10, 15, 20, 25, 35]), "growth": rnd.choice([0.05, 0.1, 0.2, 0.3]), "ret": rnd.choice([0.0, 0.08, 0.12, 0.2]),
         "exit": rnd.choice([10, 15, 20]), "promoters": rnd.choice([0.4, 0.6]), "prule": rnd.random() < 0.5,
         "psu": rnd.random() < 0.5, "cyc": rnd.random() < 0.5} for _ in range(25)]
    prog = f"""const S = require({json.dumps(str(SCRIPT))});
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(input.settings.map(st => S.backtestAll(input.bt, Object.assign({{}}, input.rules, st)))));"""
    js = json.loads(subprocess.run([NODE, "-e", prog], input=json.dumps({"bt": bt, "rules": rules, "settings": settings}),
                                   capture_output=True, text=True, check=True).stdout)
    assert sum(1 for b in bt["starts"] for r in b["rows"] if r.get("short")) > 5   # the one-year-short hold is covered
    some = 0
    for st, res in zip(settings, js):
        cfg = copy.deepcopy(base)
        cfg["growth_screen"].update(max_pe=st["pe"], min_eps_cagr=st["growth"], min_return=st["ret"], exit_multiple=st["exit"])
        for b, j in zip(run(cfg), res):
            out = lambda r: (st["cyc"] and r["cyclical"]) or (st["prule"] and r["promoters"] is not None and r["promoters"] < st["promoters"]) \
                or (st["psu"] and r["state_owned"])  # noqa: E731
            picks = [r for r in b["picks"] if not out(r)]
            assert [r["t"] for r in j["picks"]] == [r["ticker"] for r in picks], st
            mean = sum(r["total_return"] for r in picks) / len(picks) if picks else None
            assert (j["picks_ret"] is None) == (mean is None) and (mean is None or abs(j["picks_ret"] - mean) < 1e-4)
            for r, p in zip(j["picks"], picks):
                assert abs(r["er"] - p["expected_return"]) < 1e-8
            alls = [r["total_return"] for r in b["all_rows"] if not (st["cyc"] and r["cyclical"])]
            assert j["screened"] == len(alls) and abs(j["all"] - sum(alls) / len(alls)) < 1e-7
            some += len(picks)
    assert some > 20   # the settings did pick stocks
    assert any("prom" not in r for b in bt["starts"] for r in b["rows"]) and any("prom" in r for b in bt["starts"] for r in b["rows"])


def test_funnel_sentence_and_near_misses_match_between_server_and_browser():
    """At the default rules the page shows what the server wrote; once a slider moves, the browser writes the funnel
    sentence and the near-miss line. Both must read the same at the defaults."""
    cfg = {"growth_screen": loader.load_config()["growth_screen"]}
    rows = py_rows(companies(), cfg)
    data, rules = embedded(rows, cfg)
    prog = f"""
const S = require({json.dumps(str(SCRIPT))});
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const steps = S.funnel(input.rows, input.rules);
const judged = S.screenAll(input.rows, input.rules);
process.stdout.write(JSON.stringify({{steps, text: S.funnelText(steps),
  near: judged.filter(r => r.tier === 'near miss').map(r => [r.ticker, S.shortOf(r)])}}));"""
    res = json.loads(subprocess.run([NODE, "-e", prog], input=json.dumps({"rows": data, "rules": rules}),
                                    capture_output=True, text=True, check=True).stdout)
    steps = html_report.funnel_steps(rows, cfg["growth_screen"])
    assert [list(x) for x in steps] == res["steps"]
    assert [label for label, _ in steps][-1] == "+ promoters"   # the promoter rule is on by default, government-owned off
    assert html_report.funnel_text(steps) == res["text"]
    assert res["text"].startswith(f"Of <b>{len(G.apply_filters(rows, cfg['growth_screen']))}</b> companies") and res["text"].endswith("– the shortlist.")
    py_near = {r["ticker"]: html_report._short_of(r) for r in G.apply_filters(rows, cfg["growth_screen"]) if r["tier"] == "near miss"}
    assert py_near and dict(res["near"]) == py_near


def test_screen_section_reads_answer_first():
    """The five rules folded under a summary, the panel open, the funnel sentence, the shortlist table, near misses on
    one line, then the answer box."""
    cfg = loader.load_config()
    rows = sorted(py_rows(companies(60), {"growth_screen": cfg["growth_screen"]}), key=G.sort_key)
    shown = G.apply_filters(rows, cfg["growth_screen"])
    answer = html_report.answer_html(shown, [], "Index", below=True)
    html = html_report.growth_screen_html(rows, cfg, panel=True, after=answer)
    assert html.count("<li><b>") == 5 and '<details class="rules"><summary>The five rules <small>· P/E ≤ <b data-r="pe">15</b>' in html
    assert f'<p class="funnel">Of <b>{len(shown)}</b> companies' in html
    assert '<p class="near"><b>Near misses:</b>' in html
    assert '<details class="tweak" hidden open><summary>Change the rules</summary>' in html
    assert html.index('class="funnel"') < html.index('class="screen-tables"') < html.index('id="answer"')
    n = sum(1 for r in shown if r["tier"] == "shortlist")
    assert (f"Today {n} stock" in answer) if n else ('class="nopass"' in html and "data-ans=\"today\"" not in answer)
    near = sum(1 for r in shown if r["tier"] == "near miss")
    assert f'{near} near miss{"" if near == 1 else "es"} of {len(shown)}</h2>' in html


def test_default_switches_hold_back_from_the_shortlist():
    """The panel's default switches (config default_filters: the promoter rule and the list only) apply on the server
    too: no hand-added or low-promoter company on the shortlist; government-owned companies and cyclicals stay in; the
    panel still gets every row with its own guards. A list with no promoter data starts with the promoter rule off."""
    cfg = loader.load_config()
    s = cfg["growth_screen"]
    assert G.filters(s) == {"prule": True, "psu": False, "mid": True, "cyc": False}
    rows = sorted(py_rows(companies(), {"growth_screen": s}), key=G.sort_key)
    shown = G.apply_filters(rows, s)
    assert len(shown) < len(rows) and not any(r["extra"] for r in shown) and any(r["cyclical"] for r in shown)
    for r in shown:
        if r["tier"]:
            assert r["promoters"] is not None and r["promoters"] >= s["min_promoter"]
    held = [r for r in shown if any(g.startswith(("promoters", "no promoter")) for g in r["guards"])]
    assert held and all(r["tier"] == "" for r in held)
    data, rules = embedded(rows, {"growth_screen": s})
    assert len(data) == len(rows) and not any(g.startswith("promoters") for d in data for g in d["guards"])
    assert rules["prule"] and rules["mid"] and not rules["psu"] and not rules["cyc"] and rules["all"] is False
    no_data = [dict(r, promoters=None) for r in rows]   # the Nifty 50 files carry no promoter holding
    assert G.filters(s, no_data)["prule"] is False and len(G.apply_filters(no_data, s)) == len(shown)
    assert G.filters({}) == {k: False for k in G.FILTERS} and G.apply_filters(rows, {}) == rows   # the US screen: no switches


def test_backtest_at_the_default_switches_matches_the_browser(tmp_path):
    """backtest.run applies the panel's default switches (with_filters): its picks and all-screened averages are what
    the browser's backtestAll gives at the defaults, and bt-data still carries every stock for when a switch goes off."""
    from valuescreen import backtest
    con, cos, entries, starts, today, state = backtest_world(tmp_path)
    base = loader.load_config()
    base["growth_screen"]["state_owned"] = state
    s, f = base["growth_screen"], G.filters(base["growth_screen"])
    results = [backtest.with_filters(backtest.run_start(entries, cos, base, con, st, today, "^NSEI"), s, f) for st in starts]
    html = html_report.backtest_html(results, base, "Nifty 50", panel=True, promoter_note=True)
    assert "Promoter rule not applied before 2025: data not available." in html
    so = sum(1 for b in results for r in b["picks"] if r["state_owned"])
    assert (f'{so} of the {sum(len(b["picks"]) for b in results)} picks were government-owned' in html) if so else "bt-default" not in html
    bt = json.loads(re.search(r'<script type="application/json" id="bt-data">(.*?)</script>', html, re.S).group(1))
    rules = json.loads(re.search(r'id="screen-rules">(.*?)</script>', html_report.screen_panel([], s, lambda t: None), re.S).group(1))
    prog = f"""const S = require({json.dumps(str(SCRIPT))});
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify([S.backtestAll(input.bt, input.rules), S.backtestAll(input.bt, Object.assign({{}}, input.rules, {{cyc: false}}))]));"""
    js, js_all = json.loads(subprocess.run([NODE, "-e", prog], input=json.dumps({"bt": bt, "rules": rules}),
                                           capture_output=True, text=True, check=True).stdout)
    for b, j, j_all in zip(results, js, js_all):
        assert [r["t"] for r in j["picks"]] == [r["ticker"] for r in b["picks"]]
        assert j["screened"] == b["screened"] and abs(j["all"] - b["all_ret"]) < 1e-7
        assert j_all["screened"] == len(b["all_rows"])
    # every switch on: cyclicals and government-owned out of the picks, cyclicals out of all screened too
    on = {k: True for k in G.FILTERS}
    strict = [backtest.with_filters(backtest.run_start(entries, cos, base, con, st, today, "^NSEI"), s, on) for st in starts]
    js_on = json.loads(subprocess.run([NODE, "-e", prog.replace("input.rules)", "Object.assign({}, input.rules, {psu: true, cyc: true}))", 1)],
                                      input=json.dumps({"bt": bt, "rules": rules}), capture_output=True, text=True, check=True).stdout)[0]
    for b, j in zip(strict, js_on):
        assert not any(r["cyclical"] or r["state_owned"] for r in b["picks"])
        assert [r["t"] for r in j["picks"]] == [r["ticker"] for r in b["picks"]]
        assert j["screened"] == b["screened"] == sum(1 for r in b["all_rows"] if not r["cyclical"])
