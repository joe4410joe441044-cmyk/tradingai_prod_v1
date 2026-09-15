"""Named migration baselines for canonical strategy parameters (E-PARAM-1).

Baselines are the observable, temporary seed sources used during migration.
They are derived from the CURRENT sources of truth:

- PAPER: ``backend/strategy/normalized_parameters.PAPER_NORMALIZED_CALIBRATION``
  for the parameters it supplies, plus the dedicated exit/holding class
  constants (which are class constants in BOTH contracts today).
- LIVE: the current ``MicrostructureEdgeStrategy`` class constants, plus the
  ``MicrostructureStateBuilder`` default fallbacks for the normalized-only
  parameters that the legacy LIVE contract does not read.

No consumer is switched to these baselines in E-PARAM-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from backend.strategy.MicrostructureEdgeStrategy import (
    MicrostructureEdgeStrategy,
)
from backend.strategy.normalized_parameters import PAPER_NORMALIZED_CALIBRATION

from .model import (
    ParameterScope,
    ParameterSource,
    ParameterStatus,
    StrategyParameterSet,
)

# Fresh instance used only to read the current runtime constants.  Constructing
# the strategy has no side effects.
_STRATEGY = MicrostructureEdgeStrategy()


def _paper_value(name: str) -> float:
    return PAPER_NORMALIZED_CALIBRATION["parameters"][name]["value"]


@dataclass(frozen=True)
class MigrationBaseline:
    """A named, observable migration seed for one scope."""

    name: str
    parameterSetId: str
    scope: ParameterScope
    source: ParameterSource
    values: Mapping[str, float]
    notes: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "parameterSetId": self.parameterSetId,
            "scope": self.scope.value,
            "source": self.source.value,
            "values": dict(self.values),
            "notes": self.notes,
        }


PAPER_MIGRATION_BASELINE = MigrationBaseline(
    name="PAPER_MIGRATION_BASELINE",
    parameterSetId="strategy-params/PAPER",
    scope=ParameterScope.PAPER,
    source=ParameterSource.MIGRATED_PAPER_CALIBRATION,
    values=MappingProxyType(
        {
            "minimumCompositeScore": _paper_value("minimumCompositeScore"),
            "maximumStrategySpreadPct": _paper_value(
                "maximumStrategySpreadPct"
            ),
            "momentumWindowSeconds": _paper_value("momentumWindowSeconds"),
            "minimumStrategyConfidence": _paper_value(
                "minimumStrategyConfidence"
            ),
            "maximumHoldMs": _STRATEGY.MAX_HOLD_MS,
            "minimumHoldMs": _STRATEGY.MIN_HOLD_MS,
            "exitMomentumMinimum": _STRATEGY.EXIT_MOMENTUM_MIN,
            "exitLiquidityQualityMinimum": (
                _STRATEGY.EXIT_LIQUIDITY_QUALITY_MIN
            ),
            "exitSpreadQualityMinimum": _STRATEGY.EXIT_SPREAD_QUALITY_MIN,
            "momentumMinimumWarmupSeconds": _paper_value(
                "momentumMinimumWarmupSeconds"
            ),
            "absorptionVolumePercentile": _paper_value(
                "absorptionVolumePercentile"
            ),
            "liquidityQualityPercentile": _paper_value(
                "liquidityQualityPercentile"
            ),
        }
    ),
    notes=(
        "PAPER values are byte-equivalent to PAPER_NORMALIZED_CALIBRATION for "
        "the parameters it supplies. Dedicated exit thresholds and holding "
        "times are class constants in both contracts and are preserved "
        "exactly (EXIT_MOMENTUM_MIN=0.40, EXIT_LIQUIDITY_QUALITY_MIN=0.30, "
        "EXIT_SPREAD_QUALITY_MIN=0.30, MIN_HOLD_MS=500, MAX_HOLD_MS=3000)."
    ),
)


LIVE_CLASS_CONSTANT_BASELINE = MigrationBaseline(
    name="LIVE_CLASS_CONSTANT_BASELINE",
    parameterSetId="strategy-params/LIVE",
    scope=ParameterScope.LIVE,
    source=ParameterSource.MIGRATED_CLASS_CONSTANT,
    values=MappingProxyType(
        {
            "minimumCompositeScore": _STRATEGY.MIN_EDGE_SCORE,
            "maximumStrategySpreadPct": _STRATEGY.MAX_SPREAD,
            "momentumWindowSeconds": 60.0,
            "minimumStrategyConfidence": _STRATEGY.MIN_CONFIDENCE,
            "maximumHoldMs": _STRATEGY.MAX_HOLD_MS,
            "minimumHoldMs": _STRATEGY.MIN_HOLD_MS,
            "exitMomentumMinimum": _STRATEGY.EXIT_MOMENTUM_MIN,
            "exitLiquidityQualityMinimum": (
                _STRATEGY.EXIT_LIQUIDITY_QUALITY_MIN
            ),
            "exitSpreadQualityMinimum": _STRATEGY.EXIT_SPREAD_QUALITY_MIN,
            "momentumMinimumWarmupSeconds": 20.0,
            "absorptionVolumePercentile": 0.90,
            "liquidityQualityPercentile": 0.90,
        }
    ),
    notes=(
        "LIVE values reproduce the current runtime behavior. Exact class "
        "constant equivalents: MIN_EDGE_SCORE=0.55, MIN_CONFIDENCE=0.60, "
        "MIN_HOLD_MS=500, MAX_HOLD_MS=3000, EXIT_MOMENTUM_MIN=0.40, "
        "EXIT_LIQUIDITY_QUALITY_MIN=0.30, EXIT_SPREAD_QUALITY_MIN=0.30. "
        "maximumStrategySpreadPct records MAX_SPREAD=0.0005 with an imperfect "
        "semantic mapping (legacy is an absolute price threshold; canonical "
        "unit is percent). momentumWindowSeconds=60.0, "
        "momentumMinimumWarmupSeconds=20.0, absorptionVolumePercentile=0.90 "
        "and liquidityQualityPercentile=0.90 are MicrostructureStateBuilder "
        "default fallbacks for parameters the legacy LIVE contract does not "
        "read; they have no active LIVE runtime equivalent."
    ),
)


# LIVE parameters with an exact current runtime equivalent.
LIVE_BASELINE_EXACT_KEYS: Tuple[str, ...] = (
    "minimumCompositeScore",
    "minimumStrategyConfidence",
    "maximumHoldMs",
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
)

# LIVE parameters recorded from a class constant with a documented imperfect
# unit/semantic mapping.
LIVE_BASELINE_IMPERFECT_MAPPING_KEYS: Tuple[str, ...] = (
    "maximumStrategySpreadPct",
)

# LIVE parameters with no active legacy LIVE runtime equivalent.  Values are
# the MicrostructureStateBuilder default fallbacks and are NOT claimed to be
# behavior-equivalent for the legacy contract.
LIVE_BASELINE_NON_EQUIVALENT_KEYS: Tuple[str, ...] = (
    "momentumWindowSeconds",
    "momentumMinimumWarmupSeconds",
    "absorptionVolumePercentile",
    "liquidityQualityPercentile",
)


def materialize_parameter_set(
    baseline: MigrationBaseline,
    *,
    configured_revision: int = 1,
    effective_revision: int = 1,
    status: ParameterStatus = ParameterStatus.ACTIVE,
    now: Optional[datetime] = None,
) -> StrategyParameterSet:
    """Build a complete, validated :class:`StrategyParameterSet` from a baseline."""

    moment = now or datetime.now(timezone.utc)
    return StrategyParameterSet(
        parameterSetId=baseline.parameterSetId,
        schemaVersion=1,
        scope=baseline.scope,
        status=status,
        createdAt=moment,
        updatedAt=moment,
        source=baseline.source,
        parameters=dict(baseline.values),
        effectiveFrom=None,
        configuredRevision=configured_revision,
        effectiveRevision=effective_revision,
    )
