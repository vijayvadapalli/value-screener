"""The weekly routine in one command, then a short brief of what changed and what needs attention.

    python tools/weekly.py                 # prices, history, every report, screens, model portfolios, research, tests
    python tools/weekly.py --quick         # skip the slow parts (Nifty 50, US screen, miners screen)
    python tools/weekly.py --brief-only    # just the brief, from what is already there

Steps (each one is an existing command, run in order; a failure is reported and the rest carry on):
  1. share prices into the company files (main, miners, Nifty 50)       tools/update_prices.py
  2. daily price history for the charts                                 tools/update_history.py
  3. full reports with live metal prices: core, tech, oil, miners, watchlist (+ Nifty 50)   python -m valuescreen run
  4. quick screens: miners and S&P 500 / Nasdaq-100                     tools/screen_miners.py, tools/screen_us.py
  5. model portfolios                                                   tools/model_portfolio.py
  6. private research report from the latest capture                    tools/research.py
  7. tests                                                              pytest
Then the brief → output/private/weekly-brief.md (private: it includes the research rules).

What still needs judgement – reading new results into company files, the news check, capturing the weekly report –
is done in Claude Code with the /weekly skill (.claude/skills/weekly/SKILL.md), which runs this script.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from valuescreen import engine, loader, pricedb  # noqa: E402
from valuescreen import prices as prices_mod  # noqa: E402
from valuescreen import research as R  # noqa: E402

PY = sys.executable
LISTS = ("core", "tech", "oil", "miners", "watchlist")
NEAR_BUY = 0.05        # price within 5% above our buy level
SOON_DAYS = 10         # results due within this many days


def run(label, args, log):
    t0 = time.time()
    p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    ok = p.returncode == 0
    tail = [x for x in (p.stdout + p.stderr).splitlines() if x.strip() and "warn" not in x.lower()][-3:]
    log.append({"step": label, "ok": ok, "seconds": round(time.time() - t0), "tail": tail})
    print(f"{'✓' if ok else '✗'} {label} ({time.time() - t0:.0f}s)" + ("" if ok else "\n    " + "\n    ".join(tail)))
    return ok


def steps(quick: bool):
    out = [("prices – main lists", ["tools/update_prices.py"]),
           ("prices – promoted miners", ["tools/update_prices.py", "--folder", "miners"])]
    if not quick:
        out.append(("prices – Nifty 50", ["tools/update_prices.py", "--folder", "nifty50"]))
    out.append(("price history", ["tools/update_history.py"]))
    out += [(f"report – {name}", ["-m", "valuescreen", "run", "--list", name, "--live"]) for name in LISTS]
    if not quick:
        out += [("report – nifty50", ["-m", "valuescreen", "run", "--list", "nifty50"]),
                ("screen – miners", ["tools/screen_miners.py"]),
                ("screen – S&P 500 / Nasdaq-100", ["tools/screen_us.py"])]
    out.append(("model portfolios", ["tools/model_portfolio.py"]))
    if R.load_weeks():
        out.append(("private research report", ["tools/research.py"]))
    out.append(("tests", ["-m", "pytest", "-q"]))
    return out


# ------------------------------------------------------------------------------------------------- the brief
def _runs(folder):
    path = loader.output_folder(folder) / "runs.json"
    try:
        runs = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        runs = {}
    dates = sorted(runs)
    return (runs[dates[-1]], runs[dates[-2]], dates[-2]) if len(dates) >= 2 else (runs.get(dates[-1], {}) if dates else {}, {}, None)


def brief(today: dt.date) -> str:
    cfg = loader.load_config()
    try:   # the same live metal prices the reports use (falls back to config.yaml offline)
        prices_mod.refresh_spot(cfg)
    except Exception:  # noqa: BLE001
        pass
    lines = [f"# Weekly brief – {today:%d %b %Y}", "", "_Private (includes your research rules). Educational, not investment advice._", ""]

    # signal changes since the previous run
    changes = []
    for folder in (None, "miners"):
        now, before, when = _runs(folder)
        for t, r in now.items():
            b = before.get(t)
            if b and b.get("signal") != r.get("signal"):
                changes.append(f"- **{t}**: {b.get('signal')} → **{r.get('signal')}** ({r.get('zone')}) since {when}")
    lines += ["## Signals that changed since the previous run", *(changes or ["- none"]), ""]

    # results: overdue, due soon; prices near our buy level
    due, soon, near = [], [], []
    for folder in (None, "miners"):
        companies = loader.load_companies(loader.companies_folder(folder))
        results = engine.run(companies, list(companies), cfg)
        for t, r in results.items():
            nxt = companies[t]["period"].get("next_report")
            if r.get("stale"):
                due.append(f"- **{t}**: {r['stale_reason']}")
            elif nxt and 0 <= (nxt - today).days <= SOON_DAYS:
                soon.append(f"- **{t}**: {companies[t]['period'].get('label')} file; next results {nxt:%d %b}")
            buy = r.get("buy_level")
            if buy and r.get("signal") != "green" and r["price"] <= buy:
                near.append(f"- **{t}**: {r['price']:,.2f} is below our buy level {buy:,.2f} but not green – {r['action']}"
                            + (f" ({', '.join(r['signal_caps'])})" if r.get("signal_caps") else ""))
            elif buy and r.get("signal") != "green" and r["price"] <= buy * (1 + NEAR_BUY):
                near.append(f"- **{t}**: {r['price']:,.2f} is within {NEAR_BUY * 100:.0f}% of our buy level {buy:,.2f} ({r['action']})")
            if r.get("signal") == "green":
                near.append(f"- **{t}**: green – {r['action']} at {r['price']:,.2f} (buy level {buy:,.2f})" if buy else
                            f"- **{t}**: green – {r['action']}")
    lines += ["## Results to read into the company files", *(due or ["- none overdue"]), *soon, ""]
    lines += ["## At or near our buy levels", *(near or ["- none"]), ""]

    # research rules
    weeks = R.load_weeks()
    if weeks:
        week = weeks[-1]
        con = pricedb.connect()
        prices = {}
        for key, item in week["assets"].items():
            sym = item.get("symbol")
            if key == "URANIUM":
                prices[key] = cfg["spot"]["uranium"]
            elif sym and pricedb.last_date(con, sym):
                info = pricedb.info(con, sym) or {}
                prices[key] = pricedb.to_major(pricedb.bars(con, sym)[-1]["close"], info.get("currency"))[0]
        rows = R.evaluate(week, prices, {})
        hits = [f"- **{row['key']}** {rule['when']} {R.fmt(*R._band(rule['level']))} → {rule['then']} "
                f"(**{rule['status']}**, price {row['price']:,.2f}, gap {rule['gap'] * 100:+.1f}%)"
                for row in rows for rule in row["rules"] if rule["status"] in ("near", "triggered")]
        age = (today - week["date"]).days
        lines += [f"## Your research rules (capture of {week['date']:%d %b}{', ' + str(age) + ' days old – capture the new report' if age > 7 else ''})",
                  *(hits or ["- none near or triggered"]), "", "Full detail: output/private/research.html", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="The weekly routine and brief")
    ap.add_argument("--quick", action="store_true", help="skip Nifty 50, the US screen and the miners screen")
    ap.add_argument("--brief-only", action="store_true", help="only write the brief")
    args = ap.parse_args()
    today = dt.date.today()
    log = []
    if not args.brief_only:
        for label, cmd in steps(args.quick):
            run(label, cmd, log)
    text = brief(today)
    failed = [x for x in log if not x["ok"]]
    if failed:
        text += "\n## Steps that failed\n" + "\n".join(f"- {x['step']}: {' / '.join(x['tail'])}" for x in failed) + "\n"
    out = R.OUT / "weekly-brief.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nBrief saved: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
