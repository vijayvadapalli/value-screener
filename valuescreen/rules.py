"""Zones, signals (green / blue / red), buy levels, [flags] and the stale-data check – the Valuation Playbook's rules.

zone() returns, for one valued company: zone (BUY / WATCH / HOLD / SELL and variants), margin_of_safety, buy_level
(and add_level for tier A), put_level / call_level, signal, signal_caps, flags and a short action text.
"""
from __future__ import annotations

GREEN, BLUE, RED = "green", "blue", "red"
NO_LEVELS = dict(margin_of_safety=None, put_level=None, call_level=None, buy_level=None, add_level=None)
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


# ------------------------------------------------------------------------------------------------- zones per model
def _producer_zone(r, z):
    """Tier A: start at or below 15x, add at or below 12x. Others: BUY with a 20% margin at 12x. AISC ≤ 60% of spot."""
    price = r["price"]
    if r["oe"] <= 0:
        return dict(zone="NO EARNINGS", **NO_LEVELS)
    mos = 1 - price / r["v_low"] if r["v_low"] > 0 else -9.99
    cost_ok = r.get("cost_ratio") is None or r["cost_ratio"] <= z["max_cost_ratio"]
    out = dict(margin_of_safety=mos, put_level=max(r["v_low"], 0.0), call_level=r["v_sell"])
    if r.get("tier") == "A":
        out.update(buy_level=r["v_high"], add_level=r["v_low"])
        if price <= r["v_high"]:
            zn = ("BUY (add)" if price <= r["v_low"] else "BUY (start)") if cost_ok else "WATCH (high cost)"
        else:
            zn = "SELL" if price >= r["v_sell"] else "HOLD"
    else:
        out.update(buy_level=(1 - z["buy_margin_of_safety"]) * r["v_low"], add_level=None)
        if mos >= z["buy_margin_of_safety"]:
            zn = "BUY" if cost_ok else "WATCH (high cost)"
        elif mos >= 0:
            zn = "WATCH"
        else:
            zn = "SELL" if price >= r["v_sell"] else "HOLD"
    return dict(out, zone=zn)


def _nav_zone(r, buy, sell):
    """Developers, physical holders and the lease model: price ÷ NAV (or ÷ the cautious value)."""
    p = r["pnav"]
    if p is None or r["nav"] <= 0:
        return dict(zone="NO VALUE", **NO_LEVELS)
    zn = "BUY" if p <= buy else "WATCH" if p <= 1.0 else "SELL" if p >= sell else "HOLD"
    return dict(zone=zn, margin_of_safety=1 - p, put_level=buy * r["nav"], call_level=sell * r["nav"],
                buy_level=buy * r["nav"], add_level=None)


def _growth_zone(r, z):
    g = r["implied_growth"]
    if g is None:
        zn = "NO EARNINGS"
    else:
        zn = "BUY" if g <= r["growth_buy"] else "WATCH" if g <= z["growth_watch"] else "SELL" if g >= z["growth_sell"] else "HOLD"
    return dict(zone=zn, margin_of_safety=1 - r["price"] / r["v0"] if r["v0"] > 0 else None,
                put_level=r["v_buy"], call_level=r["v_sell"], buy_level=r["v_buy"], add_level=None)


def zone(r, c, cfg):
    z, m = cfg["zones"], c["model"]
    if m in ("producer", "cashflow"):
        out = _producer_zone(r, z)
    elif m == "physical":
        out = _nav_zone(r, z["physical_buy_pnav"], z["physical_sell_pnav"])
    elif m in ("developer", "leases"):
        out = _nav_zone(r, z["developer_buy_pnav"], z["developer_sell_pnav"])
    elif m == "liquid":
        out = dict(zone="NOT VALUED", **NO_LEVELS)
    else:
        out = _growth_zone(r, z)
    for level in ("buy_level", "add_level"):   # heavy net debt can push a level below zero, which means no buy level
        if out.get(level) is not None and out[level] <= 0:
            out[level] = None
    if r.get("stale"):
        out["zone"] = "STALE (would be BUY)" if out["zone"].startswith("BUY") else out["zone"] + " · stale"
    if r.get("cyclical") and out["zone"].startswith(("BUY", "WATCH")):
        out["zone"] += " · cyclical: check the cycle"
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


def signal(r, cfg):
    """(colour, caps): green = buy / start, blue = watch / hold, red = expensive or no valid value.
    A cheap cyclical, cash conversion below 70%, or a lender showing bad-loan warning signs is capped at blue."""
    zn = r["zone"]
    if zn.startswith(("SELL", "NO EARNINGS", "NO VALUE", "NOT VALUED")):
        return RED, []
    if not zn.startswith("BUY"):
        return BLUE, []
    caps = ((["cyclical"] if _is_cyclical(r) else []) + (["cash conversion"] if _low_cash_conversion(r, cfg) else [])
            + (["bad loans"] if _bad_loan_flags(r) else []))
    return (BLUE if caps else GREEN), caps


def flags(r, cfg):
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
    if "high cost" in r["zone"]:
        out.append("AISC > 60% of spot")
    v2 = r.get("v2") or {}
    if v2.get("one_offs"):
        out.append("one-off quarter removed")
    out += [FLAG_TEXT.get(f, f) for f in v2.get("flags", [])]
    if r.get("nav_extrapolated"):
        out.append("NAV beyond study prices")
    return out + list(r.get("flags_file", []))


def action_text(r):
    zn, sig = r["zone"], r["signal"]
    if zn.startswith("NOT VALUED"):
        return "No value – don't add"
    if zn.startswith(("NO EARNINGS", "NO VALUE")):
        return "No valid value"
    if zn.startswith("STALE"):
        return "Would be buy – refresh data"
    if sig == GREEN:
        return {"BUY (add)": "Buy – add (≤ 12x)", "BUY (start)": "Buy – start (≤ 15x)"}.get(zn.split(" ·")[0], "Buy")
    if sig == RED:
        return "Expensive – don't add"
    if r.get("signal_caps"):
        return "Watch – capped at blue"
    if r.get("tier") == "A" and zn.startswith("HOLD"):
        return "Watch – above 15x"
    return "Watch / hold"
