"""A US company's figures from its SEC facts: quarters, the last twelve months, yearly history and the balance sheet.

Adapted from valuation-models/valmodels/edgar.py. 10-Qs report cash flow year to date, so single quarters are worked
out by subtraction, and Q4 = the year − nine months (or − the three quarters, when no nine-month figure was filed). Companies change tags over time; for each figure the tag with the
most recent data wins. Money in US$ (full units); per-share figures as filed (before later splits).

    summarize(facts) → {"ttm": {...}, "ttm_end", "ttm_complete", "annual": {fy_end: {...}}, "balance": {...},
                        "shares", "shares_date", "latest_filed", "latest_form"}
"""
from __future__ import annotations

import datetime as dt

FLOW_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"],
    "d_and_a": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization",
                "Depreciation"],
}
INSTANT_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "st_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "debt_total": ["LongTermDebt", "DebtInstrumentCarryingAmount", "LongTermDebtAndCapitalLeaseObligations"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "short_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
SHARE_TAGS = {"dei": ["EntityCommonStockSharesOutstanding"], "us-gaap": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                                                                         "CommonStockSharesOutstanding"]}


def wanted_tags() -> dict:
    """{namespace: {tags}} to keep in the database."""
    gaap = {t for names in list(FLOW_TAGS.values()) + list(INSTANT_TAGS.values()) for t in names} | set(EPS_TAGS)
    return {"us-gaap": gaap | set(SHARE_TAGS["us-gaap"]), "dei": set(SHARE_TAGS["dei"])}


def _d(s):
    return dt.date.fromisoformat(s)


def _entries(facts, tag, unit="USD", ns="us-gaap"):
    """{(start, end): fact} for durations or {end: fact} for instants; the latest filing wins on duplicates."""
    out = {}
    for f in facts.get("facts", {}).get(ns, {}).get(tag, {}).get("units", {}).get(unit, []):
        key = (f.get("start"), f["end"]) if f.get("start") else f["end"]
        if key not in out or (f.get("filed") or "") > (out[key].get("filed") or ""):
            out[key] = f
    return out


def _quarters(entries):
    """{quarter end: value} from a mix of 3-month, year-to-date and full-year facts."""
    q, by_start = {}, {}
    for key, f in entries.items():
        if not isinstance(key, tuple) or key[0] is None:
            continue
        s, e = key
        if 80 <= (_d(e) - _d(s)).days <= 100:
            q[_d(e)] = f["val"]
        by_start.setdefault(s, []).append((_d(e), f["val"]))
    for lst in by_start.values():
        lst.sort()
        for (e0, v0), (e1, v1) in zip(lst, lst[1:]):
            if 80 <= (e1 - e0).days <= 100 and e1 not in q:
                q[e1] = v1 - v0
    # a year with three known quarters but no nine-month figure: Q4 = the year − those three quarters
    for key, f in entries.items():
        if isinstance(key, tuple) and key[0] and 350 <= (_d(key[1]) - _d(key[0])).days <= 380 and _d(key[1]) not in q:
            start, end = _d(key[0]), _d(key[1])
            inside = [v for e, v in q.items() if start < e < end]
            if len(inside) == 3:
                q[end] = f["val"] - sum(inside)
    return dict(sorted(q.items()))


def _years(entries):
    """{year end: value} from full-year (350–380 day) facts."""
    out = {}
    for key, f in entries.items():
        if isinstance(key, tuple) and key[0] and 350 <= (_d(key[1]) - _d(key[0])).days <= 380:
            out[_d(key[1])] = f["val"]
    return dict(sorted(out.items()))


def _best(facts, names, fn, unit="USD", ns="us-gaap"):
    """The series (by `fn`) of the tag whose data is most recent."""
    best = {}
    for t in names:
        s = fn(_entries(facts, t, unit, ns))
        if s and (not best or max(s) > max(best)):
            best = s
    return best


def _latest_instant(facts, names, unit="USD", ns="us-gaap"):
    best = None
    for t in names:
        e = {k: f for k, f in _entries(facts, t, unit, ns).items() if not isinstance(k, tuple)}
        if e:
            end = max(e)
            if best is None or end > best[0]:
                best = (end, e[end]["val"])
    return best


def _instant_on(facts, names, day: dt.date, unit="USD"):
    """The instant value at `day` (a year end) for the first tag that has one."""
    for t in names:
        for k, f in _entries(facts, t, unit).items():
            if not isinstance(k, tuple) and _d(k) == day:
                return f["val"]
    return None


RECENT_DAYS = 200   # figures older than this, against today, are not used (the company falls back to Yahoo)


def shares_outstanding(facts, as_of: dt.date | None = None):
    """(date, shares). The cover-page count from the latest filing, adding up every share class it lists (Mastercard and
    Fox report one figure per class) – if it is recent; many companies stopped tagging it years ago. Otherwise the latest
    quarter's diluted weighted average. None if neither is recent."""
    as_of = as_of or dt.date.today()
    recent = lambda end: (as_of - _d(end)).days <= RECENT_DAYS  # noqa: E731
    cover = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if cover:
        latest = max(cover, key=lambda f: ((f.get("filed") or ""), f["end"]))
        same = [f for f in cover if f.get("accn") == latest.get("accn") and f["end"] == latest["end"]]
        total = sum(f["val"] for f in same)
        if recent(latest["end"]) and total > 0:
            return latest["end"], total
    weighted = [f for f in facts.get("facts", {}).get("us-gaap", {}).get(SHARE_TAGS["us-gaap"][0], {}).get("units", {}).get("shares", [])
                if f.get("start") and 80 <= (_d(f["end"]) - _d(f["start"])).days <= 100]
    if weighted:
        latest = max(weighted, key=lambda f: (f["end"], f.get("filed") or ""))
        if recent(latest["end"]):
            return latest["end"], latest["val"]
    return None


def problem(s: dict, as_of: dt.date | None = None) -> str | None:
    """Why a company's SEC figures should not be used (it then falls back to Yahoo), or None if they are fine."""
    as_of = as_of or dt.date.today()
    if s["ttm"].get("net_income") is None:
        return "no recent net income in the SEC data"
    if not s["ttm_end"] or (as_of - s["ttm_end"]).days > RECENT_DAYS:
        return f"SEC figures end {s['ttm_end']}"
    if not s["shares"]:
        return "no recent share count in the SEC data"
    return None


def summarize(facts: dict, as_of: dt.date | None = None) -> dict:
    quarters = {k: _best(facts, names, _quarters) for k, names in FLOW_TAGS.items()}
    years = {k: _best(facts, names, _years) for k, names in FLOW_TAGS.items()}
    years["eps"] = _best(facts, EPS_TAGS, _years, unit="USD/shares")
    window = quarters["net_income"] or quarters["revenue"]   # the twelve months follow the figure that is valued
    ends = sorted(window)[-4:]
    complete = len(ends) == 4 and all(80 <= (b - a).days <= 100 for a, b in zip(ends, ends[1:]))
    ttm = {}
    if complete:
        for k, q in quarters.items():
            ttm[k] = sum(q[e] for e in ends) if all(e in q for e in ends) else None
        ttm_end = ends[-1]
    else:   # fall back to the latest full year
        last = max((max(y) for y in years.values() if y), default=None)
        ttm = {k: y.get(last) for k, y in years.items() if k != "eps"}
        ttm_end = last
    bal = {k: v for k, v in ((k, _latest_instant(facts, names)) for k, names in INSTANT_TAGS.items()) if v}
    debt = bal["debt_total"][1] if "debt_total" in bal else (bal.get("debt_noncurrent", (0, 0))[1] + bal.get("debt_current", (0, 0))[1])
    debt += bal.get("short_borrowings", (0, 0))[1]
    shares = shares_outstanding(facts, as_of)
    annual_equity = {y: _instant_on(facts, INSTANT_TAGS["equity"], y) for y in years["net_income"]}
    annual_shares = _best(facts, SHARE_TAGS["us-gaap"][:1], _years, unit="shares")
    filed = [f.get("filed") for ns in facts.get("facts", {}).values() for t in ns.values() for u in t.get("units", {}).values()
             for f in u if f.get("filed")]
    return {
        "ttm": ttm, "ttm_end": ttm_end, "ttm_complete": complete,
        "annual": {y: {**{k: years[k].get(y) for k in years}, "equity": annual_equity.get(y), "shares": annual_shares.get(y)}
                   for y in sorted(years["net_income"])[-10:]},
        "balance": {"cash_and_st": bal.get("cash", (0, 0))[1] + bal.get("st_investments", (0, 0))[1], "debt": debt,
                    "equity": bal.get("equity", (None, None))[1], "date": max((v[0] for v in bal.values()), default=None)},
        "shares": shares[1] if shares else None, "shares_date": shares[0] if shares else None,
        "latest_filed": max(filed) if filed else None,
    }
