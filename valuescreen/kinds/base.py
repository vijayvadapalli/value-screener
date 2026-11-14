"""What every valuation model provides to the rest of the system: its zone, its words, its charts and its lines on the
price chart. One subclass per model (kinds/<model>.py), registered in kinds/__init__.py – the report modules ask the
model instead of checking which one it is, so a new model is one new file.

All methods take the result dict `r` (models.value_company + rules); `c` is the company file and `cfg` the config.
"""
from __future__ import annotations

from ..types import Result

NO_LEVELS = dict(margin_of_safety=None, put_level=None, call_level=None, buy_level=None, add_level=None)


class Kind:
    label = ""           # the model's name in each company section's header
    buy_rule = ""        # caption of the "Buy level" card
    profit_note = None   # why profit vs price does not apply (models valued on assets), or None

    # ---- the company file
    def check(self, c) -> str | None:
        """What the company file is missing for this model, or None (loader.validate_company raises it)."""
        return None

    # ---- the zone (rules.py adds the stale / cyclical modifiers, the signal and the action)
    def zone(self, r: Result, zones) -> dict:
        """{band, buy_step?, high_cost?, margin_of_safety, put_level, call_level, buy_level, add_level}."""
        raise NotImplementedError

    # ---- words (wording.py)
    def headline(self, r: Result, cfg, at, act, name, mos) -> str:
        """The one-paragraph verdict. `at` = "At <price> (<date>)", `act` = the action in bold, `mos` = margin of safety."""
        raise NotImplementedError

    def steps(self, r: Result, c) -> list[str]:
        return []

    def example(self, r: Result, c) -> str | None:
        return None

    def figures(self, r: Result) -> list[tuple]:
        """Key-figure rows (label, value, bold) – wording.key_figures adds the zone."""
        return []

    def value_cards(self, r: Result, mos, mos_colour) -> list[tuple]:
        """The value and margin-of-safety cards that follow the price card."""
        return []

    def buy_card_rule(self, r: Result) -> str:
        return self.buy_rule

    def extra_card(self, r: Result) -> tuple | None:
        """The last card: what the price assumes (metal price, growth) or the return a year."""
        return None

    # ---- summary tables (html_report, profit_vs_price)
    def summary_detail(self, r: Result) -> str:
        """The value report's verdict in a few words, shown next to the profit-vs-price grade."""
        raise NotImplementedError

    def value_cell(self, r: Result) -> tuple[str, str]:
        """(value, basis) for the summary table."""
        return "–", "not valued"

    def assumes_cell(self, r: Result) -> tuple[str, float | None]:
        """What the price already assumes, and a number to sort on."""
        if r.get("implied_metal_hi"):
            return f"{r.get('primary_metal', '')} {r['implied_metal_hi']:,.0f}", None
        return "–", None

    # ---- charts (charts.py, price_chart.py)
    def band_points(self, r: Result) -> list[tuple]:
        """[(label, value, kind)] for the valuation band; kind is buy | value | sell."""
        return []

    def curve(self, ax, r: Result, c, cfg) -> bool:
        """Draws the model's main chart on `ax`; False when there is nothing to draw."""
        return False

    def heat_grid(self, r: Result, c, cfg):
        """(title, rows, cols, values) for the sensitivity heatmap, or None."""
        return None

    def extra_chart(self, r: Result, path):
        """A second chart some models add (the lease value bridge), as a PNG path, or None."""
        return None

    def value_lines(self, r: Result) -> list[tuple]:
        """[(price, label, kind, colour, solid)] – our valuation drawn on the price chart (price_chart merges them)."""
        return []
