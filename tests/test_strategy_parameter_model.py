"""Model, registry and migration baseline tests (E-PARAM-1)."""

import dataclasses
from datetime import datetime, timezone

import pytest

from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy
from backend.strategy.normalized_parameters import PAPER_NORMALIZED_CALIBRATION
from backend.strategy.parameters import (
    CANONICAL_SCHEMA_VERSION,
    LIVE_BASELINE_EXACT_KEYS,
    LIVE_BASELINE_IMPERFECT_MAPPING_KEYS,
    LIVE_BASELINE_NON_EQUIVALENT_KEYS,
    LIVE_CLASS_CONSTANT_BASELINE,
    PAPER_MIGRATION_BASELINE,
    CouplingGroup,
    ParameterScope,
    ParameterSource,
    ParameterStatus,
    ParameterTier,
    StrategyParameterRegistry,
    StrategyParameterSet,
    materialize_parameter_set,
)


def _strategy():
    return MicrostructureEdgeStrategy()


def _paper_baseline_values():
    return dict(PAPER_MIGRATION_BASELINE.values)


def test_registry_has_exactly_twelve_parameters():
    assert len(StrategyParameterRegistry.PARAMETERS) == 12
    assert len(StrategyParameterRegistry.names()) == 12


def test_primary_and_advanced_counts():
    assert len(StrategyParameterRegistry.primary()) == 5
    assert len(StrategyParameterRegistry.advanced()) == 7


def test_canonical_names_are_unique():
    names = StrategyParameterRegistry.names()
    assert len(names) == len(set(names))
    assert set(names) == {
        "minimumCompositeScore",
        "maximumStrategySpreadPct",
        "momentumWindowSeconds",
        "minimumStrategyConfidence",
        "maximumHoldMs",
        "minimumHoldMs",
        "exitMomentumMinimum",
        "exitLiquidityQualityMinimum",
        "exitSpreadQualityMinimum",
        "momentumMinimumWarmupSeconds",
        "absorptionVolumePercentile",
        "liquidityQualityPercentile",
    }


def test_primary_membership():
    primary = {meta.name for meta in StrategyParameterRegistry.primary()}
    assert primary == {
        "minimumCompositeScore",
        "maximumStrategySpreadPct",
        "momentumWindowSeconds",
        "minimumStrategyConfidence",
        "maximumHoldMs",
    }


def test_registry_units_and_ranges():
    expected = {
        "minimumCompositeScore": ("normalized score (0.0-1.0)", 0.0, 1.0, True, True),
        "maximumStrategySpreadPct": ("percent (0-100 scale)", 0.0, 5.0, False, True),
        "momentumWindowSeconds": ("seconds", 5.0, 600.0, True, True),
        "minimumStrategyConfidence": ("normalized score (0.0-1.0)", 0.0, 1.0, True, True),
        "maximumHoldMs": ("milliseconds", 100.0, 60000.0, True, True),
        "minimumHoldMs": ("milliseconds", 0.0, 60000.0, True, True),
        "exitMomentumMinimum": ("normalized score (0.0-1.0)", 0.0, 1.0, True, True),
        "exitLiquidityQualityMinimum": ("normalized score (0.0-1.0)", 0.0, 1.0, True, True),
        "exitSpreadQualityMinimum": ("normalized score (0.0-1.0)", 0.0, 1.0, True, True),
        "momentumMinimumWarmupSeconds": ("seconds", 0.0, 600.0, True, True),
        "absorptionVolumePercentile": ("normalized percentile (0.0-1.0)", 0.0, 1.0, False, True),
        "liquidityQualityPercentile": ("normalized percentile (0.0-1.0)", 0.0, 1.0, False, True),
    }
    assert len(expected) == 12
    for name, (unit, minimum, maximum, min_inc, max_inc) in expected.items():
        meta = StrategyParameterRegistry.get(name)
        assert meta is not None, name
        assert meta.unit == unit
        assert meta.minimum == minimum
        assert meta.maximum == maximum
        assert meta.minimum_inclusive is min_inc
        assert meta.maximum_inclusive is max_inc
        assert meta.editable is True


def test_registry_labels_and_descriptions_present():
    for meta in StrategyParameterRegistry.PARAMETERS:
        assert meta.label_en
        assert meta.label_ja
        assert meta.description
        assert meta.seed_source


def test_coupling_groups_are_represented():
    groups = {
        group: tuple(meta.name for meta in StrategyParameterRegistry.by_group(group))
        for group in CouplingGroup
    }
    assert groups[CouplingGroup.HOLDING_TIME] == (
        "minimumHoldMs",
        "maximumHoldMs",
    )
    assert groups[CouplingGroup.EXIT_DETERIORATION] == (
        "exitMomentumMinimum",
        "exitLiquidityQualityMinimum",
        "exitSpreadQualityMinimum",
    )
    assert set(groups[CouplingGroup.ENTRY_QUALITY]) == {
        "minimumCompositeScore",
        "minimumStrategyConfidence",
        "maximumStrategySpreadPct",
    }
    assert set(groups[CouplingGroup.MOMENTUM_HORIZON]) == {
        "momentumWindowSeconds",
        "momentumMinimumWarmupSeconds",
    }
    assert set(groups[CouplingGroup.DETECTOR_SENSITIVITY]) == {
        "absorptionVolumePercentile",
        "liquidityQualityPercentile",
    }
    grouped = [name for names in groups.values() for name in names]
    assert sorted(grouped) == sorted(StrategyParameterRegistry.names())


def test_scope_enum_values():
    assert {scope.value for scope in ParameterScope} == {"PAPER", "LIVE", "BOTH"}


def test_source_enum_values():
    assert {source.value for source in ParameterSource} == {
        "PARAMETER_SETTINGS",
        "MIGRATED_PAPER_CALIBRATION",
        "MIGRATED_CLASS_CONSTANT",
        "DEFAULT",
        "ROLLBACK",
    }


def test_status_enum_values():
    assert {status.value for status in ParameterStatus} == {
        "ACTIVE",
        "PENDING",
        "SUPERSEDED",
        "ARCHIVED",
    }


def test_model_is_immutable():
    parameter_set = materialize_parameter_set(PAPER_MIGRATION_BASELINE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        parameter_set.status = ParameterStatus.PENDING
    with pytest.raises(TypeError):
        parameter_set.parameters["minimumCompositeScore"] = 0.99


def test_valid_paper_baseline_is_complete_and_active():
    parameter_set = materialize_parameter_set(PAPER_MIGRATION_BASELINE)
    assert isinstance(parameter_set, StrategyParameterSet)
    assert parameter_set.scope is ParameterScope.PAPER
    assert parameter_set.status is ParameterStatus.ACTIVE
    assert parameter_set.source is ParameterSource.MIGRATED_PAPER_CALIBRATION
    assert parameter_set.schemaVersion == CANONICAL_SCHEMA_VERSION
    assert set(parameter_set.parameters) == set(StrategyParameterRegistry.names())


def test_valid_live_baseline_is_complete_and_active():
    parameter_set = materialize_parameter_set(LIVE_CLASS_CONSTANT_BASELINE)
    assert parameter_set.scope is ParameterScope.LIVE
    assert parameter_set.status is ParameterStatus.ACTIVE
    assert parameter_set.source is ParameterSource.MIGRATED_CLASS_CONSTANT
    assert set(parameter_set.parameters) == set(StrategyParameterRegistry.names())


def test_paper_baseline_equivalence():
    strategy = _strategy()
    values = _paper_baseline_values()
    calibration = PAPER_NORMALIZED_CALIBRATION["parameters"]

    calibration_keys = (
        "minimumCompositeScore",
        "maximumStrategySpreadPct",
        "momentumWindowSeconds",
        "minimumStrategyConfidence",
        "momentumMinimumWarmupSeconds",
        "absorptionVolumePercentile",
        "liquidityQualityPercentile",
    )
    for name in calibration_keys:
        assert values[name] == calibration[name]["value"], name

    assert values["maximumHoldMs"] == strategy.MAX_HOLD_MS
    assert values["minimumHoldMs"] == strategy.MIN_HOLD_MS
    assert values["exitMomentumMinimum"] == strategy.EXIT_MOMENTUM_MIN
    assert (
        values["exitLiquidityQualityMinimum"]
        == strategy.EXIT_LIQUIDITY_QUALITY_MIN
    )
    assert (
        values["exitSpreadQualityMinimum"] == strategy.EXIT_SPREAD_QUALITY_MIN
    )


def test_live_baseline_equivalence():
    strategy = _strategy()
    values = _live_baseline_values()

    assert set(LIVE_BASELINE_EXACT_KEYS).isdisjoint(
        LIVE_BASELINE_IMPERFECT_MAPPING_KEYS
    )
    assert set(LIVE_BASELINE_NON_EQUIVALENT_KEYS) == {
        "momentumWindowSeconds",
        "momentumMinimumWarmupSeconds",
        "absorptionVolumePercentile",
        "liquidityQualityPercentile",
    }

    expected = {
        "minimumCompositeScore": strategy.MIN_EDGE_SCORE,
        "minimumStrategyConfidence": strategy.MIN_CONFIDENCE,
        "maximumHoldMs": strategy.MAX_HOLD_MS,
        "minimumHoldMs": strategy.MIN_HOLD_MS,
        "exitMomentumMinimum": strategy.EXIT_MOMENTUM_MIN,
        "exitLiquidityQualityMinimum": strategy.EXIT_LIQUIDITY_QUALITY_MIN,
        "exitSpreadQualityMinimum": strategy.EXIT_SPREAD_QUALITY_MIN,
    }
    assert set(expected) == set(LIVE_BASELINE_EXACT_KEYS)
    for name, value in expected.items():
        assert values[name] == value, name

    assert (
        values["maximumStrategySpreadPct"] == strategy.MAX_SPREAD
    )


def _live_baseline_values():
    return dict(LIVE_CLASS_CONSTANT_BASELINE.values)


def test_model_rejects_unknown_parameter():
    values = _paper_baseline_values()
    values["unknownParameter"] = 1.0
    with pytest.raises(ValueError):
        StrategyParameterSet(
            parameterSetId="strategy-params/PAPER",
            schemaVersion=1,
            scope=ParameterScope.PAPER,
            status=ParameterStatus.ACTIVE,
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
            source=ParameterSource.PARAMETER_SETTINGS,
            parameters=values,
            effectiveFrom=None,
            configuredRevision=1,
            effectiveRevision=1,
        )


def test_model_rejects_missing_parameter():
    values = _paper_baseline_values()
    del values["minimumCompositeScore"]
    with pytest.raises(ValueError):
        StrategyParameterSet(
            parameterSetId="strategy-params/PAPER",
            schemaVersion=1,
            scope=ParameterScope.PAPER,
            status=ParameterStatus.ACTIVE,
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
            source=ParameterSource.PARAMETER_SETTINGS,
            parameters=values,
            effectiveFrom=None,
            configuredRevision=1,
            effectiveRevision=1,
        )


def test_model_rejects_bool_and_nan():
    now = datetime.now(timezone.utc)
    for bad in (True, float("nan"), float("inf")):
        values = _paper_baseline_values()
        values["minimumCompositeScore"] = bad
        with pytest.raises((ValueError, TypeError)):
            StrategyParameterSet(
                parameterSetId="strategy-params/PAPER",
                schemaVersion=1,
                scope=ParameterScope.PAPER,
                status=ParameterStatus.ACTIVE,
                createdAt=now,
                updatedAt=now,
                source=ParameterSource.PARAMETER_SETTINGS,
                parameters=values,
                effectiveFrom=None,
                configuredRevision=1,
                effectiveRevision=1,
            )


def test_model_rejects_unsupported_schema_version():
    values = _paper_baseline_values()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        StrategyParameterSet(
            parameterSetId="strategy-params/PAPER",
            schemaVersion=99,
            scope=ParameterScope.PAPER,
            status=ParameterStatus.ACTIVE,
            createdAt=now,
            updatedAt=now,
            source=ParameterSource.PARAMETER_SETTINGS,
            parameters=values,
            effectiveFrom=None,
            configuredRevision=1,
            effectiveRevision=1,
        )


def test_revision_fields_are_consistent():
    parameter_set = materialize_parameter_set(
        PAPER_MIGRATION_BASELINE,
        configured_revision=3,
        effective_revision=2,
    )
    assert parameter_set.configuredRevision == 3
    assert parameter_set.effectiveRevision == 2
    values = _paper_baseline_values()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        StrategyParameterSet(
            parameterSetId="strategy-params/PAPER",
            schemaVersion=1,
            scope=ParameterScope.PAPER,
            status=ParameterStatus.PENDING,
            createdAt=now,
            updatedAt=now,
            source=ParameterSource.PARAMETER_SETTINGS,
            parameters=values,
            effectiveFrom=None,
            configuredRevision=2,
            effectiveRevision=5,
        )


def test_to_dict_from_dict_round_trip():
    parameter_set = materialize_parameter_set(PAPER_MIGRATION_BASELINE)
    payload = parameter_set.to_dict()
    restored = StrategyParameterSet.from_dict(payload)
    assert restored == parameter_set
    assert restored.to_dict() == payload


def test_effective_from_is_optional_and_normalized():
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    parameter_set = materialize_parameter_set(
        PAPER_MIGRATION_BASELINE, now=moment
    )
    assert parameter_set.effectiveFrom is None
    payload = parameter_set.to_dict()
    assert payload["effectiveFrom"] is None
    assert payload["createdAt"].endswith("Z")


def test_tier_enum_values():
    assert {tier.value for tier in ParameterTier} == {"PRIMARY", "ADVANCED"}
