"""The screening rules, one copy shared by the full valuation (engine, v2, rules) and the quick screens (US, miners).

    earnings_basis(kind, ttm, ...)    → (eps, basis, normal_eps): the EPS a growth company is valued on
    growth_band(g, buy, zones)        → "BUY" | "WATCH" | "HOLD" | "SELL" | "NO EARNINGS"
    multiple_band(price, eps, cautious, sell, buy_margin) → the same bands for value at 12x / 25x (tiers B and C, miners)
    caps(cyclical, low_cash, bad_loans) → the reasons a cheap company is held at blue
    colour(band, caps)                → "green" | "blue" | "red"

Each caller words the bands its own way (BUY / "Cheap", HOLD / "Fair"); the thresholds and the colours live here only.
"""
from __future__ import annotations

GREEN, BLUE, RED = "green", "blue", "red"
RED_BANDS = ("SELL", "NO EARNINGS", "NO VALUE", "NOT VALUED")

# how earnings_basis arrived at the EPS
CYCLICAL, HISTORY_BREAK, FINANCIAL, TWELVE_MONTHS = "cyclical", "history break", "financial", "12-month"


def earnings_basis(kind: str, ttm: float | None, avg5: float | None = None, book: float | None = None,
                   roe: float | None = None, bad_loans: float = 0.0, history_break: str | None = None):
    """The Valuation Playbook's earnings rule. Returns (eps, basis, normal_eps):
    - cyclical: the average of the 12-month EPS and the 5-year average – unless the history is not comparable
      (a demerger), then the 12-month EPS alone;
    - financial: the average of the 12-month EPS and (book − bad loans not provided for) × 5-year ROE (= normal_eps);
    - otherwise the 12-month EPS. No 12-month EPS → (None, "12-month", None)."""
    if ttm is None:
        return None, TWELVE_MONTHS, None
    if kind == "cyclical" and history_break:
        return ttm, HISTORY_BREAK, None
    if kind == "cyclical" and avg5 is not None:
        return (ttm + avg5) / 2, CYCLICAL, None
    if kind == "financial" and book and roe is not None:
        normal = (book - (bad_loans or 0.0)) * roe
        return (ttm + normal) / 2, FINANCIAL, normal
    return ttm, TWELVE_MONTHS, None


def growth_band(g: float | None, buy: float, zones: dict) -> str:
    """Growth the price needs: BUY at or below `buy` (5%, or 10% for tier A), WATCH up to growth_watch, SELL at or above
    growth_sell, HOLD in between; no positive earnings → NO EARNINGS."""
    if g is None:
        return "NO EARNINGS"
    if g <= buy:
        return "BUY"
    if g <= zones["growth_watch"]:
        return "WATCH"
    return "SELL" if g >= zones["growth_sell"] else "HOLD"


def multiple_band(price: float, eps: float, cautious: float, sell: float, buy_margin: float = 0.20) -> str:
    """Value on earnings multiples: BUY with at least `buy_margin` below the cautious value (12x; 10x for oil), WATCH up
    to the cautious value, SELL at or above the sell value (25x), HOLD in between; no positive earnings → NO EARNINGS."""
    if eps <= 0:
        return "NO EARNINGS"
    margin = 1 - price / cautious if cautious > 0 else None
    if margin is not None and margin >= buy_margin:
        return "BUY"
    if margin is not None and margin >= 0:
        return "WATCH"
    return "SELL" if price >= sell else "HOLD"


def caps(cyclical: bool, low_cash: bool, bad_loans: bool) -> list[str]:
    """Why a cheap company is held at blue: a cyclical (cheap at the top of the cycle), cash conversion below 70%,
    or a lender showing bad-loan warning signs."""
    return (["cyclical"] if cyclical else []) + (["cash conversion"] if low_cash else []) + (["bad loans"] if bad_loans else [])


def colour(band: str, caps_: list[str] = ()) -> str:
    """green = buy (unless capped, then blue), red = expensive or no valid value, blue = everything in between."""
    if band in RED_BANDS:
        return RED
    if band == "BUY":
        return BLUE if caps_ else GREEN
    return BLUE
