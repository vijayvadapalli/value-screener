"""The settings panel's JavaScript (valuescreen/assets/screen.js) must judge exactly as growth_screen.py does. Runs the
page's own script in Node against random companies and many settings, and compares with Python. Skipped without Node."""
import copy
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
            assert (js[t][2] is None) == (py[t][2] is None) and (py[t][2] is None or abs(js[t][2] - py[t][2]) < 1e-12)
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
