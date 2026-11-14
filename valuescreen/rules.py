"""Zones, signals (green / blue / red), buy levels, [flags] and the stale-data check – the Valuation Playbook's rules.

zone() returns, for one valued company: zone (BUY / WATCH / HOLD / SELL and variants), margin_of_safety, buy_level
(and add_level for tier A), put_level / call_level, signal, signal_caps, flags and a short action text.
"""
from __future__ import annotations

from . import kinds, screening
from .types import Result

GREEN, BLUE, RED = screening.GREEN, screening.BLUE, screening.RED
FLAG_TEXT = {"conglomerate": "conglomerate / finance arm", "insurer": "insurer: earnings a weak guide"}


MAX_WAIT_DAYS = 400   # longest a file can wait for its next report (annual reporters)


def stale_check(c, cfg):
    as_of = cfg["as_of"]
    limit = cfg["stale_days"].get(c["model"], cfg["stale_days"]["default"])
    age = (as_of - c["period"]["end"]).days
    reasons = []
    nxt = c["period"].get("next_report")
    # old results are only stale once newer ones exist: with the next report still ahead (half-yearly and annual
    # reporters, or a quarter not yet out), the file stays current for up to MAX_WAIT_DAYS
    waiting = bool(nxt and nxt > as_of and age <= MAX_WAIT_DAYS)
    if age > limit and not waiting:
        reasons.append(f"results are {age} days old (limit {limit})")
    if nxt and nxt < as_of:
        reasons.append(f"newer results were due {nxt.isoformat()} - refresh the file")
    elif nxt and nxt == as_of:
        reasons.append("new results due today")
    return dict(stale=bool(reasons), stale_reason="; ".join(reasons), period_age_days=age,
                price_age_days=(as_of - c["price"]["date"]).days)


# ------------------------------------------------------------------------------------------------- zones
# Each model gives its band (BUY / WATCH / HOLD / SELL / NO EARNINGS / NO VALUE / NOT VALUED) with its details –
# buy_step ("add" / "start", tier A) and high_cost (a buy held back by AISC above 60% of spot) – and the levels
# (kinds/<model>.py). The zone text the reports show is written from these by zone_text(); signal and action are
# decided on the fields, not the text.
def zone_text(band, buy_step=None, high_cost=False, stale=False, cyclical=False):
    """The zone as the reports and the signals log show it, e.g. "BUY (add)", "WATCH (high cost)", "HOLD · stale",
    "STALE (would be BUY)", "WATCH · cyclical: check the cycle"."""
    if stale and band == "BUY":
        return "STALE (would be BUY)"
    text = f"BUY ({buy_step})" if band == "BUY" and buy_step else "WATCH (high cost)" if high_cost else band
    if stale:
        text += " · stale"
    if cyclical and band in ("BUY", "WATCH"):
        text += " · cyclical: check the cycle"
    return text


def zone(r: Result, c: dict, cfg: dict) -> dict:
    out = kinds.of(c["model"]).zone(r, cfg["zones"])
    out.setdefault("buy_step", None)
    out.setdefault("high_cost", False)
    for level in ("buy_level", "add_level"):   # heavy net debt can push a level below zero, which means no buy level
        if out.get(level) is not None and out[level] <= 0:
            out[level] = None
    out["zone"] = zone_text(out["band"], out["buy_step"], out["high_cost"], bool(r.get("stale")), bool(r.get("cyclical")))
    full = {**r, **out}
    out["signal"], out["signal_caps"] = signal(full, cfg)
    out["flags"] = flags(full, cfg)
    out["action"] = action_text({**full, **out})
    return out


# ------------------------------------------------------------------------------------------------- signal, flags, action
def _is_cyclical(r):
    return bool(r.get("cyclical")) or (r.get("v2") or {}).get("kind") == "cyclical"


def _low_cash_conversion(r, cfg):
    cc = r.get("cash_conversion")
    return cc is not None and cc < cfg["zones"].get("min_cash_conversion", 0.70)


def _bad_loan_flags(r):
    return list((r.get("asset_quality") or {}).get("flags", []))


def _buyable(r):
    """In the buy band with current results – a stale buy waits for a refresh."""
    return r["band"] == "BUY" and not r.get("stale")


def signal(r: Result, cfg: dict) -> tuple[str, list[str]]:
    """(colour, caps): green = buy / start, blue = watch / hold, red = expensive or no valid value.
    A cheap cyclical, cash conversion below 70%, or a lender showing bad-loan warning signs is capped at blue."""
    if not _buyable(r):   # a stale buy is blue until the results are refreshed
        return (BLUE if r["band"] == "BUY" else screening.colour(r["band"])), []
    caps = screening.caps(_is_cyclical(r), _low_cash_conversion(r, cfg), bool(_bad_loan_flags(r)))
    return screening.colour("BUY", caps), caps


def flags(r: Result, cfg: dict) -> list[str]:
    """Short warnings for the comment column, shown in [brackets]."""
    out = ["STALE"] if r.get("stale") else []
    if r.get("price_undated"):
        out.append("undated price")
    elif (r.get("price_age_days") or 0) > cfg.get("price_stale_days", 7):
        out.append(f"price {r['price_age_days']} days old")
    if "intraday" in (r.get("price_note") or "").lower():
        out.append("intraday price")
    if _is_cyclical(r):
        out.append("cyclical")
    if _low_cash_conversion(r, cfg):
        out.append(f"cash conversion {r['cash_conversion']*100:.0f}%")
    out += _bad_loan_flags(r)
    if r.get("high_cost"):
        out.append("AISC > 60% of spot")
    v2 = r.get("v2") or {}
    if v2.get("one_offs"):
        out.append("one-off quarter removed")
    out += [FLAG_TEXT.get(f, f) for f in v2.get("flags", [])]
    if r.get("nav_extrapolated"):
        out.append("NAV beyond study prices")
    return out + list(r.get("flags_file", []))


def action_text(r: Result) -> str:
    band, sig = r["band"], r["signal"]
    if band == "NOT VALUED":
        return "No value – don't add"
    if band in ("NO EARNINGS", "NO VALUE"):
        return "No valid value"
    if band == "BUY" and r.get("stale"):
        return "Would be buy – refresh data"
    if sig == GREEN:
        return {"add": "Buy – add (≤ 12x)", "start": "Buy – start (≤ 15x)"}.get(r.get("buy_step"), "Buy")
    if sig == RED:
        return "Expensive – don't add"
    if r.get("signal_caps"):
        return "Watch – capped at blue"
    if r.get("tier") == "A" and band == "HOLD":
        return "Watch – above 15x"
    return "Watch / hold"
