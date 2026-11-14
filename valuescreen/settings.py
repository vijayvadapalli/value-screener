"""Lookups in the configuration that the valuation itself needs – currency conversion and tiers – kept apart from
loader.py (which reads files) so the models do not depend on file reading. loader re-exports them."""
from __future__ import annotations


class ValidationError(ValueError):
    pass


def fx(cfg: dict, frm: str, to: str) -> float:
    """Multiplier converting an amount in `frm` currency into `to` currency."""
    if frm == to:
        return 1.0
    table = cfg["fx_usd_per_unit"]
    if frm not in table or to not in table:
        raise ValidationError(f"FX rate needed for {frm}->{to}; add it to config.yaml fx_usd_per_unit")
    return table[frm] / table[to]


def tier_of(c: dict, cfg: dict) -> str | None:
    """A, B or C from the company file's `tier:`, else from config `tiers:`; None when untiered."""
    if c.get("tier"):
        return str(c["tier"]).upper()
    for tier, tickers in (cfg.get("tiers") or {}).items():
        if c["ticker"].upper() in {str(x).upper() for x in tickers}:
            return str(tier).upper()
    return None
