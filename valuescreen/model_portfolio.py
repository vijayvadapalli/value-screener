"""A concentrated model portfolio across asset classes – value first, then quality, with momentum as a filter.

Candidates come from every screen, the most thorough valuation winning when a company appears in several:
full company files (core, oil, tech lists) → the S&P 500 / Nasdaq-100 screen → the miners quick screen. ETFs anchor the
sleeves and the defensive part.

Rules (low risk to capital, a margin of safety on every holding):
- Eligible only with a margin of safety: green on its own model (producers at least 20% below the 12x value, or tier A at
  or below 15x; growth stocks needing at most 5% a year – 8% allowed at half score – ; physical holders below NAV).
- Quality: no STALE or data flags, AISC ≤ 60% of spot, debt ≤ 3× EBITDA, shares not up more than 10% in 3 years,
  cash conversion ≥ 70% (not for financials), profit-vs-price grade not D. Developers, explorers, lease plays, companies
  that are not valued, and tier-C juniors are left out.
- Momentum: price at or above 95% of its 200-day average with a positive 6-month return = full position; otherwise
  "start a third" (a third of the weight now, the rest waits in T-bills).
- Score = a weighted mix of value, quality and momentum; the best in each sleeve are picked.
- Two profiles (PROFILES): balanced – US quality value 40% · miners & royalties 25% · energy 10% · uranium 5% ·
  defensive 20%, scored 45/35/20; resources, value first – miners & royalties 40% · energy 20% · uranium 10% ·
  US quality value 10% · defensive 20%, scored 60/25/15. A sleeve without enough qualifying names is filled with its ETF
  (SPY, GDX, XLE, URNM).
- Sizing: within a sleeve, inversely to each holding's volatility, at most 10% per name. 11 stocks at most per
  profile, so with the ETFs that fill short sleeves and the two defensive ETFs a portfolio holds at most 13–15 names.
Educational framework, not investment advice.
"""
from __future__ import annotations

import datetime as dt
import html
import math
from pathlib import Path

import numpy as np

from . import style as S

SLEEVE_NAMES = {"us": "US quality value", "mining": "Miners & royalties", "energy": "Energy", "uranium": "Uranium",
                "defensive": "Defensive"}
ETFS = {"SPY": ("SPDR S&P 500", "us"), "GDX": ("VanEck Gold Miners", "mining"),
        "XLE": ("Energy Select Sector SPDR", "energy"), "URNM": ("Sprott Uranium Miners", "uranium"),
        "IAU": ("iShares Gold Trust", "defensive"), "SGOV": ("iShares 0–3 Month Treasury Bond", "defensive")}
# sleeve: (target weight, most names, ETF that fills it); defensive: gold and T-bill weights
PROFILES = {
    "balanced": {
        "title": "Model portfolio – balanced", "file": "model-portfolio",
        "blurb": "Five sleeves weighted toward US quality value (45% value, 35% quality, 20% momentum).",
        "sleeves": {"us": (0.40, 5, "SPY"), "mining": (0.25, 3, "GDX"), "energy": (0.10, 2, "XLE"), "uranium": (0.05, 1, "URNM")},
        "defensive": {"IAU": 0.10, "SGOV": 0.10},
        "weights": {"value": 0.45, "quality": 0.35, "momentum": 0.20}, "max_weight": 0.10},
    "resources": {
        "title": "Model portfolio – resources, value first", "file": "model-resources",
        "blurb": "Resource-heavy: 70% in miners, royalties, energy and uranium, ranked mostly on margin of safety "
                 "(60% value, 25% quality, 15% momentum).",
        "sleeves": {"mining": (0.40, 5, "GDX"), "energy": (0.20, 3, "XLE"), "uranium": (0.10, 1, "URNM"), "us": (0.10, 2, "SPY")},
        "defensive": {"IAU": 0.12, "SGOV": 0.08},
        "weights": {"value": 0.60, "quality": 0.25, "momentum": 0.15}, "max_weight": 0.10},
}
GRADE_SCORE = {"A": 1.0, "B": 0.75, "C": 0.5, "n/m": 0.5, "D": 0.0}
MINING_WORDS = ("gold", "silver", "copper", "metal", "mining", "royalty", "precious")


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------------------------------------- candidates
def _sleeve_for_file(r):
    sector = (r.get("sector") or "").lower()
    if "uranium" in sector:
        return "uranium"
    if r["model"] == "growth":
        return "us"
    if "energy" in sector or "oil" in sector or r["model"] == "cashflow":
        return "energy"
    return "mining"


def from_company_file(r: dict, source: str) -> dict:
    """A candidate from a full valuation (valuescreen.engine result)."""
    yahoo = r.get("yahoo") or r["ticker"]
    c = {"key": yahoo.upper(), "anchor": r["ticker"], "ticker": r["display_ticker"], "yahoo": yahoo, "name": r["name"],
         "source": source, "sleeve": _sleeve_for_file(r), "mcap": r.get("market_value_usd_bn"), "signal": r["signal"], "action": r["action"], "price": r["price"],
         "ccy": r["price_ccy"], "buy_level": r.get("buy_level"), "flags": list(r.get("flags", [])), "tier": r.get("tier")}
    m = r["model"]
    reasons = []
    if m in ("developer", "liquid", "leases"):
        reasons.append("no earnings value (developer, explorer or lease play)")
    if r.get("tier") == "C":
        reasons.append("tier C – speculative")
    if r.get("stale"):
        reasons.append("stale results")
    if m in ("producer", "cashflow", "physical", "developer"):
        mos = r.get("margin_of_safety")
        c["value_text"] = "–" if mos is None else f"margin of safety {S.pct(mos)}"
        c["value_score"] = 0.0 if mos is None else clip((mos + 0.2) / 0.8)
        if r["signal"] != "green":
            reasons.append(f"no margin of safety ({r['action']})")
        cost = r.get("cost_ratio")
        if cost is not None and cost > 0.60:
            reasons.append(f"AISC {cost*100:.0f}% of spot")
        q = [{"A": 1.0, "B": 0.7}.get(r.get("tier"), 0.6)] + ([1 - cost] if cost is not None else [])
        c["quality_score"] = sum(q) / len(q)
        c["quality_text"] = " · ".join(x for x in (f"tier {r['tier']}" if r.get("tier") else "",
                                                   f"AISC {cost*100:.0f}% of spot" if cost is not None else "") if x)
        c["exit_rule"] = (f"sell zone from {r['call_level']:,.2f}" if r.get("call_level") else "signal turns red")
    else:   # growth model
        g = r.get("implied_growth")
        c["value_text"] = "–" if g is None else f"needs {S.pct(g, 1)}/yr"
        c["value_score"] = 0.0 if g is None else clip((0.10 - g) / 0.25)
        if g is None or g > 0.08:
            reasons.append(f"no margin of safety ({r['action']})")
        c["quality_score"], c["quality_text"] = 0.6, "full company file"
        c["exit_rule"] = "growth needed above 25% a year"
    c["reasons"] = reasons
    return c


def from_us_screen(r: dict) -> dict:
    sector, industry = r.get("sector") or "", (r.get("industry") or "").lower()
    sleeve = ("energy" if sector == "Energy" else "mining" if sector == "Materials" and any(w in industry for w in MINING_WORDS)
              else "us")
    g = r.get("implied_growth")
    c = {"key": r["yahoo"].upper(), "ticker": r["ticker"], "yahoo": r["yahoo"], "name": r["name"], "source": "US screen", "mcap": r.get("market_value_bn"),
         "sleeve": sleeve, "signal": r.get("signal"), "action": r.get("action"), "price": r["price"], "ccy": "USD",
         "buy_level": None, "flags": list(r.get("flags", [])), "cik": r.get("cik"),
         "value_text": "–" if g is None else f"needs {S.pct(g, 1)}/yr", "value_score": 0.0 if g is None else clip((0.10 - g) / 0.25),
         "exit_rule": "growth needed above 25% a year, or grade D"}
    reasons = []
    if g is None or r.get("signal") not in ("green", "blue") or g > 0.08 or r.get("signal") == "grey":
        reasons.append(f"no margin of safety ({r.get('action')})")
    if r.get("grade") == "D":
        reasons.append("grade D – price ran ahead of profits")
    if r.get("debt_ebitda") and r["debt_ebitda"] > 3:
        reasons.append("debt > 3× EBITDA")
    net_debt_share = -r["nc"] / r["price"] if r.get("nc") is not None and r.get("price") else None
    if net_debt_share is not None and net_debt_share > 0.5:   # catches debt the EBITDA test misses (no operating income tag)
        reasons.append("net debt above half the market value")
    if sector != "Financials" and r.get("fcf_yield") is not None and r["fcf_yield"] <= 0:
        reasons.append("negative free cash flow")
    if (r.get("share_change_3y") or 0) > 0.10:
        reasons.append("diluting shareholders")
    if r.get("low_cash"):
        reasons.append("cash conversion below 70%")
    if any(f.startswith(("data check", "profit ×")) for f in r.get("flags", [])):
        reasons.append("figures need checking")
    q = [GRADE_SCORE.get(r.get("grade", "n/m"), 0.5)]
    if r.get("cash_conversion") is not None and r.get("pb") is None:
        q.append(clip(r["cash_conversion"] / 1.2))
    if r.get("roe") is not None:
        q.append(clip(r["roe"] / 0.20))
    de = r.get("debt_ebitda")
    q.append(0.6 if de is None else 1.0 if de < 1 else 0.6 if de <= 3 else 0.0)
    c["quality_score"] = sum(q) / len(q)
    c["quality_text"] = " · ".join(x for x in (f"grade {r.get('grade', 'n/m')}",
                                               f"ROE {r['roe']*100:.0f}%" if r.get("roe") is not None else "",
                                               f"cash {r['cash_conversion']*100:.0f}%" if r.get("cash_conversion") is not None and r.get("pb") is None else "",
                                               f"P/B {r['pb']:.1f}" if r.get("pb") is not None else "") if x)
    c["reasons"] = reasons
    return c


def from_miners_screen(r: dict) -> dict:
    sleeve = "uranium" if "uranium" in r["metals"] else "mining"
    mos = r.get("mos")
    c = {"key": r["yahoo"].upper(), "ticker": r["ticker"], "yahoo": r["yahoo"], "name": r["name"], "source": "miners screen", "mcap": r.get("market_value_usd"),
         "sleeve": sleeve, "signal": r["signal"], "action": r["action"], "price": r.get("price"), "ccy": r.get("currency") or "USD",
         "buy_level": 0.8 * r["v12"] if r.get("v12") else None, "flags": list(r["flags"]) + ["quick screen – make a full company file before buying"],
         "value_text": "–" if mos is None else f"margin of safety {S.pct(mos)} (quick)",
         "value_score": 0.0 if mos is None else clip((mos + 0.2) / 0.8) * 0.9,   # a quick screen counts a little less
         "exit_rule": "price above the 25x value"}
    reasons = []
    if r["stage"] != "producer" or r["signal"] != "green":
        reasons.append(f"no margin of safety ({r['action']})")
    if (r.get("fcf_yield") or 0) < 0.03:
        reasons.append("free-cash-flow yield below 3%")
    if r.get("grade") == "D":
        reasons.append("grade D")
    if (r.get("market_value_usd") or 0) < 2:
        reasons.append("market value below US$2bn")
    if any(f.startswith(("debt", "capex above", "latest year")) for f in r["flags"]):
        reasons.append("debt, capex or old figures")
    q = [GRADE_SCORE.get(r.get("grade", "n/m"), 0.5), clip((r.get("fcf_yield") or 0) / 0.10)]
    c["quality_score"] = sum(q) / len(q) * 0.9
    c["quality_text"] = f"grade {r.get('grade', 'n/m')} · FCF yield {S.pct(r.get('fcf_yield'), 1)}"
    c["reasons"] = reasons
    return c


def etf_candidate(symbol: str) -> dict:
    name, sleeve = ETFS[symbol]
    return {"key": symbol, "ticker": symbol, "yahoo": symbol, "name": name, "source": "ETF", "sleeve": sleeve, "signal": "blue",
            "action": "Anchor", "price": None, "ccy": "USD", "buy_level": None, "flags": [], "value_text": "index / metal",
            "value_score": 0.5, "quality_score": 0.7, "quality_text": "diversified", "exit_rule": "rebalance", "reasons": [],
            "etf": True}


def merge(*groups) -> list[dict]:
    """One candidate per company: the first group to mention it wins (full files before screens)."""
    seen, out, ciks = set(), [], set()
    for group in groups:
        for c in group:
            k = c["key"].upper()
            duplicate = k in seen or (c.get("cik") and c["cik"] in ciks)
            seen.add(k)
            if c.get("cik"):   # recorded even for a duplicate, so its other share classes are dropped too
                ciks.add(c["cik"])
            if not duplicate:
                out.append(c)
    return out


# ------------------------------------------------------------------------------------------------- momentum and risk
def price_stats(closes: list[float]) -> dict | None:
    """200-day average, 6- and 12-month returns, 1-year volatility and worst fall, from daily closes (oldest first)."""
    if len(closes) < 130:
        return None
    px = np.array(closes, dtype=float)
    last = px[-1]
    sma = px[-200:].mean()
    year = px[-252:]
    rets = np.diff(np.log(year))
    peak = np.maximum.accumulate(year)
    return {"last": last, "sma200": sma, "vs_200": last / sma - 1, "r6": last / px[-126] - 1,
            "r12": last / px[-252] - 1 if len(px) >= 252 else None, "vol": float(rets.std() * math.sqrt(252)),
            "max_fall": float((year / peak - 1).min())}


def momentum(c: dict, st: dict | None):
    if not st:
        c.update(momentum_score=0.3, entry="third", momentum_text="no price history", vol=0.40)
        return
    full = st["vs_200"] >= -0.05 and st["r6"] > 0
    c.update(stats=st, vol=max(st["vol"], 0.02), entry="full" if full else "third",
             momentum_score=0.5 * clip((st["vs_200"] + 0.10) / 0.30) + 0.5 * clip((st["r6"] + 0.20) / 0.60),
             momentum_text=f"{S.pct(st['vs_200'])} vs 200-day · 6 m {S.pct(st['r6'])}")
    if c.get("etf"):
        c["entry"] = "full"


def score(c: dict, weights: dict) -> float:
    return weights["value"] * c["value_score"] + weights["quality"] * c["quality_score"] + weights["momentum"] * c["momentum_score"]


# ------------------------------------------------------------------------------------------------- building the portfolio
def build(candidates: list[dict], profile: str = "balanced") -> dict:
    """Picks and sizes the holdings for a profile. The candidates are not changed (they can feed several profiles).
    Returns {"holdings", "next", "excluded", "sleeves", "waiting", "profile"}."""
    p = PROFILES[profile]
    cap = p["max_weight"]
    candidates = [dict(c, score=score(c, p["weights"])) for c in candidates]
    eligible = [c for c in candidates if not c["reasons"] and not c.get("etf")]
    etfs = {c["ticker"]: c for c in candidates if c.get("etf")}
    holdings, sleeves = [], {}
    for key, (target, count, etf) in p["sleeves"].items():
        label = SLEEVE_NAMES[key]
        picks = sorted((c for c in eligible if c["sleeve"] == key), key=lambda c: -c["score"])[:count]
        inv = {c["key"]: 1 / c["vol"] for c in picks}
        total_inv = sum(inv.values()) or 1
        # a sleeve with fewer than half its names is part ETF: each pick keeps an equal share at most
        share = min(1.0, len(picks) / count) if picks else 0.0
        stock_budget = target * share
        weights = {k: stock_budget * v / total_inv for k, v in inv.items()}
        for _ in range(5):   # at most `cap` per name, spreading the excess to the uncapped names
            over = {k: w - cap for k, w in weights.items() if w > cap}
            if not over:
                break
            under = [k for k, w in weights.items() if w < cap]
            for k in over:
                weights[k] = cap
            spare = sum(over.values())
            if not under:
                break
            base = sum(inv[k] for k in under)
            for k in under:
                weights[k] += spare * inv[k] / base
        etf_weight = target - sum(weights.values())
        for c in picks:
            c["target_weight"] = weights[c["key"]]
            c["weight"] = weights[c["key"]] if c["entry"] == "full" else weights[c["key"]] / 3
            holdings.append(c)
        if etf_weight > 0.0049 and etf in etfs:
            e = dict(etfs[etf], target_weight=etf_weight, weight=etf_weight, why_etf="fills the sleeve: too few names passed")
            holdings.append(e)
        sleeves[key] = {"label": label, "target": target, "names": len(picks)}
    waiting = sum(c["target_weight"] - c["weight"] for c in holdings)
    for symbol, w in p["defensive"].items():
        w += waiting if symbol == "SGOV" else 0
        if symbol in etfs:
            holdings.append(dict(etfs[symbol], target_weight=w, weight=w,
                                 why_etf="defensive" + (f" – includes {S.pct(waiting, 1, signed=False)} waiting for the rest of the 'thirds'"
                                                        if symbol == "SGOV" and waiting > 0 else "")))
    sleeves["defensive"] = {"label": "Defensive", "target": sum(p["defensive"].values()), "names": len(p["defensive"])}
    chosen = {c["key"] for c in holdings}
    nxt = sorted((c for c in eligible if c["key"] not in chosen), key=lambda c: -c["score"])[:12]
    excluded = {}
    for c in candidates:
        for reason in c["reasons"][:1]:
            excluded[reason.split(" (")[0]] = excluded.get(reason.split(" (")[0], 0) + 1
    return {"holdings": holdings, "next": nxt, "excluded": excluded, "sleeves": sleeves, "waiting": waiting, "profile": profile}


def portfolio_risk(holdings: list[dict], closes_by_key: dict) -> dict:
    """Past-year volatility and worst fall of today's mix (backward-looking: what this mix would have done)."""
    series = []
    for c in holdings:
        px = closes_by_key.get(c["key"])
        if px is None or len(px) < 253:
            continue
        r = np.diff(np.log(np.array(px[-253:], dtype=float)))
        series.append((c["weight"], r))
    if not series:
        return {}
    total = sum(w for w, _ in series)
    daily = sum(w / total * r for w, r in series)
    curve = np.exp(np.cumsum(daily))
    return {"vol": float(daily.std() * math.sqrt(252)), "max_fall": float((curve / np.maximum.accumulate(curve) - 1).min()),
            "return_1y": float(curve[-1] - 1), "covered": total}


# ------------------------------------------------------------------------------------------------- report
SOURCE_LINK = {"miners list": "miners.html", "core list": "core.html", "oil list": "oil.html", "tech list": "tech.html", "US screen": "us-screen.html",
               "miners screen": "miners-screen.html"}


def _e(x):
    return html.escape(str(x), quote=True)


def _row(i, c):
    link = SOURCE_LINK.get(c["source"])
    anchor = f"#c-{c['anchor']}" if c.get("anchor") else ""
    src = f'<a href="{link}{anchor}">{_e(c["source"])}</a>' if link else _e(c["source"])
    st = c.get("stats") or {}
    entry = ('<span class="pill green">Full</span>' if c.get("entry") == "full" else
             '<span class="pill blue">Start a third</span>')
    flags = " ".join(f"[{_e(f)}]" for f in c.get("flags", []))
    why = c.get("why_etf") or " · ".join(x for x in (c["value_text"], c.get("quality_text")) if x)
    buy = "–" if not c.get("buy_level") else f"≤ {c['buy_level']:,.2f}"
    m = c.get("mcap")
    mcap = "–" if not m else f"${m:,.0f}bn" if m >= 10 else f"${m:,.1f}bn"
    return f"""<tr data-sleeve="{c['sleeve']}">
<td>{i}</td><td><a href="https://finance.yahoo.com/quote/{_e(c['yahoo'])}" target="_blank" rel="noopener"><b>{_e(c['ticker'])}</b></a><br><small>{_e(c['name'])}</small>{f'<br><span class="flags">{flags}</span>' if flags else ''}</td>
<td>{_e(SLEEVE_NAMES[c['sleeve']])}</td><td class="r">{mcap}</td><td class="r"><b>{c['weight']*100:.1f}%</b>{f"<br><small>target {c['target_weight']*100:.1f}%</small>" if abs(c['target_weight'] - c['weight']) > 1e-6 else ''}</td>
<td>{entry}</td><td>{_e(why)}</td><td>{_e(c.get('momentum_text', '–'))}</td>
<td class="r">{'–' if not st else S.pct(st['vol'], 0, signed=False)}</td><td class="r">{'–' if not st else S.pct(st['max_fall'])}</td>
<td class="r">{c['score']:.2f}</td><td>{buy}</td><td>{_e(c.get('exit_rule', ''))}</td><td>{src}</td></tr>"""


def report(result: dict, risk: dict, path: Path, as_of: dt.date, notes: list[str]):
    from .html_report import CSS as BASE_CSS  # noqa: PLC0415
    h, p = result["holdings"], PROFILES[result["profile"]]
    w = p["weights"]
    sleeve_mix = " · ".join(f"{SLEEVE_NAMES[k].lower()} {v[0]*100:.0f}%" for k, v in p["sleeves"].items())
    full = sum(c["weight"] for c in h if c.get("entry") == "full" and not c.get("etf"))
    thirds = sum(1 for c in h if c.get("entry") == "third")
    sleeve_rows = "".join(
        f"<tr><td>{_e(v['label'])}</td><td class='r'>{v['target']*100:.0f}%</td>"
        f"<td class='r'>{sum(c['weight'] for c in h if c['sleeve'] == k)*100:.1f}%</td><td class='r'>{v['names']}</td></tr>"
        for k, v in result["sleeves"].items())
    nxt = "".join(f"<li><b>{_e(c['ticker'])}</b> ({_e(SLEEVE_NAMES[c['sleeve']])}, score {c['score']:.2f}) – {_e(c['value_text'])}</li>"
                  for c in result["next"])
    excluded = " · ".join(f"{_e(k)}: {v}" for k, v in sorted(result["excluded"].items(), key=lambda x: -x[1]))
    cards = [("Positions", f"{len(h)}", f"{thirds} starting with a third"), ("In stocks now", S.pct(full, 0, signed=False), "of the portfolio, full positions"),
             ("Waiting in T-bills", S.pct(result["waiting"], 1, signed=False), "for the rest of the 'thirds'")]
    if risk:
        cards += [("Past-year volatility", S.pct(risk["vol"], 0, signed=False), "of today's mix, backward-looking"),
                  ("Worst fall in the past year", S.pct(risk["max_fall"]), "today's mix, backward-looking")]
    cards_html = "".join(f'<div class="card" style="border-top-color:{S.SIGNAL["blue"]}"><div class="lbl">{_e(a)}</div>'
                         f'<div class="val">{_e(b)}</div><div class="cap">{_e(c)}</div></div>' for a, b, c in cards)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(p['title'].split(' – ')[0] + ' ' + result['profile'])}</title><style>{BASE_CSS}
main{{max-width:1500px}} .r{{text-align:right}} .flags{{font-size:11px;color:var(--muted)}}
table.mp{{border-collapse:collapse;width:100%;font-size:13px}} table.mp th{{text-align:left;background:var(--soft);color:var(--ink2);padding:7px 8px;
border-bottom:1px solid var(--ink2);font-size:12px}} table.mp td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:middle}}
tr[data-sleeve=us] td:first-child{{box-shadow:inset 3px 0 var(--blue)}} tr[data-sleeve=mining] td:first-child{{box-shadow:inset 3px 0 #B7791F}}
tr[data-sleeve=energy] td:first-child{{box-shadow:inset 3px 0 var(--red)}} tr[data-sleeve=uranium] td:first-child{{box-shadow:inset 3px 0 var(--green)}}
tr[data-sleeve=defensive] td:first-child{{box-shadow:inset 3px 0 var(--muted)}}
table.sl{{border-collapse:collapse;font-size:13px;margin:6px 0 14px}} table.sl td,table.sl th{{padding:4px 12px;border-bottom:1px solid var(--line)}}</style>
</head><body><main>
<h1>{_e(p['title'])}</h1>
<p class="sub">{len(h)} positions across {len(result['sleeves'])} sleeves · built {as_of:%d %b %Y} from today's reports · educational framework, not investment advice</p>
<div class="cards">{cards_html}</div>
<p class="method"><b>{_e(p['blurb'])}</b> Sleeves: {_e(sleeve_mix)} · defensive {result['sleeves']['defensive']['target']*100:.0f}% (gold, T-bills).</p>
<p class="method"><b>How it is built.</b> Every holding needs a <b>margin of safety</b> on its own model (producers at least 20% below the
12x value or tier A at or below 15x; growth stocks needing at most 5–8% a year), <b>quality</b> (no stale or flagged data, AISC ≤ 60% of
spot, debt ≤ 3× EBITDA, no heavy dilution, cash conversion ≥ 70%, grade not D; no developers, explorers or tier-C juniors) and is
scored {w['value']*100:.0f}% value, {w['quality']*100:.0f}% quality, {w['momentum']*100:.0f}% momentum. <b>Momentum</b> decides how much to buy now: at or above 95% of the 200-day average with a
positive 6-month return = full position, otherwise <b>start a third</b> and keep the rest in T-bills. Weights within a sleeve follow
inverse volatility, at most {p['max_weight']*100:.0f}% per name; a sleeve without enough qualifying names is filled with its ETF. Rebalance monthly, or when a
holding's signal turns red.</p>
<h3>Sleeves</h3><table class="sl"><tr><th>Sleeve</th><th>Target</th><th>Now</th><th>Names</th></tr>{sleeve_rows}</table>
<h3>Holdings</h3><div class="wrap"><table class="mp"><tr><th>#</th><th>Holding</th><th>Sleeve</th><th>Market value</th><th>Weight</th><th>Entry</th>
<th>Why (value · quality)</th><th>Momentum</th><th>Volatility</th><th>Worst fall 1 yr</th><th>Score</th><th>Buy at or below</th><th>Exit</th><th>From</th></tr>
{''.join(_row(i, c) for i, c in enumerate(h, 1))}</table></div>
<h3>Next in line</h3><ul class="small">{nxt or '<li>none</li>'}</ul>
<h3>Left out</h3><p class="small">{excluded}</p>
<ul class="small">{''.join(f'<li>{_e(n)}</li>' for n in notes)}</ul>
<footer>Volatility and worst fall use the past year's daily closes and describe what today's mix would have done – not a forecast.
Prices in each listing's currency. Educational framework, not investment advice.</footer>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
