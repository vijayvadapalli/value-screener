"""The shape of a valuation result – what models.value_company, rules.zone and engine.run put in the dict each company
gets. Typing only: nothing here runs, but an editor or type checker uses it to catch a mistyped key (r["v_lwo"]).

    Result = the fields every model has (identity, price, value, zone, signal) + each model's own fields, all optional
    in the type because a result carries only its own model's fields.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, List, Optional, Tuple, TypedDict


class Identity(TypedDict, total=False):
    ticker: str
    display_ticker: str
    name: str
    model: str                     # producer | cashflow | developer | physical | growth | leases | liquid
    sector: str
    currency: str                  # the company's reporting currency
    tier: Optional[str]            # A / B / C, or None
    cyclical: bool
    shade: Optional[str]           # market-value shade for the summary table
    market_value_usd_bn: Optional[float]


class PriceAndPeriod(TypedDict, total=False):
    price: float
    price_ccy: str
    price_date: dt.date
    price_source: str
    price_undated: bool
    price_note: str
    price_age_days: int
    period: str                    # e.g. "Q3 2026" or "TTM to Sep 2026"
    period_end: dt.date
    period_reported: Optional[dt.date]
    period_age_days: int
    stale: bool
    stale_reason: str


class Value(TypedDict, total=False):
    oe: Optional[float]            # owner earnings / EPS per share used (at today's metal prices)
    nc: Optional[float]            # net cash per share (negative = net debt)
    v_low: Optional[float]         # cautious value (12x, NAV, no-growth value)
    v_high: Optional[float]        # fair value (15x)
    exp: Optional[float]           # owner-earnings change per share for a 1-unit change in the metal price
    scenarios: List[Tuple[float, float]]
    coverage_lo: float             # value ÷ price
    coverage_hi: float


class Zone(TypedDict, total=False):
    band: str                      # BUY | WATCH | HOLD | SELL | NO EARNINGS | NO VALUE | NOT VALUED
    buy_step: Optional[str]        # "add" / "start" (tier A)
    high_cost: bool                # a buy held back by AISC above 60% of spot
    zone: str                      # the text shown, written from the fields above (rules.zone_text)
    margin_of_safety: Optional[float]
    buy_level: Optional[float]
    add_level: Optional[float]
    put_level: Optional[float]
    call_level: Optional[float]
    signal: str                    # green | blue | red
    signal_caps: List[str]         # why a cheap company is held at blue
    action: str
    flags: List[str]
    flags_file: List[str]
    comment: str
    assumptions: List[str]
    notes: List[str]
    sources: List[str]


class ProducerFields(TypedDict, total=False):
    oe_rep: float                  # owner earnings as reported, before re-pricing to spot
    mult_lo: int
    mult_hi: int
    sell_multiple: int
    v_sell: float
    pe: Optional[float]
    basis: str                     # which earnings block of the file was used
    primary_metal: str
    implied_metal_lo: float        # the metal price the share price assumes at 12x / 15x
    implied_metal_hi: float
    cost_ratio: float              # AISC ÷ spot
    terms: List[dict]              # per metal: realised, spot, delta, sens
    stress: List[Tuple[float, float, float]]
    projects: List[dict]
    fcf_ps: Optional[float]


class NavFields(TypedDict, total=False):
    nav: float
    pnav: float                    # price ÷ NAV
    nav_extrapolated: bool


class GrowthFields(TypedDict, total=False):
    v0: float                      # value with no growth
    v10: float
    v20: float
    v_buy: float
    implied_growth: Optional[float]
    growth_buy: float
    discount_rate: float
    no_growth_multiple: float
    value_fn: Callable[[float], float]
    v2: dict                       # the Nifty v2 working (v2.base_eps)
    cash_conversion: Optional[float]
    eps_annual: list
    eps_years: list
    cfo_annual: list
    profit_annual: list
    pb: float
    pb_reported: float
    fair_pb: Optional[float]
    asset_quality: Optional[dict]


class LeasesFields(TypedDict, total=False):
    v_base: float
    irr: float
    irr_cautious: float
    irr_curve: list
    parts: dict
    scenario_values: dict
    caprate: dict
    timeline: dict
    shares_m: float
    sens_return_resid: tuple


class LiquidFields(TypedDict, total=False):
    liquid: float
    liquid_items: List[Tuple[str, float]]
    liquid_ratio: float
    market_value: float
    debt: float


class Result(Identity, PriceAndPeriod, Value, Zone, ProducerFields, NavFields, GrowthFields, LeasesFields, LiquidFields,
             total=False):
    """One company's valuation result."""
