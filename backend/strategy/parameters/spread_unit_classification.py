"""Canonical spread unit classification for Parameter Settings."""
from __future__ import annotations

from enum import Enum


class SpreadUnitClassification(str, Enum):
    """Final WORK AA enum for maximumStrategySpreadPct provenance.

    LIVE strategy compare uses absolute_price MAX_SPREAD=0.0005 and excludes
    the field from LIVE runtimeParameters. The Settings field name implies
    percent but records the class constant with imperfect mapping. PAPER uses
    true percent 0-100. Never copy PAPER 0.50 into LIVE.
    """

    LEGACY_UNIT_REPRESENTATION = "LEGACY_UNIT_REPRESENTATION"
    PAPER_PERCENT_0_100 = "PAPER_PERCENT_0_100"


LIVE_SPREAD_CLASSIFICATION = SpreadUnitClassification.LEGACY_UNIT_REPRESENTATION
PAPER_SPREAD_CLASSIFICATION = SpreadUnitClassification.PAPER_PERCENT_0_100

# Disputed for percent interpretation; recorded in store with provenance only.
LIVE_SPREAD_PERCENT_INTERPRETATION_BLOCKED = True
LIVE_SPREAD_RECORDED_VALUE = 0.0005
LIVE_SPREAD_STRATEGY_COMPARISON_UNIT = "absolute_price"
LIVE_SPREAD_SETTINGS_FIELD_UNIT = "percent_name_with_absolute_constant"
LIVE_SPREAD_NOTE = (
    "LIVE runtimeParameters exclude maximumStrategySpreadPct; "
    "evaluate_spread_safety uses absolute MAX_SPREAD=0.0005. "
    "Settings field records the class constant with imperfect "
    "percent mapping. Do not copy PAPER 0.50."
)