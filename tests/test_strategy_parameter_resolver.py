"""E-PARAM-2 focused tests: canonical PAPER authority / runtime snapshot.

These tests prove the PAPER authority migration is behavior-neutral:
CONFIGURED -> EFFECTIVE -> immutable runtime snapshot, explicit observable
fallback, legacy ``PAPER_ONLY`` compatibility, and unchanged PAPER feature /
strategy / confidence behavior.  LIVE is proven to stay on the legacy path.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace

import pytest

from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder,
)
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import governance_state
from backend.runtime.trading_trace import strategy_decision_snapshot
from backend.strategy.MicrostructureEdgeStrategy import (
    MicrostructureEdgeStrategy,
)
from backend.strategy.normalized_parameters import (
    PAPER_NORMALIZED_CALIBRATION,
    paper_calibration_for_mode,
    parameter_value,
)
from backend.strategy.parameters.baselines import (
    LIVE_CLASS_CONSTANT_BASELINE,
    PAPER_MIGRATION_BASELINE,
)
from backend.strategy.parameters.model import (
    ParameterScope,
    ParameterSource,
    ParameterStatus,
    StrategyParameterSet,
)
from backend.strategy.parameters.resolver import (
    PAPER_RUNTIME_SCOPE,
    CanonicalParameterResolver,
    RuntimeAuthorityStatus,
)
from backend.strategy.parameters.store import (
    STORAGE_SUBDIRECTORY,
    StrategyParameterStore,
)


def _paper_set(**overrides):
    values = dict(PAPER_MIGRATION_BASELINE.values)
    values.update(overrides)
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyParameterSet(
        parameterSetId="strategy-params/PAPER",
        schemaVersion=1,
        scope=ParameterScope.PAPER,
        status=ParameterStatus.ACTIVE,
        createdAt=moment,
        updatedAt=moment,
        source=ParameterSource.PARAMETER_SETTINGS,
        parameters=values,
        effectiveFrom=None,
        configuredRevision=7,
        effectiveRevision=5,
    )


def _live_set(**overrides):
    values = dict(LIVE_CLASS_CONSTANT_BASELINE.values)
    values.update(overrides)
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyParameterSet(
        parameterSetId="strategy-params/LIVE",
        schemaVersion=1,
        scope=ParameterScope.LIVE,
        status=ParameterStatus.ACTIVE,
        createdAt=moment,
        updatedAt=moment,
        source=ParameterSource.PARAMETER_SETTINGS,
        parameters=values,
        effectiveFrom=None,
        configuredRevision=9,
        effectiveRevision=9,
    )


def packet(mid_price, total_volume, *, spread_pct=0.20, last_price=None):
    half_spread = mid_price * (spread_pct / 100.0) / 2.0
    return {
        "buyVolume": total_volume * 0.55,
        "sellVolume": total_volume * 0.45,
        "bestBid": mid_price - half_spread,
        "bestAsk": mid_price + half_spread,
        "lastPrice": mid_price if last_price is None else last_price,
    }


def _warm(parameter_set, mid_price=100.0, total_volume=1000.0, count=20):
    builder = MicrostructureStateBuilder(parameter_set=parameter_set)
    state = None
    for _ in range(count):
        state = builder.build_microstructure_state(
            packet(mid_price, total_volume)
        )
    return builder, state


# ---------------------------------------------------------------------------
# Resolver / scope / fallback
# ---------------------------------------------------------------------------


def test_resolver_paper_scope_and_canonical_metadata(tmp_path):
    resolver = CanonicalParameterResolver(base_directory=tmp_path)
    snapshot = resolver.resolve_paper()

    assert snapshot.scope == PAPER_RUNTIME_SCOPE == "PAPER_ONLY"
    assert snapshot.canonicalScope == "PAPER"
    assert snapshot.parameterSetId == "strategy-params/PAPER"
    assert snapshot.authorityStatus == (
        RuntimeAuthorityStatus.PAPER_MIGRATION_BASELINE.value
    )
    assert snapshot.storeStatus == "MISSING"
    assert snapshot.source == "MIGRATED_PAPER_CALIBRATION"
    assert snapshot.featureContract == "TIME_SYMBOL_NORMALIZED_V1"
    assert snapshot.capturedAt.endswith("Z")
    assert snapshot.configuredRevision == 1
    assert snapshot.effectiveRevision == 1

    runtime = snapshot.to_runtime_dict()
    assert runtime["scope"] == "PAPER_ONLY"
    assert runtime["canonicalScope"] == "PAPER"
    assert runtime["parameterSetId"] == "strategy-params/PAPER"
    assert runtime["configuredRevision"] == 1
    assert runtime["effectiveRevision"] == 1
    assert runtime["source"] == "MIGRATED_PAPER_CALIBRATION"
    assert runtime["authorityStatus"] == "PAPER_MIGRATION_BASELINE"
    assert runtime["storeStatus"] == "MISSING"


def test_store_to_configured_to_effective(tmp_path):
    store = StrategyParameterStore(tmp_path)
    saved = store.save(_paper_set(minimumCompositeScore=0.42))
    assert saved.status.value == "SAVED"

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()

    assert snapshot.authorityStatus == "PERSISTED"
    assert snapshot.storeStatus == "VALID"
    assert snapshot.source == "PARAMETER_SETTINGS"
    assert snapshot.configuredRevision == 7
    assert snapshot.effectiveRevision == 5
    assert snapshot.parameters["minimumCompositeScore"] == 0.42
    # The runtime legacy view is overlaid with the canonical effective value.
    assert (
        snapshot.to_runtime_dict()["parameters"]["minimumCompositeScore"][
            "value"
        ]
        == 0.42
    )


def test_missing_store_falls_back_observably(tmp_path):
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    assert snapshot.authorityStatus == "PAPER_MIGRATION_BASELINE"
    assert snapshot.storeStatus == "MISSING"
    assert snapshot.source == "MIGRATED_PAPER_CALIBRATION"
    assert snapshot.source != "MIGRATED_CLASS_CONSTANT"


def test_corrupt_store_falls_back_observably(tmp_path):
    directory = tmp_path / STORAGE_SUBDIRECTORY
    directory.mkdir()
    target = directory / "strategy-params__PAPER.json"
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, b"{not-valid-json")
    finally:
        os.close(fd)

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    assert snapshot.authorityStatus == "PAPER_MIGRATION_BASELINE"
    assert snapshot.storeStatus == "CORRUPT"
    assert snapshot.source == "MIGRATED_PAPER_CALIBRATION"


def test_no_cross_scope_fallback(tmp_path):
    store = StrategyParameterStore(tmp_path)
    assert store.save(_live_set(minimumCompositeScore=0.99)).status.value == (
        "SAVED"
    )

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    assert snapshot.authorityStatus == "PAPER_MIGRATION_BASELINE"
    assert snapshot.source == "MIGRATED_PAPER_CALIBRATION"
    assert snapshot.source != "MIGRATED_CLASS_CONSTANT"
    assert snapshot.parameters["minimumCompositeScore"] == 0.34


def test_revision_stability_for_persisted_and_fallback(tmp_path):
    persisted = CanonicalParameterResolver(base_directory=tmp_path)
    first = persisted.resolve_paper()
    second = persisted.resolve_paper()
    assert (first.configuredRevision, first.effectiveRevision) == (1, 1)
    assert (second.configuredRevision, second.effectiveRevision) == (1, 1)

    store = StrategyParameterStore(tmp_path)
    store.save(_paper_set())
    persisted_snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    assert persisted_snapshot.authorityStatus == "PERSISTED"
    assert persisted_snapshot.configuredRevision == 7
    assert persisted_snapshot.effectiveRevision == 5
    repeat = CanonicalParameterResolver(base_directory=tmp_path).resolve_paper()
    assert repeat.configuredRevision == 7
    assert repeat.effectiveRevision == 5


# ---------------------------------------------------------------------------
# Runtime snapshot immutability / legacy compatibility
# ---------------------------------------------------------------------------


def test_runtime_snapshot_is_immutable(tmp_path):
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()

    with pytest.raises(FrozenInstanceError):
        snapshot.scope = "LIVE"

    with pytest.raises(TypeError):
        snapshot.runtimeParameters["minimumCompositeScore"]["value"] = 0.0

    runtime = snapshot.to_runtime_dict()
    runtime["parameters"]["minimumCompositeScore"]["value"] = 999.0
    assert snapshot.parameters["minimumCompositeScore"] == 0.34
    assert (
        snapshot.to_runtime_dict()["parameters"]["minimumCompositeScore"][
            "value"
        ]
        == 0.34
    )


def test_legacy_paper_only_compatibility(tmp_path):
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    runtime = snapshot.to_runtime_dict()

    assert parameter_value(runtime, "minimumCompositeScore", None) == 0.34
    assert parameter_value(runtime, "minimumStrategyConfidence", None) == 0.23
    assert (
        parameter_value(runtime, "strategyFeatureCalibrationId", None)
        == "TIME_SYMBOL_NORMALIZED_V1"
    )
    # Legacy shim is preserved for existing consumers/tests.
    assert paper_calibration_for_mode("paper") == PAPER_NORMALIZED_CALIBRATION
    assert paper_calibration_for_mode("live") is None


# ---------------------------------------------------------------------------
# PAPER equivalence
# ---------------------------------------------------------------------------


def test_paper_resolved_value_equivalence(tmp_path):
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    runtime = snapshot.to_runtime_dict()

    for name, expected in PAPER_MIGRATION_BASELINE.values.items():
        assert snapshot.parameters[name] == expected

    for name, entry in PAPER_NORMALIZED_CALIBRATION["parameters"].items():
        assert runtime["parameters"][name]["value"] == entry["value"]
        assert runtime["parameters"][name]["unit"] == entry["unit"]


def test_paper_feature_equivalence(tmp_path):
    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()

    legacy_builder, legacy_state = _warm(
        deepcopy(PAPER_NORMALIZED_CALIBRATION)
    )
    canonical_builder, canonical_state = _warm(runtime)

    for key in (
        "absorptionDetected",
        "stagnantHeavyFlow",
        "fakePressureDetected",
        "liquidityCalibrationReady",
        "normalizedSpreadQuality",
        "normalizedLiquidityQuality",
        "normalizedMomentum",
        "momentumDirection",
        "directionPurity",
        "activityRatio",
        "momentumWarmupReady",
    ):
        assert legacy_state[key] == canonical_state[key], key

    legacy_details = legacy_state["liquidityInstabilityDebug"][
        "detectorDetails"
    ]
    canonical_details = canonical_state["liquidityInstabilityDebug"][
        "detectorDetails"
    ]
    assert legacy_details == canonical_details


def test_paper_spread_safety_equivalence(tmp_path):
    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()

    _, legacy_state = _warm(deepcopy(PAPER_NORMALIZED_CALIBRATION))
    _, canonical_state = _warm(runtime)

    strategy = MicrostructureEdgeStrategy()
    assert strategy.evaluate_spread_safety(
        legacy_state
    ) == strategy.evaluate_spread_safety(canonical_state)
    assert strategy.evaluate_spread_safety(canonical_state)["spreadSafe"] is (
        True
    )


def test_feature_builder_uses_persisted_canonical_authority(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper_set(maximumStrategySpreadPct=0.01))

    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()
    assert runtime["authorityStatus"] == "PERSISTED"

    _, tight_state = _warm(runtime)
    strategy = MicrostructureEdgeStrategy()
    assert strategy.evaluate_spread_safety(tight_state)["spreadSafe"] is (
        False
    )

    empty = tmp_path / "empty"
    empty.mkdir()
    baseline = CanonicalParameterResolver(
        base_directory=empty
    ).resolve_paper().to_runtime_dict()
    _, baseline_state = _warm(baseline)
    assert strategy.evaluate_spread_safety(baseline_state)["spreadSafe"] is (
        True
    )


def test_paper_strategy_equivalence(tmp_path):
    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()

    _, legacy_state = _warm(deepcopy(PAPER_NORMALIZED_CALIBRATION))
    _, canonical_state = _warm(runtime)

    strategy = MicrostructureEdgeStrategy()
    legacy = strategy.process_microstructure_strategy(legacy_state)["strategy"]
    canonical = strategy.process_microstructure_strategy(canonical_state)[
        "strategy"
    ]

    for key in (
        "edge",
        "confidence",
        "executionAllowed",
        "direction",
        "suppressionReason",
        "featureContract",
        "minimumCompositeScore",
        "minimumConfidence",
        "hardGateResults",
        "entryReadiness",
    ):
        assert legacy[key] == canonical[key], key


def test_paper_confidence_equivalence(tmp_path):
    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()

    previous = dict(governance_state)
    governance_result = {"executionAllowed": True}
    try:
        governance_state["execution_enabled"] = True
        paper_runtime = ExecutionRuntime()
        paper_runtime.engine = SimpleNamespace(
            mode="paper", get_risk_state=lambda: {}
        )

        def evaluate(confidence, authority):
            return paper_runtime.evaluate_execution_permission(
                {"confidence": confidence, "parameterAuthority": authority},
                governance_result,
                canonical_direction="LONG",
            )

        for confidence in (0.23, 0.2299, 0.30):
            legacy_result = evaluate(
                confidence, deepcopy(PAPER_NORMALIZED_CALIBRATION)
            )
            canonical_result = evaluate(confidence, runtime)
            assert legacy_result == canonical_result
        assert evaluate(
            0.23, runtime
        )["executionAllowed"] is True
        assert evaluate(
            0.2299, runtime
        )["reason"] == "LOW_CONFIDENCE"
    finally:
        governance_state.clear()
        governance_state.update(previous)


# ---------------------------------------------------------------------------
# LIVE no-regression
# ---------------------------------------------------------------------------


def test_live_path_unchanged(tmp_path):
    # A PAPER canonical snapshot is irrelevant to LIVE; the builder default is
    # the legacy class-constant contract.
    builder, state = _warm(None)
    assert state["parameterAuthority"] == {
        "source": "MicrostructureStateBuilder",
        "kind": "classConstant",
    }
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(
        state
    )["strategy"]
    assert strategy["featureContract"] == "LEGACY_CALLBACK_WINDOW"

    previous = dict(governance_state)
    try:
        governance_state["execution_enabled"] = True
        live_runtime = ExecutionRuntime()
        live_runtime.engine = SimpleNamespace(
            mode="live", get_risk_state=lambda: {}
        )
        result = live_runtime.evaluate_execution_permission(
            {"confidence": 0.30},
            {"executionAllowed": True},
            canonical_direction="LONG",
        )
        assert result == {
            "executionAllowed": False,
            "reason": "LOW_CONFIDENCE",
        }
    finally:
        governance_state.clear()
        governance_state.update(previous)


def test_trace_preserves_canonical_metadata_without_schema_break(tmp_path):
    runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()
    _, state = _warm(runtime)
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(
        state
    )["strategy"]
    snapshot = strategy_decision_snapshot(strategy)

    authority = snapshot["parameterAuthority"]
    assert authority["scope"] == "PAPER_ONLY"
    assert authority["canonicalScope"] == "PAPER"
    assert authority["parameterSetId"] == "strategy-params/PAPER"
    assert authority["authorityStatus"] == "PAPER_MIGRATION_BASELINE"
    assert authority["source"] == "MIGRATED_PAPER_CALIBRATION"
    assert "parameters" in authority
    assert snapshot.get("truncated") is not True
    assert len(json.dumps(snapshot).encode("utf-8")) < 8192
