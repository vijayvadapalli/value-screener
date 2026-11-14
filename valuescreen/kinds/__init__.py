"""The valuation models as classes: each knows its zone, its words, its charts and its lines on the price chart.

    kinds.of(model) → the Kind for a result's or company file's `model` ("producer", "growth", ...)

To add a model: write kinds/<model>.py with a Kind subclass, register it in KINDS, add its valuation function to
models.MODEL_FN and its required fields to loader.validate_company. Nothing else needs to know about it.
"""
from __future__ import annotations

from .base import NO_LEVELS, Kind
from .growth import GrowthKind
from .leases import LeasesKind
from .liquid import LiquidKind
from .nav import DeveloperKind, PhysicalKind
from .producer import ProducerKind

KINDS: dict[str, Kind] = {
    "producer": ProducerKind("Producer / royalty – owner earnings", "20% margin at 12x"),
    "cashflow": ProducerKind("Cash-flow (oil & gas)", "20% margin at the cautious multiple"),
    "developer": DeveloperKind(),
    "physical": PhysicalKind(),
    "growth": GrowthKind(),
    "leases": LeasesKind(),
    "liquid": LiquidKind(),
}


def of(model: str) -> Kind:
    return KINDS[model]


__all__ = ["KINDS", "NO_LEVELS", "Kind", "of"]
