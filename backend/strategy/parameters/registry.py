"""Canonical StrategyParameterRegistry (E-PARAM-1).

Static, code-defined source of truth for the V1 editable strategy parameter
metadata.  This module contains metadata only: it performs no persistence and
is not imported by any Trading Cycle consumer.

Exactly twelve V1 editable parameters are defined (5 primary, 7 advanced).
Units, ranges, coupling groups and tiers are taken from the approved
architecture design.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .model import ParameterScope


class ParameterTier(str, Enum):
    """UI grouping tier for a canonical parameter."""

    PRIMARY = "PRIMARY"
    ADVANCED = "ADVANCED"


class CouplingGroup(str, Enum):
    """Coupled parameter group; members are presented and validated together."""

    HOLDING_TIME = "HOLDING_TIME"
    EXIT_DETERIORATION = "EXIT_DETERIORATION"
    ENTRY_QUALITY = "ENTRY_QUALITY"
    MOMENTUM_HORIZON = "MOMENTUM_HORIZON"
    DETECTOR_SENSITIVITY = "DETECTOR_SENSITIVITY"


class ValueType(str, Enum):
    """Numeric semantics required by a canonical parameter."""

    INTEGER = "int"
    FLOAT = "float"


_BOTH_SCOPES = frozenset({ParameterScope.PAPER, ParameterScope.LIVE})


@dataclass(frozen=True)
class ParameterMetadata:
    """Immutable metadata for one canonical strategy parameter."""

    name: str
    label_en: str
    label_ja: str
    unit: str
    minimum: float
    maximum: Optional[float]
    minimum_inclusive: bool
    maximum_inclusive: bool
    precision: int
    value_type: ValueType
    scope_applicability: frozenset
    coupling_group: CouplingGroup
    tier: ParameterTier
    editable: bool
    description: str
    seed_source: str

    def in_range(self, value: float) -> bool:
        """Return True when ``value`` satisfies the inclusive/exclusive range."""

        if self.minimum_inclusive:
            if value < self.minimum:
                return False
        elif value <= self.minimum:
            return False
        if self.maximum is None:
            return True
        if self.maximum_inclusive:
            if value > self.maximum:
                return False
        elif value >= self.maximum:
            return False
        return True

    def quantize(self, value: float):
        """Normalize ``value`` to the declared precision and value type."""

        if self.value_type is ValueType.INTEGER:
            return int(round(value))
        return round(float(value), self.precision)


def _meta(
    name: str,
    label_en: str,
    label_ja: str,
    unit: str,
    minimum: float,
    maximum: Optional[float],
    *,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
    precision: int = 6,
    value_type: ValueType = ValueType.FLOAT,
    coupling_group: CouplingGroup,
    tier: ParameterTier,
    description: str,
    seed_source: str,
    editable: bool = True,
) -> ParameterMetadata:
    return ParameterMetadata(
        name=name,
        label_en=label_en,
        label_ja=label_ja,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        minimum_inclusive=minimum_inclusive,
        maximum_inclusive=maximum_inclusive,
        precision=precision,
        value_type=value_type,
        scope_applicability=_BOTH_SCOPES,
        coupling_group=coupling_group,
        tier=tier,
        editable=editable,
        description=description,
        seed_source=seed_source,
    )


class StrategyParameterRegistry:
    """Single static registry of canonical V1 strategy parameters."""

    PARAMETERS: Tuple[ParameterMetadata, ...] = (
        _meta(
            "minimumCompositeScore",
            "Composite Entry Score",
            "総合エントリースコア",
            "normalized score (0.0-1.0)",
            0.0,
            1.0,
            coupling_group=CouplingGroup.ENTRY_QUALITY,
            tier=ParameterTier.PRIMARY,
            description=(
                "Minimum composite decision score required before execution "
                "is allowed."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.minimumCompositeScore (PAPER) / "
                "MicrostructureEdgeStrategy.MIN_EDGE_SCORE (LIVE)"
            ),
        ),
        _meta(
            "maximumStrategySpreadPct",
            "Maximum Strategy Spread",
            "最大スプレッド",
            "percent (0-100 scale)",
            0.0,
            5.0,
            minimum_inclusive=False,
            maximum_inclusive=True,
            coupling_group=CouplingGroup.ENTRY_QUALITY,
            tier=ParameterTier.PRIMARY,
            description=(
                "Maximum symbol-normalized spread percent accepted by the "
                "strategy. 0.50 means 0.50 percent."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.maximumStrategySpreadPct (PAPER) / "
                "MicrostructureEdgeStrategy.MAX_SPREAD (LIVE)"
            ),
        ),
        _meta(
            "momentumWindowSeconds",
            "Momentum Window",
            "モメンタム窓",
            "seconds",
            5.0,
            600.0,
            coupling_group=CouplingGroup.MOMENTUM_HORIZON,
            tier=ParameterTier.PRIMARY,
            description="Causal strategy momentum horizon in seconds.",
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.momentumWindowSeconds"
            ),
        ),
        _meta(
            "minimumStrategyConfidence",
            "Minimum Confidence",
            "最小信頼度",
            "normalized score (0.0-1.0)",
            0.0,
            1.0,
            coupling_group=CouplingGroup.ENTRY_QUALITY,
            tier=ParameterTier.PRIMARY,
            description=(
                "Downstream minimum confidence floor required before execution."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.minimumStrategyConfidence (PAPER) / "
                "MicrostructureEdgeStrategy.MIN_CONFIDENCE and the ExecutionRuntime "
                "floor (LIVE)"
            ),
        ),
        _meta(
            "maximumHoldMs",
            "Maximum Hold",
            "最大保有時間",
            "milliseconds",
            100.0,
            None,
            precision=0,
            value_type=ValueType.INTEGER,
            coupling_group=CouplingGroup.HOLDING_TIME,
            tier=ParameterTier.PRIMARY,
            description=(
                "Hard maximum holding time before a formal MAX_HOLD exit."
            ),
            seed_source="MicrostructureEdgeStrategy.MAX_HOLD_MS",
        ),
        _meta(
            "minimumHoldMs",
            "Minimum Hold",
            "最小保有時間",
            "milliseconds",
            0.0,
            60000.0,
            precision=0,
            value_type=ValueType.INTEGER,
            coupling_group=CouplingGroup.HOLDING_TIME,
            tier=ParameterTier.ADVANCED,
            description=(
                "Soft-exit floor that gates reversal and momentum-decay exits."
            ),
            seed_source="MicrostructureEdgeStrategy.MIN_HOLD_MS",
        ),
        _meta(
            "exitMomentumMinimum",
            "Exit Momentum Minimum",
            "決済モメンタム下限",
            "normalized score (0.0-1.0)",
            0.0,
            1.0,
            coupling_group=CouplingGroup.EXIT_DETERIORATION,
            tier=ParameterTier.ADVANCED,
            description="Momentum-decay exit threshold.",
            seed_source="MicrostructureEdgeStrategy.EXIT_MOMENTUM_MIN",
        ),
        _meta(
            "exitLiquidityQualityMinimum",
            "Exit Liquidity Quality Minimum",
            "決済流動性品質下限",
            "normalized score (0.0-1.0)",
            0.0,
            1.0,
            coupling_group=CouplingGroup.EXIT_DETERIORATION,
            tier=ParameterTier.ADVANCED,
            description="Liquidity-deterioration exit threshold.",
            seed_source=(
                "MicrostructureEdgeStrategy.EXIT_LIQUIDITY_QUALITY_MIN"
            ),
        ),
        _meta(
            "exitSpreadQualityMinimum",
            "Exit Spread Quality Minimum",
            "決済スプレッド品質下限",
            "normalized score (0.0-1.0)",
            0.0,
            1.0,
            coupling_group=CouplingGroup.EXIT_DETERIORATION,
            tier=ParameterTier.ADVANCED,
            description="Spread-divergence exit threshold.",
            seed_source="MicrostructureEdgeStrategy.EXIT_SPREAD_QUALITY_MIN",
        ),
        _meta(
            "momentumMinimumWarmupSeconds",
            "Momentum Warmup",
            "モメンタム暖機",
            "seconds",
            0.0,
            600.0,
            coupling_group=CouplingGroup.MOMENTUM_HORIZON,
            tier=ParameterTier.ADVANCED,
            description=(
                "Minimum elapsed causal history before momentum is usable."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.momentumMinimumWarmupSeconds"
            ),
        ),
        _meta(
            "absorptionVolumePercentile",
            "Absorption Volume Percentile",
            "吸収出来高パーセンタイル",
            "normalized percentile (0.0-1.0)",
            0.0,
            1.0,
            minimum_inclusive=False,
            maximum_inclusive=True,
            coupling_group=CouplingGroup.DETECTOR_SENSITIVITY,
            tier=ParameterTier.ADVANCED,
            description=(
                "Rolling volume percentile that marks abnormal depth for the "
                "absorption detector."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.absorptionVolumePercentile"
            ),
        ),
        _meta(
            "liquidityQualityPercentile",
            "Liquidity Quality Percentile",
            "流動性品質パーセンタイル",
            "normalized percentile (0.0-1.0)",
            0.0,
            1.0,
            minimum_inclusive=False,
            maximum_inclusive=True,
            coupling_group=CouplingGroup.DETECTOR_SENSITIVITY,
            tier=ParameterTier.ADVANCED,
            description=(
                "Rolling volume percentile used as the symbol-relative "
                "liquidity quality reference."
            ),
            seed_source=(
                "PAPER_NORMALIZED_CALIBRATION.liquidityQualityPercentile"
            ),
        ),
    )

    BY_NAME: Mapping[str, ParameterMetadata] = MappingProxyType(
        {parameter.name: parameter for parameter in PARAMETERS}
    )

    COUPLING_GROUPS: Mapping[CouplingGroup, Tuple[str, ...]] = MappingProxyType(
        {
            CouplingGroup.HOLDING_TIME: (
                "minimumHoldMs",
                "maximumHoldMs",
            ),
            CouplingGroup.EXIT_DETERIORATION: (
                "exitMomentumMinimum",
                "exitLiquidityQualityMinimum",
                "exitSpreadQualityMinimum",
            ),
            CouplingGroup.ENTRY_QUALITY: (
                "minimumCompositeScore",
                "minimumStrategyConfidence",
                "maximumStrategySpreadPct",
            ),
            CouplingGroup.MOMENTUM_HORIZON: (
                "momentumWindowSeconds",
                "momentumMinimumWarmupSeconds",
            ),
            CouplingGroup.DETECTOR_SENSITIVITY: (
                "absorptionVolumePercentile",
                "liquidityQualityPercentile",
            ),
        }
    )

    @classmethod
    def get(cls, name: str) -> Optional[ParameterMetadata]:
        return cls.BY_NAME.get(name)

    @classmethod
    def names(cls) -> Tuple[str, ...]:
        return tuple(parameter.name for parameter in cls.PARAMETERS)

    @classmethod
    def primary(cls) -> Tuple[ParameterMetadata, ...]:
        return tuple(
            parameter
            for parameter in cls.PARAMETERS
            if parameter.tier is ParameterTier.PRIMARY
        )

    @classmethod
    def advanced(cls) -> Tuple[ParameterMetadata, ...]:
        return tuple(
            parameter
            for parameter in cls.PARAMETERS
            if parameter.tier is ParameterTier.ADVANCED
        )

    @classmethod
    def by_group(cls, group: CouplingGroup) -> Tuple[ParameterMetadata, ...]:
        return tuple(
            cls.BY_NAME[name] for name in cls.COUPLING_GROUPS[group]
        )
