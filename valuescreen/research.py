"""Private weekly research: a captured report next to our own valuation, prices and charts.

The captures live in data/private/research/<date>.yaml and the report goes to output/private/research.html – both
private (git-ignored; loader.publish refuses them). Only plain support / resistance prices, without any source name or
commentary, may reach the public charts (public_levels).

    load_weeks()                      → captures, oldest first
    levels(item)                      → [{"lo", "hi", "mid", "kind"}] from support / resistance entries
    evaluate(week, prices, ours)      → one row per asset: price, nearest levels, rules, our signal, agree / conflict
    public_levels(weeks, ticker)      → plain levels for a public chart
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from . import loader

FOLDER = loader.ROOT / "data" / "private" / "research"
OUT = loader.ROOT / "output" / "private"
NEAR = 0.03       # a price within 3% of a level or a rule's trigger counts as "near"
AGREE = 0.05      # their support within 5% of our buy level / value = the two views agree


def load_weeks(folder: Path | None = None) -> list[dict]:
    folder = folder or FOLDER
    weeks = []
    for f in sorted(folder.glob("*.yaml")) if folder.exists() else []:
        w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        w["date"] = w["date"] if isinstance(w.get("date"), dt.date) else dt.date.fromisoformat(str(w.get("date") or f.stem))
        w.setdefault("assets", {})
        weeks.append(w)
    return sorted(weeks, key=lambda w: w["date"])


def _band(x):
    if isinstance(x, dict):
        x = x.get("price") if "price" in x else [x["lo"], x["hi"]]
    lo, hi = (min(x), max(x)) if isinstance(x, (list, tuple)) else (x, x)
    return float(lo), float(hi)


def levels(item: dict, kinds=("support", "resistance"), tfs=None) -> list[dict]:
    """[{"lo", "hi", "mid", "kind", "tf", "public"}]. Levels sit under `timeframes: {D: {...}, M: {...}}` (D = daily
    chart, M = monthly / long term) as the report draws them; plain `support` / `resistance` count as daily."""
    groups = item.get("timeframes") or {"D": {k: item.get(k) for k in kinds}}
    out = []
    for tf, block in groups.items():
        if tfs and tf not in tfs:
            continue
        for kind in kinds:
            for x in (block or {}).get(kind) or []:
                public = not (isinstance(x, dict) and x.get("public") is False)
                lo, hi = _band(x)
                out.append({"lo": lo, "hi": hi, "mid": (lo + hi) / 2, "kind": kind, "tf": tf, "public": public})
    return out


def nearest(price: float, item: dict) -> tuple[dict | None, dict | None]:
    """The nearest support at or below the price and the nearest resistance at or above it (zones count when the
    price is inside them)."""
    lv = levels(item, tfs=("D", "W")) or levels(item)
    sup = [x for x in lv if x["lo"] <= price * (1 + NEAR / 3)]
    res = [x for x in lv if x["hi"] >= price * (1 - NEAR / 3)]
    s = max(sup, key=lambda x: x["hi"], default=None)
    r = min(res, key=lambda x: x["lo"], default=None)
    if s and r and s is r:   # inside a zone: it is the support; the next one up is the resistance
        r = min((x for x in res if x["lo"] > s["hi"]), key=lambda x: x["lo"], default=None)
    return s, r


def distance(price: float, lo: float, hi: float) -> float:
    """Signed distance from the price to a level or zone, as a share of the price (0 inside a zone)."""
    if lo <= price <= hi:
        return 0.0
    return (lo - price) / price if price < lo else (hi - price) / price


def rule_status(rule: dict, price: float | None) -> dict:
    """How far a rule is from triggering: 'triggered', 'near' (within NEAR) or 'waiting'."""
    if price is None:
        return {"status": "no price", "gap": None}
    lo, hi = _band(rule["level"])
    if rule["when"] == "below":
        gap = (hi - price) / price            # negative = the price still has to fall this much
        hit = price <= hi
    else:
        gap = (lo - price) / price            # positive = the price still has to rise this much
        hit = price >= lo
    status = "triggered" if hit else "near" if abs(gap) <= NEAR else "waiting"
    return {"status": status, "gap": gap}


def public_levels(weeks: list[dict], ticker: str, symbol: str | None = None) -> list[dict]:
    """Plain support / resistance prices for a public chart – from the latest capture that covers the company, without
    any source, stance or note. Matched on the capture's asset key or its Yahoo symbol."""
    for w in reversed(weeks):
        for key, item in w["assets"].items():
            if key.upper() == ticker.upper() or (symbol and str(item.get("symbol", "")).upper() == symbol.upper()):
                return [{"lo": x["lo"], "hi": x["hi"], "kind": x["kind"], "tf": x["tf"]} for x in levels(item) if x["public"]]
    return []


def changes(week: dict, previous: dict | None) -> dict:
    """{asset: [text]} – levels added or removed and stance changes since the previous capture."""
    if not previous:
        return {}
    out = {}
    for key, item in week["assets"].items():
        old = previous["assets"].get(key)
        if old is None:
            out[key] = ["new this week"]
            continue
        now = {(x["kind"], round(x["lo"], 2), round(x["hi"], 2)) for x in levels(item)}
        before = {(x["kind"], round(x["lo"], 2), round(x["hi"], 2)) for x in levels(old)}   # timeframe moves are not changes
        notes = [f"new {k} {fmt(lo, hi)}" for k, lo, hi in sorted(now - before)]
        notes += [f"dropped {k} {fmt(lo, hi)}" for k, lo, hi in sorted(before - now)]
        if (item.get("stance") or "") != (old.get("stance") or ""):
            notes.append(f"stance: {item.get('stance')} (was: {old.get('stance')})")
        if notes:
            out[key] = notes
    return out


def fmt(lo: float, hi: float | None = None) -> str:
    f = lambda v: f"{v:.3g}" if abs(v) < 1 else f"{v:,.2f}" if v < 1000 else f"{v:,.0f}"  # noqa: E731   ratios: 0.0213
    return f(lo) if hi is None or abs(hi - lo) < 1e-9 else f"{f(lo)}–{f(hi)}"


def our_view(r: dict | None) -> dict:
    """The parts of our valuation the comparison needs."""
    if not r:
        return {}
    return {"signal": r.get("signal"), "action": r.get("action"), "buy": r.get("buy_level"), "add": r.get("add_level"),
            "value_lo": r.get("v_low") if r.get("model") != "growth" else r.get("v0"), "sell": r.get("call_level"),
            "mos": r.get("margin_of_safety"), "growth": r.get("implied_growth"), "model": r.get("model")}


def compare(item: dict, ours: dict, price: float | None) -> list[str]:
    """Where the two views agree or conflict."""
    if not ours or price is None:
        return []
    out = []
    sup = [x for x in levels(item, ("support",))]
    for name, lvl in (("buy level", ours.get("buy")), ("add level", ours.get("add")), ("12x value", ours.get("value_lo"))):
        if lvl and lvl > 0:
            hit = [x for x in sup if abs(x["mid"] / lvl - 1) <= AGREE]
            if hit:
                out.append(f"agree: their support {fmt(hit[0]['lo'], hit[0]['hi'])} ≈ our {name} {lvl:,.2f}")
                break
    stance = (item.get("stance") or "").lower()
    keen = any(w in stance for w in ("bullish", "building", "add", "deep value", "overweight"))
    if ours.get("signal") == "red" and keen:
        out.append(f"conflict: they are positive, our valuation says {ours.get('action')}")
    if ours.get("signal") == "green" and "not adding" in stance:
        out.append("conflict: we see value, they are not adding")
    return out


def evaluate(week: dict, prices: dict, ours: dict) -> list[dict]:
    """One row per asset. prices: {asset key: price}; ours: {asset key: valuation result}."""
    rules = {}
    for rule in week.get("if_then") or []:
        rules.setdefault(rule["asset"], []).append(rule)
    rows = []
    for key, item in week["assets"].items():
        price = prices.get(key)
        s, r = nearest(price, item) if price else (None, None)
        view = our_view(ours.get(key))
        rows.append({
            "key": key, "item": item, "price": price,
            "support": s, "support_gap": distance(price, s["lo"], s["hi"]) if s and price else None,
            "resistance": r, "resistance_gap": distance(price, r["lo"], r["hi"]) if r and price else None,
            "rules": [dict(rule, **rule_status(rule, price)) for rule in rules.get(key, [])],
            "ours": view, "compare": compare(item, view, price),
        })
    return rows


# ------------------------------------------------------------------------------------------------- the private report
STATUS_CLASS = {"triggered": "red", "near": "amber", "waiting": "grey", "no price": "grey"}


def _e(x):
    import html  # noqa: PLC0415
    return html.escape(str(x), quote=True)


def _gap(g):
    return "–" if g is None else ("in zone" if g == 0 else f"{g * 100:+.1f}%")


TF_NAME = {"D": "daily", "W": "weekly", "M": "monthly"}


def _lv_list(item, kind):
    parts = []
    for tf in ("D", "W", "M"):
        lv = levels(item, (kind,), tfs=(tf,))
        if lv:
            parts.append(f"{TF_NAME[tf]}: " + ", ".join(fmt(x["lo"], x["hi"]) for x in lv))
    return " · ".join(parts) or "–"


def build_html(week: dict, rows: list[dict], changed: dict, charts: dict, links: dict, path: Path, weeks: list[dict]) -> Path:
    """output/private/research.html – private; never published."""
    from . import page  # noqa: PLC0415
    from .html_report import chart_block  # noqa: PLC0415
    rules = [dict(rule, asset=row["key"], price=row["price"]) for row in rows for rule in row["rules"]]
    order = {"triggered": 0, "near": 1, "waiting": 2, "no price": 3}
    rules.sort(key=lambda r: (order[r["status"]], abs(r["gap"]) if r["gap"] is not None else 9))
    n_trig = sum(r["status"] == "triggered" for r in rules)
    n_near = sum(r["status"] == "near" for r in rules)
    agree = [(row["key"], c) for row in rows for c in row["compare"] if c.startswith("agree")]
    conflict = [(row["key"], c) for row in rows for c in row["compare"] if c.startswith("conflict")]
    cards = "".join(f'<div class="card" style="border-top-color:{col}"><div class="lbl">{_e(a)}</div><div class="val">{b}</div>'
                    f'<div class="cap">{_e(c)}</div></div>' for a, b, c, col in (
                        ("Rules triggered", n_trig, "price already through the level", "var(--red)"),
                        ("Rules near", n_near, f"within {NEAR * 100:.0f}% of triggering", "#B7791F"),
                        ("Agree with our valuation", len(agree), "their support ≈ our buy level / value", "var(--green)"),
                        ("Conflict", len(conflict), "they are keen, we say expensive (or the reverse)", "var(--red)")))
    rule_rows = "".join(
        f'<tr><td><a href="#a-{_e(r["asset"])}"><b>{_e(r["asset"])}</b></a></td><td>{_e(r["when"])} {fmt(*_band(r["level"]))}</td>'
        f'<td>{_e(r["then"])}</td><td class="nw">{"–" if r["price"] is None else fmt(r["price"])}</td><td class="nw">{_gap(r["gap"])}</td>'
        f'<td><span class="st {STATUS_CLASS[r["status"]]}">{_e(r["status"])}</span></td></tr>' for r in rules)
    asset_rows = []
    for row in rows:
        o, it = row["ours"], row["item"]
        ours = (f'<span class="pill {o["signal"]}">{_e(o["action"])}</span>' if o.get("signal") else "–")
        asset_rows.append(
            f'<tr><td><a href="#a-{_e(row["key"])}"><b>{_e(row["key"])}</b></a><br><small>{_e(it.get("name", ""))}</small></td>'
            f'<td class="nw">{"–" if row["price"] is None else fmt(row["price"])}</td><td>{_e(it.get("stance", "–"))}</td>'
            f'<td class="nw">{fmt(row["support"]["lo"], row["support"]["hi"]) if row["support"] else "–"}<br><small>{_gap(row["support_gap"])}</small></td>'
            f'<td class="nw">{fmt(row["resistance"]["lo"], row["resistance"]["hi"]) if row["resistance"] else "–"}<br><small>{_gap(row["resistance_gap"])}</small></td>'
            f'<td class="sig">{ours}</td><td class="small">{"<br>".join(_e(c) for c in row["compare"]) or "–"}</td></tr>')
    sections = []
    for row in rows:
        key, it, o = row["key"], row["item"], row["ours"]
        ours_txt = ""
        if o.get("signal"):
            bits = [o.get("action") or ""]
            if o.get("mos") is not None and o.get("model") != "growth":
                bits.append(f"margin of safety {o['mos'] * 100:+.0f}%")
            if o.get("growth") is not None:
                bits.append(f"price needs {o['growth'] * 100:+.1f}%/yr growth")
            for name in ("buy", "add", "value_lo", "sell"):
                if o.get(name):
                    bits.append(f"{name.replace('value_lo', '12x value')} {o[name]:,.2f}")
            link = links.get(key)
            ours_txt = (f'<p><b>Our valuation:</b> {_e(" · ".join(bits))}'
                        + (f' · <a href="{_e(link)}">full working</a>' if link else "") + "</p>")
        rules_txt = "".join(f'<li>{_e(r["when"])} {fmt(*_band(r["level"]))} → {_e(r["then"])} '
                            f'<span class="st {STATUS_CLASS[r["status"]]}">{_e(r["status"])} {_gap(r["gap"])}</span></li>' for r in row["rules"])
        notes = "".join(f"<li>{_e(n)}</li>" for n in it.get("notes") or [])
        changes_txt = "".join(f"<li>{_e(c)}</li>" for c in changed.get(key, []))
        history = ""
        if len(weeks) > 1:
            hist = [(w["date"], w["assets"].get(key)) for w in weeks if w["assets"].get(key)]
            history = ('<h4>History</h4><table class="kv"><tr><td><b>Week</b></td><td><b>Support</b></td><td><b>Resistance</b></td><td><b>Stance</b></td></tr>'
                       + "".join(f'<tr><td>{d:%d %b %Y}</td><td>{_e(_lv_list(i, "support"))}</td><td>{_e(_lv_list(i, "resistance"))}</td>'
                                 f'<td>{_e(i.get("stance", ""))}</td></tr>' for d, i in hist) + "</table>")
        sections.append(f"""<section class="company" id="a-{_e(key)}">
<nav class="crumbs"><a href="#top">↑ This week</a></nav>
<div class="head"><h2>{_e(key)} <span>{_e(it.get("name", ""))}</span></h2>{f'<span class="pill big {o["signal"]}">{_e(o["action"])}</span>' if o.get("signal") else ""}</div>
<p class="meta">{_e(it.get("kind", ""))}{" · " + _e(it.get("symbol")) if it.get("symbol") else ""} · price {"–" if row["price"] is None else fmt(row["price"])}</p>
<div class="callout" style="border-left-color:var(--blue)"><b>Their view:</b> {_e(it.get("stance", "–"))}</div>
<div class="grid2"><div><table class="kv"><tr><td>Support</td><td>{_e(_lv_list(it, "support"))}</td></tr>
<tr><td>Resistance</td><td>{_e(_lv_list(it, "resistance"))}</td></tr>
<tr><td>Targets</td><td>{_e(", ".join(fmt(*_band(t)) for t in it.get("targets") or []) or "–")}</td></tr></table>
{f"<h4>Rules</h4><ul>{rules_txt}</ul>" if rules_txt else ""}{f"<h4>Notes</h4><ul class='small'>{notes}</ul>" if notes else ""}</div>
<div>{ours_txt}{"<p><b>Comparison:</b> " + "; ".join(_e(c) for c in row["compare"]) + "</p>" if row["compare"] else ""}
{f"<h4>Changed since last week</h4><ul class='small'>{changes_txt}</ul>" if changes_txt else ""}</div></div>
{chart_block(key, charts.get(key)) if charts.get(key) else '<p class="small">No price history for a chart.</p>'}
{history}
</section>""")
    themes = "".join(f"<li>{_e(t)}</li>" for t in week.get("themes") or [])
    macro = "".join(f"<li><b>{_e(k)}:</b> {_e(v)}</li>" for k, v in (week.get("macro") or {}).items())
    toc = " ".join(f'<a href="#a-{_e(r["key"])}">{_e(r["key"])}</a>' for r in rows)
    scripts = page.chart_scripts() if charts else ""
    body = f"""
<p class="private">PRIVATE – your own research notes. Not committed, not published.</p>
<h1>Research – week of {week['date']:%d %B %Y}</h1>
<p class="sub">{_e(week.get('title', ''))} · {len(rows)} assets · prices as of the latest close</p>
<div class="cards">{cards}</div>
<h3>Rules – how close each one is to triggering</h3>
<div class="wrap"><table class="rt"><tr><th>Asset</th><th>If price is</th><th>Then</th><th>Price</th><th>Gap</th><th>Status</th></tr>{rule_rows}</table></div>
<h3>Every asset – their levels next to our valuation</h3>
<div class="wrap"><table class="rt"><tr><th>Asset</th><th>Price</th><th>Their stance</th><th>Nearest support</th><th>Nearest resistance</th><th>Our signal</th><th>Agree / conflict</th></tr>
{''.join(asset_rows)}</table></div>
<div class="grid2"><div><h3>Themes</h3><ul class="small">{themes}</ul></div><div><h3>Macro</h3><ul class="small">{macro}</ul></div></div>
<nav class="toc">Assets: {toc}</nav>
{''.join(sections)}
<footer>Private research notes next to our own valuation.</footer>
"""
    html_page = page.document(f"Research – {week['date']:%d %b %Y} (private)", page.report_css() + page.asset("research.css"), body,
                              scripts=scripts, head='<meta name="robots" content="noindex">', main_attrs=' id="top"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_page, encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------- chart patterns
def _month(s) -> tuple[int, int]:
    s = str(s)
    return int(s[:4]), int(s[5:7])


def _day(s) -> str:
    """YYYY-MM or YYYY-MM-DD → YYYY-MM-DD (a month means its first day)."""
    s = str(s)
    return s if len(s) >= 10 else f"{s[:7]}-01"


def _months_between(a, b):
    (y0, m0), (y1, m1) = _month(a), _month(b)
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _arc(left, bottom, right):
    """Monthly points of a rounded bowl through left rim → bottom → right rim (parabolic in log price, as drawn on a
    log chart)."""
    import math  # noqa: PLC0415
    (dl, pl), (db, pb), (dr, pr) = [(d, float(v)) for d, v in (left, bottom, right)]
    months = _months_between(dl, dr)
    bottom_month = _months_between(db, db)[0]
    ib = months.index(bottom_month) if bottom_month in months else len(months) // 2
    out = []
    for i, d in enumerate(months):
        if i <= ib:
            f = ((ib - i) / ib) ** 2 if ib else 0
            v = math.exp(math.log(pb) + (math.log(pl) - math.log(pb)) * f)
        else:
            span = len(months) - 1 - ib
            f = ((i - ib) / span) ** 2 if span else 0
            v = math.exp(math.log(pb) + (math.log(pr) - math.log(pb)) * f)
        out.append([d, round(v, 4)])
    return out


def pattern_lines(item: dict) -> list[dict]:
    """Lines to draw for the patterns in a capture: [{"tf", "kind", "label", "points": [[date, price], ...]}]."""
    out = []
    for pat in item.get("patterns") or []:
        tf = pat.get("tf", "M")
        if pat.get("type") in ("cup_handle", "rounding"):
            out.append({"tf": tf, "kind": "cup", "label": pat.get("label", "cup"), "points": _arc(pat["left"], pat["bottom"], pat["right"])})
        if pat.get("type") == "cup_handle" and pat.get("handle_low") and pat.get("breakout"):
            out.append({"tf": tf, "kind": "handle", "label": "handle", "points": _arc(pat["right"], pat["handle_low"], pat["breakout"])})
        if pat.get("type") == "line":   # a trend line: two points, drawn on to the latest bar
            out.append({"tf": tf, "kind": "line", "side": pat.get("side", "support"), "label": pat.get("label", "trend line"),
                        "points": [[_day(pat["from"][0]), float(pat["from"][1])], [_day(pat["to"][0]), float(pat["to"][1])]]})
        rim = pat.get("rim")
        if rim is not None:
            lo, hi = _band(rim)
            start, end = pat["right"][0], pat.get("breakout", pat["right"])[0]   # the rim (breakout line) as drawn: right rim → breakout
            for level in sorted({lo, hi}):
                out.append({"tf": tf, "kind": "rim", "label": "rim", "points": [[f"{str(start)[:7]}-01", level], [f"{str(end)[:7]}-01", level]]})
    return out
