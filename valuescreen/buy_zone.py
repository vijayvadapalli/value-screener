"""Buy-zone and review lists for a portfolio list (list setting `buy_zone: true` – the core list), with a decision log.

A company is in the **buy zone** when all three hold (thresholds under `buy_zone:` in config.yaml):

  valuation   the signal is green – the price is at or below the buy level
  support     the price is at most `near_support` (5%) above the nearest support below it: a level found on the chart
              (chart_levels.levels, marked "auto") or a watched support level shown on the public chart
  RSI         the 14-day RSI is below `max_rsi` (30) – oversold

**Review** = two of the three: worth a look, with the missing one named. Companies with no price history are left out
(no support or RSI to test). Everything comes from the price-chart data the report already builds (price_chart.payload),
so the support, the RSI and the price are the ones the chart shows, in the chart's currency.

The decision log – what you decided and why – lives in data/private/decisions/<list>.yaml, private and never
committed (tools/decide.py adds an entry). Only entries marked `public: true` reach the published report; the full log
goes to the private page output/private/<list>-decisions.html.

    rows(results, charts, cfg)            → [{ticker, conditions, met, missing, ...}] for every company with a chart
    split(rows)                           → (buy zone, review)
    load_decisions(list_name)             → entries, newest first
    section_html(rows, entries, ...)      → the report section: the two lists next to the decision log
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

import yaml

from . import loader

FOLDER = loader.ROOT / "data" / "private" / "decisions"
PRIVATE_OUT = loader.ROOT / "output" / "private"
DEFAULTS = {"near_support": 0.05, "max_rsi": 30}
NAMES = {"value": "valuation green", "support": "near support", "rsi": "RSI below {max_rsi:g}"}


def e(x) -> str:
    return html.escape(str(x), quote=True)


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("buy_zone") or {})}


def nearest_support(chart: dict) -> tuple[float | None, str]:
    """The nearest support at or below the last price – (price, "auto" | "watched") – or (None, "") when the price is
    below every support found. A watched zone the price sits inside counts as distance 0."""
    last = (chart.get("summary") or {}).get("last")
    if not last:
        return None, ""
    found = [(x["price"], "auto") for x in chart.get("levels") or [] if x["kind"] == "support" and x["price"] <= last]
    found += [(min(x["hi"], last), "watched")   # inside a watched zone: the price itself
              for x in chart.get("watched") or [] if x["kind"] == "support" and x["lo"] <= last]
    return max(found, key=lambda b: b[0]) if found else (None, "")


def evaluate(r: dict, chart: dict, s: dict) -> dict:
    """One company's three checks."""
    summary = chart.get("summary") or {}
    last, rsi = summary.get("last"), summary.get("rsi")
    support, source = nearest_support(chart)
    distance = (last / support - 1) if support else None
    conditions = {"value": r.get("signal") == "green",
                  "support": distance is not None and distance <= s["near_support"],
                  "rsi": rsi is not None and rsi < s["max_rsi"]}
    return {"ticker": r["ticker"], "display_ticker": r.get("display_ticker", r["ticker"]), "name": r.get("name", ""),
            "signal": r.get("signal"), "action": r.get("action", ""), "price": last, "date": summary.get("date"),
            "currency": chart.get("currency") or "", "support": support, "support_source": source, "distance": distance,
            "rsi": rsi, "conditions": conditions, "met": sum(conditions.values()),
            "missing": [NAMES[k].format(**s) for k, ok in conditions.items() if not ok]}


def rows(results: dict, charts: dict, cfg: dict) -> list[dict]:
    """Every company with a price chart, most conditions met first, then the closest to support."""
    s = settings(cfg)
    out = [evaluate(r, charts[t], s) for t, r in results.items() if charts.get(t) and (charts[t].get("summary") or {}).get("last")]
    return sorted(out, key=lambda x: (-x["met"], x["distance"] if x["distance"] is not None else 9, x["ticker"]))


def split(rs: list[dict]) -> tuple[list[dict], list[dict]]:
    return [r for r in rs if r["met"] == 3], [r for r in rs if r["met"] == 2]


# ---------------------------------------------------------------------------------------------- the decision log
def decisions_file(list_name: str) -> Path:
    return FOLDER / f"{list_name}.yaml"


def load_decisions(list_name: str, folder: Path | None = None) -> list[dict]:
    """The log's entries, newest first: {date, ticker, decision, note, price, public}. Missing file → []."""
    f = (folder or FOLDER) / f"{list_name}.yaml"
    if not f.exists():
        return []
    raw = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    out = []
    for x in raw if isinstance(raw, list) else raw.get("decisions") or []:
        if not isinstance(x, dict) or not x.get("ticker"):
            continue
        d = x.get("date")
        d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
        out.append({"date": d, "ticker": str(x["ticker"]).upper(), "decision": str(x.get("decision") or ""),
                    "note": str(x.get("note") or ""), "price": x.get("price"), "public": x.get("public") is True})
    return sorted(out, key=lambda x: x["date"], reverse=True)


HEADER = ("# Decision log for the {name} list – what you decided and why. PRIVATE: data/private/ is never committed.\n"
          "# Add an entry with tools/decide.py, or by hand. `public: true` shows that entry in the published report.\n")


def append_decision(list_name: str, entry: dict, folder: Path | None = None) -> Path:
    """Adds one entry at the end of the log (the file and its folder are created when missing; comments are kept)."""
    f = (folder or FOLDER) / f"{list_name}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    text = f.read_text(encoding="utf-8") if f.exists() else HEADER.format(name=list_name)
    if text and not text.endswith("\n"):
        text += "\n"
    item = {k: v for k, v in entry.items() if v is not None}
    f.write_text(text + yaml.safe_dump([item], sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------------------------- HTML
def _num(x) -> str:
    return "–" if x is None else (f"{x:,.2f}" if x < 1000 else f"{x:,.0f}")


def _latest(entries: list[dict]) -> dict:
    out = {}
    for d in entries:   # newest first
        out.setdefault(d["ticker"], d)
    return out


def _list_html(rs: list[dict], last: dict, href, s: dict, empty: str) -> str:
    if not rs:
        return f'<p class="notes">{empty}</p>'
    body = []
    for r in rs:
        t = r["ticker"]
        link = href(t)
        name = f'<a href="{e(link)}"><b>{e(r["display_ticker"])}</b></a>' if link else f'<b>{e(r["display_ticker"])}</b>'
        dist = "–" if r["distance"] is None else f"{r['distance']*100:+.1f}%"
        src = " <small>(watched)</small>" if r["support_source"] == "watched" else ""
        tick = lambda ok: '<span class="pos">✓</span>' if ok else '<span class="neg">✗</span>'  # noqa: E731
        c = r["conditions"]
        decided = last.get(t)
        dec = f'<br><small>last decision {decided["date"]:%d %b}: {e(decided["decision"])}</small>' if decided else ""
        miss = f'<br><small>missing: {e(", ".join(r["missing"]))}</small>' if r["missing"] else ""
        rsi = "–" if r["rsi"] is None else f"{r['rsi']:.0f}"
        body.append(f'<tr data-signal="{e(r["signal"] or "")}"><td>{name}<br><small>{e(r["name"])}</small>{miss}{dec}</td>'
                    f'<td>{_num(r["price"])} <small>{e(r["currency"])}</small></td>'
                    f'<td>{tick(c["value"])} <span class="pill {e(r["signal"] or "")}">{e(r["signal"] or "–")}</span></td>'
                    f'<td>{tick(c["support"])} {_num(r["support"])}{src}<br><small>price {dist} above it</small></td>'
                    f'<td>{tick(c["rsi"])} {rsi}</td></tr>')
    head = (f'<tr><th>Company</th><th>Price</th><th>Valuation</th><th>Nearest support (≤ {s["near_support"]*100:g}% above)</th>'
            f'<th>RSI (&lt; {s["max_rsi"]:g})</th></tr>')
    return f'<div class="wrap"><table class="sum bz"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def log_html(entries: list[dict], limit: int = 12) -> str:
    if not entries:
        return '<p class="notes">No decisions recorded yet.</p>'

    def item(d):
        price = f" at {_num(d['price'])}" if d.get("price") is not None else ""
        note = f" – {e(d['note'])}" if d["note"] else ""
        return (f'<li><small>{d["date"]:%d %b %Y}</small> <b>{e(d["ticker"])}</b> '
                f'<span class="dec">{e(d["decision"])}</span>{price}{note}</li>')
    shown, older = entries[:limit], entries[limit:]
    more = (f'<details><summary>{len(older)} older</summary><ul class="dlog">{"".join(item(d) for d in older)}</ul></details>'
            if older else "")
    return f'<ul class="dlog">{"".join(item(d) for d in shown)}</ul>{more}'


STYLE = ("<style>#buyzone .bzgrid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:24px;align-items:start}"
         "@media (max-width:900px){#buyzone .bzgrid{grid-template-columns:1fr}}"
         "#buyzone ul.dlog{list-style:none;padding:0;margin:6px 0;font-size:13px} #buyzone ul.dlog li{padding:5px 0;"
         "border-bottom:1px solid var(--line)} #buyzone .dec{font-weight:600;text-transform:uppercase;font-size:11.5px;"
         "letter-spacing:.03em;color:var(--blue)} #buyzone table.bz th{cursor:default} #buyzone table.bz th:after{content:none}</style>")


def section_html(rs: list[dict], entries: list[dict], cfg: dict, href=None, private: bool = False) -> str:
    """The buy zone and review lists, with the decision log beside them. Public (private=False): only the log
    entries marked `public: true`."""
    s = settings(cfg)
    href = href or (lambda t: f"#c-{t}")
    shown = entries if private else [d for d in entries if d["public"]]
    buy, review = split(rs)
    last = _latest(shown)
    rule = (f"<b>Buy zone</b> = all three: valuation green, the price at most {s['near_support']*100:g}% above the nearest "
            f"support (auto or watched), and the 14-day RSI below {s['max_rsi']:g}. <b>Review</b> = two of the three. "
            "A prompt to look, not a trade: check the news and the latest results first.")
    log_note = ("" if private or not shown else
                '<p class="notes">Entries chosen for publishing. The full log is kept privately.</p>')
    log = log_html(shown) if shown or private else '<p class="notes">No decisions published yet.</p>'
    return (f'<section class="company" id="buyzone">{STYLE}<h2>Buy zone – {len(buy)} now, {len(review)} to review</h2>'
            f'<p class="notes">{rule}</p><div class="bzgrid"><div>'
            f'<h3>Buy zone</h3>{_list_html(buy, last, href, s, "No company meets all three today.")}'
            f'<h3>Review</h3>{_list_html(review, last, href, s, "No company meets two of the three today.")}</div>'
            f'<div><h3>Decision log</h3>{log}{log_note}</div></div></section>')


def answer_line(rs: list[dict], href=None) -> str:
    """One sentence for the top of the report: who is in the buy zone, who to review."""
    href = href or (lambda t: f"#c-{t}")
    buy, review = split(rs)

    def names(xs):
        out = [f'<a href="{e(href(r["ticker"]))}"><b>{e(r["display_ticker"])}</b></a>' for r in xs]
        return out[0] if len(out) == 1 else ", ".join(out[:-1]) + " and " + out[-1]
    first = (f"<b>Buy zone today:</b> {names(buy)}." if buy else "<b>Nothing is in the buy zone today.</b>")
    second = f" To review (two of three): {names(review)}." if review else ""
    return (f'<div class="answer" id="bz-answer"><p>{first}{second} <a href="#buyzone">The lists and the decision log</a>.</p></div>')


def write_private(rs: list[dict], entries: list[dict], cfg: dict, title: str, list_name: str, out: Path | None = None) -> Path:
    """output/private/<list>-decisions.html – the lists with the whole log; private, never published."""
    from . import page  # noqa: PLC0415
    folder = out or PRIVATE_OUT
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{list_name}-decisions.html"
    body = (f'<h1>{e(title)} – buy zone and decisions (private)</h1><p class="sub">Run {dt.date.today():%d %b %Y} · '
            f'{len(entries)} decisions in data/private/decisions/{e(list_name)}.yaml</p>'
            + section_html(rs, entries, cfg, href=lambda t: None, private=True))
    path.write_text(page.document(f"{e(title)} – decisions (private)", page.report_css(), body,
                                  head='<meta name="robots" content="noindex">'), encoding="utf-8")
    return path
