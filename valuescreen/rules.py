"""Zones, stale-data check and option levels."""
from __future__ import annotations


def stale_check(c, cfg):
    as_of = cfg["as_of"]
    model = c["model"]
    limit = cfg["stale_days"].get(model, cfg["stale_days"]["default"])
    age = (as_of - c["period"]["end"]).days
    reasons = []
    if age > limit:
        reasons.append(f"results are {age} days old (limit {limit})")
    nxt = c["period"].get("next_report")
    if nxt and nxt < as_of:
        reasons.append(f"newer results were due {nxt.isoformat()} - refresh the file")
    elif nxt and nxt == as_of:
        reasons.append("new results due today")
    price_age = (as_of - c["price"]["date"]).days
    return dict(stale=bool(reasons), stale_reason="; ".join(reasons), period_age_days=age, price_age_days=price_age)


def zone(r, c, cfg):
    z = cfg["zones"]
    m = c["model"]
    out = {}
    price = r["price"]
    if m in ("producer", "cashflow"):
        if r["oe"] <= 0:
            out.update(zone="NO EARNINGS", margin_of_safety=None)
        else:
            mos = 1 - price / r["v_low"] if r["v_low"] > 0 else -9.99
            cost_ok = r.get("cost_ratio") is None or r["cost_ratio"] <= z["max_cost_ratio"]
            if mos >= z["buy_margin_of_safety"] and cost_ok:
                zn = "BUY"
            elif mos >= z["buy_margin_of_safety"]:
                zn = "WATCH (high cost)"
            elif mos >= 0:
                zn = "WATCH"
            elif price >= r["v_sell"]:
                zn = "SELL"
            else:
                zn = "HOLD"
            out.update(zone=zn, margin_of_safety=mos, put_level=max(r["v_low"], 0.0), call_level=r["v_sell"])
    elif m in ("developer", "physical"):
        buy, sell = (z["developer_buy_pnav"], z["developer_sell_pnav"]) if m == "developer" else (z["physical_buy_pnav"], z["physical_sell_pnav"])
        p = r["pnav"]
        zn = "BUY" if p <= buy else "WATCH" if p <= 1.0 else "SELL" if p >= sell else "HOLD"
        out.update(zone=zn, margin_of_safety=1 - p, put_level=buy * r["nav"], call_level=sell * r["nav"])
    else:  # growth
        g = r["implied_growth"]
        if g is None:
            zn = "NO EARNINGS"
        else:
            zn = "BUY" if g <= z["growth_buy"] else "WATCH" if g <= z["growth_watch"] else "SELL" if g >= z["growth_sell"] else "HOLD"
        out.update(zone=zn, margin_of_safety=1 - price / r["v0"] if r["v0"] > 0 else None,
                   put_level=r["v_buy"], call_level=r["v_sell"])
    if r.get("stale"):
        if out["zone"] == "BUY":
            out["zone"] = "STALE (would be BUY)"
        else:
            out["zone"] = out["zone"] + " · stale"
    if r.get("cyclical") and out["zone"].startswith(("BUY", "WATCH")):
        out["zone"] += " · cyclical: check the cycle"
    return out
