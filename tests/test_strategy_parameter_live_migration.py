"""E-PARAM-3 focused tests: LIVE authority + Cycle 10 exit migration.

These tests prove the LIVE canonical migration is behavior-neutral:

- LIVE resolves its own isolated canonical snapshot with the named
  ``LIVE_CLASS_CONSTANT_BASELINE`` fallback.
- PAPER and LIVE scopes never fall back to one another.
- LIVE keeps the legacy ``LEGACY_CALLBACK_WINDOW`` feature contract and the
  legacy detector mathematics.
- Migrated LIVE strategy gates and the Cycle 10 exit thresholds remain
  behavior-equivalent to the class constants.
- Exit thresholds follow the parameter revision captured at entry
  (snapshot-at-entry) and later revisions cannot mutate an existing trade.
"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder,
)
from backend.bot_manager.bot_manager import BotManager
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import governance_state
from backend.strategy.MicrostructureEdgeStrategy import (
    MicrostructureEdgeStrategy,
)
from backend.strategy.normalized_parameters import (
    PAPER_NORMALIZED_CALIBRATION,
    parameter_value,
)
from backend.strategy.parameters.baselines import (
    LIVE_BASELINE_EXACT_KEYS,
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
    LIVE_RUNTIME_SCOPE,
    CanonicalParameterResolver,
    RuntimeAuthorityStatus,
)
from backend.strategy.parameters.store import StrategyParameterStore


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _set(scope, parameter_set_id, values, revision=1):
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyParameterSet(
        parameterSetId=parameter_set_id,
        schemaVersion=1,
        scope=scope,
        status=ParameterStatus.ACTIVE,
        createdAt=moment,
        updatedAt=moment,
        source=ParameterSource.PARAMETER_SETTINGS,
        parameters=dict(values),
        effectiveFrom=None,
        configuredRevision=revision,
        effectiveRevision=revision,
    )


def _live_set(**overrides):
    values = dict(LIVE_CLASS_CONSTANT_BASELINE.values)
    values.update(overrides)
    return _set(ParameterScope.LIVE, "strategy-params/LIVE", values, 9)


def _paper_set(**overrides):
    values = dict(PAPER_MIGRATION_BASELINE.values)
    values.update(overrides)
    return _set(ParameterScope.PAPER, "strategy-params/PAPER", values, 7)


def packet(mid_price, total_volume, *, spread_pct=0.20, last_price=None):
    half_spread = mid_price * (spread_pct / 100.0) / 2.0
    return {
        "buyVolume": total_volume * 0.55,
        "sellVolume": total_volume * 0.45,
        "bestBid": mid_price - half_spread,
        "bestAsk": mid_price + half_spread,
        "lastPrice": mid_price if last_price is None else last_price,
    }


def _warm(
    parameter_set,
    *,
    mid_price=100.0,
    total_volume=1000.0,
    count=20,
    spread_pct=0.20,
):
    builder = MicrostructureStateBuilder(parameter_set=parameter_set)
    state = None
    for _ in range(count):
        state = builder.build_microstructure_state(
            packet(mid_price, total_volume, spread_pct=spread_pct)
        )
    return builder, state


def _exit_state(**overrides):
    value = {
        "symbol": "BTCUSDT",
        "timestamp": 1001.5,
        "liquidityQuality": 0.5,
        "spreadQuality": 0.9,
        "spreadVolatility": 0.0,
        "spread": 0.0001,
        "momentumPersistence": 0.9,
        "normalizedLiquidityQuality": 0.9,
        "normalizedSpreadQuality": 0.9,
        "normalizedMomentum": 0.9,
        "momentumDirection": "UP",
        "momentumWarmupReady": True,
        "buyPressure": 0.6,
        "sellPressure": 0.4,
        "absorptionDetected": False,
        "stagnantHeavyFlow": False,
        "fakePressureDetected": False,
        "liquidityCalibrationReady": True,
    }
    value.update(overrides)
    return value


def _exit_position(**overrides):
    value = {
        "symbol": "BTCUSDT",
        "positionSide": "BUY",
        "entryPrice": 100.0,
        "currentPrice": 100.0,
        "openedAt": 1000.0,
        "evaluatedAt": 1001.5,
    }
    value.update(overrides)
    return value


def _snapshot(**params):
    return {
        "scope": LIVE_RUNTIME_SCOPE,
        "parameters": {
            name: {"value": value} for name, value in params.items()
        },
    }


# ---------------------------------------------------------------------------
# Resolver / scope isolation / fallback
# ---------------------------------------------------------------------------


def test_live_resolver_scope_and_fallback(tmp_path):
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live()

    assert snapshot.scope == LIVE_RUNTIME_SCOPE == "LIVE_ONLY"
    assert snapshot.canonicalScope == "LIVE"
    assert snapshot.parameterSetId == "strategy-params/LIVE"
    assert snapshot.authorityStatus == (
        RuntimeAuthorityStatus.LIVE_CLASS_CONSTANT_BASELINE.value
    )
    assert snapshot.storeStatus == "MISSING"
    assert snapshot.source == "MIGRATED_CLASS_CONSTANT"
    assert snapshot.featureContract == "LEGACY_CALLBACK_WINDOW"
    assert snapshot.configuredRevision == 1
    assert snapshot.effectiveRevision == 1

    runtime = snapshot.to_runtime_dict()
    assert runtime["scope"] == "LIVE_ONLY"
    assert runtime["canonicalScope"] == "LIVE"
    # Only the proven exact class-constant equivalents are exposed.
    assert set(runtime["parameters"]) == set(LIVE_BASELINE_EXACT_KEYS)
    assert "maximumStrategySpreadPct" not in runtime["parameters"]


def test_live_missing_and_corrupt_store_fall_back_observably(tmp_path):
    assert CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().authorityStatus == (
        "LIVE_CLASS_CONSTANT_BASELINE"
    )

    directory = tmp_path / "strategy_parameters"
    directory.mkdir()
    target = directory / "strategy-params__LIVE.json"
    target.write_text("{not-valid-json")
    target.chmod(0o600)

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live()
    assert snapshot.authorityStatus == "LIVE_CLASS_CONSTANT_BASELINE"
    assert snapshot.storeStatus == "CORRUPT"
    assert snapshot.source == "MIGRATED_CLASS_CONSTANT"


def test_scope_isolation_no_cross_fallback(tmp_path):
    store = StrategyParameterStore(tmp_path)
    assert store.save(
        _paper_set(minimumCompositeScore=0.99)
    ).status.value == "SAVED"

    live_snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live()
    assert live_snapshot.authorityStatus == "LIVE_CLASS_CONSTANT_BASELINE"
    assert live_snapshot.parameters["minimumCompositeScore"] == 0.55

    store.save(_live_set(minimumCompositeScore=0.88))
    paper_snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    # The PAPER store is unaffected by the LIVE set (no cross-scope leakage).
    assert paper_snapshot.authorityStatus == "PERSISTED"
    assert paper_snapshot.parameters["minimumCompositeScore"] == 0.99

    empty = tmp_path / "empty"
    empty.mkdir()
    baseline_paper = CanonicalParameterResolver(
        base_directory=empty
    ).resolve_paper()
    assert baseline_paper.authorityStatus == "PAPER_MIGRATION_BASELINE"
    assert baseline_paper.parameters["minimumCompositeScore"] == 0.34


def test_live_persisted_authority(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_live_set(minimumCompositeScore=0.77))

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live()
    assert snapshot.authorityStatus == "PERSISTED"
    assert snapshot.storeStatus == "VALID"
    assert snapshot.source == "PARAMETER_SETTINGS"
    assert snapshot.configuredRevision == 9
    assert snapshot.effectiveRevision == 9
    assert snapshot.parameters["minimumCompositeScore"] == 0.77
    assert (
        snapshot.to_runtime_dict()["parameters"]["minimumCompositeScore"][
            "value"
        ]
        == 0.77
    )


def test_live_resolved_value_equivalence(tmp_path):
    strategy = MicrostructureEdgeStrategy()
    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live()

    assert snapshot.parameters["minimumCompositeScore"] == (
        strategy.MIN_EDGE_SCORE
    )
    assert snapshot.parameters["minimumStrategyConfidence"] == (
        strategy.MIN_CONFIDENCE
    )
    assert snapshot.parameters["minimumHoldMs"] == strategy.MIN_HOLD_MS
    assert snapshot.parameters["maximumHoldMs"] == strategy.MAX_HOLD_MS
    assert snapshot.parameters["exitMomentumMinimum"] == (
        strategy.EXIT_MOMENTUM_MIN
    )
    assert snapshot.parameters["exitLiquidityQualityMinimum"] == (
        strategy.EXIT_LIQUIDITY_QUALITY_MIN
    )
    assert snapshot.parameters["exitSpreadQualityMinimum"] == (
        strategy.EXIT_SPREAD_QUALITY_MIN
    )


# ---------------------------------------------------------------------------
# LIVE feature / detector / strategy equivalence
# ---------------------------------------------------------------------------


def test_live_feature_builder_equivalence(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()

    _, legacy_state = _warm(None)
    _, live_state = _warm(live_runtime)

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
        "spread",
        "spreadVolatility",
        "spreadQuality",
        "liquidityQuality",
        "buyPressure",
        "sellPressure",
    ):
        assert legacy_state[key] == live_state[key], key

    assert live_state["parameterAuthority"]["scope"] == "LIVE_ONLY"
    assert live_state["parameterAuthority"]["canonicalScope"] == "LIVE"
    # The legacy detector mathematics is unchanged (class-constant thresholds).
    assert (
        live_state["liquidityInstabilityDebug"]["detectorDetails"]
        == legacy_state["liquidityInstabilityDebug"]["detectorDetails"]
    )
    assert (
        live_state["strategyMomentumFeatures"]
        == legacy_state["strategyMomentumFeatures"]
        == {}
    )


def test_live_feature_contract_unchanged(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()
    _, live_state = _warm(live_runtime)

    strategy_state = MicrostructureEdgeStrategy().process_microstructure_strategy(
        live_state
    )["strategy"]
    assert strategy_state["featureContract"] == "LEGACY_CALLBACK_WINDOW"
    assert strategy_state["minimumCompositeScore"] == 0.55
    assert strategy_state["minimumConfidence"] == 0.60


def test_live_strategy_equivalence(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()

    _, legacy_state = _warm(None)
    _, live_state = _warm(live_runtime)

    strategy = MicrostructureEdgeStrategy()
    legacy = strategy.process_microstructure_strategy(legacy_state)["strategy"]
    live = strategy.process_microstructure_strategy(live_state)["strategy"]

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
    ):
        assert legacy[key] == live[key], key


def test_live_spread_equivalence(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()

    _, legacy_state = _warm(None)
    _, live_state = _warm(live_runtime)
    _, legacy_wide = _warm(None, mid_price=100.0, spread_pct=2.0)
    _, live_wide = _warm(live_runtime, mid_price=100.0, spread_pct=2.0)

    strategy = MicrostructureEdgeStrategy()
    assert strategy.evaluate_spread_safety(
        legacy_state
    ) == strategy.evaluate_spread_safety(live_state)
    assert strategy.evaluate_spread_safety(
        legacy_wide
    ) == strategy.evaluate_spread_safety(live_wide)
    # The canonical LIVE authority does not switch the absolute-price spread
    # threshold onto the PAPER percent semantics.
    assert strategy.evaluate_spread_safety(live_wide)["spreadSafe"] is False


def test_live_confidence_equivalence(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()

    previous = dict(governance_state)
    try:
        governance_state["execution_enabled"] = True
        runtime = ExecutionRuntime()
        runtime.engine = SimpleNamespace(
            mode="live", get_risk_state=lambda: {}
        )

        def evaluate(confidence, authority):
            return runtime.evaluate_execution_permission(
                {"confidence": confidence, "parameterAuthority": authority},
                {"executionAllowed": True},
                canonical_direction="LONG",
            )

        for confidence in (0.60, 0.5999, 0.30):
            assert evaluate(confidence, None) == evaluate(
                confidence, live_runtime
            )

        assert evaluate(0.60, live_runtime)["executionAllowed"] is True
        assert evaluate(0.5999, live_runtime)["reason"] == "LOW_CONFIDENCE"
        # A PAPER authority must never leak into the LIVE confidence floor.
        assert evaluate(
            0.30, deepcopy(PAPER_NORMALIZED_CALIBRATION)
        )["reason"] == "LOW_CONFIDENCE"
    finally:
        governance_state.clear()
        governance_state.update(previous)


# ---------------------------------------------------------------------------
# Cycle 10 exit thresholds
# ---------------------------------------------------------------------------


def test_exit_thresholds_read_canonical_authority(tmp_path):
    strategy = MicrostructureEdgeStrategy()
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()
    _, live_state = _warm(live_runtime)

    thresholds = strategy._exit_thresholds(live_state, None)
    assert thresholds == {
        "minimumHoldMs": strategy.MIN_HOLD_MS,
        "maximumHoldMs": strategy.MAX_HOLD_MS,
        "exitMomentumMinimum": strategy.EXIT_MOMENTUM_MIN,
        "exitLiquidityQualityMinimum": strategy.EXIT_LIQUIDITY_QUALITY_MIN,
        "exitSpreadQualityMinimum": strategy.EXIT_SPREAD_QUALITY_MIN,
    }

    paper_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()
    _, paper_state = _warm(paper_runtime)
    assert strategy._exit_thresholds(paper_state, None) == thresholds


def test_paper_exit_equivalence(tmp_path):
    paper_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper().to_runtime_dict()

    strategy = MicrostructureEdgeStrategy()
    for scenario in (
        {},
        {"liquidityCalibrationReady": False},
        {"normalizedLiquidityQuality": 0.2},
        {"normalizedSpreadQuality": 0.2},
        {"normalizedMomentum": 0.3},
        {"momentumDirection": "DOWN"},
    ):
        canonical = strategy.evaluate_exit(
            _exit_state(parameterAuthority=paper_runtime, **scenario),
            _exit_position(),
        )
        legacy = strategy.evaluate_exit(
            _exit_state(
                parameterAuthority=deepcopy(PAPER_NORMALIZED_CALIBRATION),
                **scenario,
            ),
            _exit_position(),
        )
        assert canonical.to_dict() == legacy.to_dict()

    # The canonical PAPER snapshot must reproduce the same thresholds.
    _, paper_state = _warm(paper_runtime)
    assert strategy._exit_thresholds(paper_state, None) == (
        strategy._exit_thresholds(_exit_state(), None)
    )


def test_live_exit_equivalence(tmp_path):
    live_runtime = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_live().to_runtime_dict()

    strategy = MicrostructureEdgeStrategy()
    for scenario in (
        {},
        {"liquidityCalibrationReady": False},
        {"liquidityQuality": 0.2},
        {"spreadQuality": 0.2},
        {"momentumPersistence": 0.3},
        {"openedAt": 1000.0, "evaluatedAt": 1003.5},
    ):
        _, live_state = _warm(live_runtime)
        live_state.update(scenario)
        live_state["timestamp"] = 1001.5 if "evaluatedAt" not in scenario else 1003.5
        with_authority = strategy.evaluate_exit(
            live_state, _exit_position(**scenario)
        )
        _, legacy_state = _warm(None)
        legacy_state.update(scenario)
        legacy_state["timestamp"] = live_state["timestamp"]
        without_authority = strategy.evaluate_exit(
            legacy_state, _exit_position(**scenario)
        )
        assert with_authority.to_dict() == without_authority.to_dict()


# ---------------------------------------------------------------------------
# Snapshot at entry
# ---------------------------------------------------------------------------


def test_exit_snapshot_at_entry_is_immutable(tmp_path):
    strategy = MicrostructureEdgeStrategy()
    revision_one = _snapshot(
        minimumHoldMs=500,
        maximumHoldMs=3000,
        exitMomentumMinimum=0.40,
        exitLiquidityQualityMinimum=0.30,
        exitSpreadQualityMinimum=0.30,
    )
    revision_two = _snapshot(
        minimumHoldMs=500,
        maximumHoldMs=3000,
        exitMomentumMinimum=0.40,
        exitLiquidityQualityMinimum=0.90,
        exitSpreadQualityMinimum=0.30,
    )

    state = _exit_state()

    # R1 position: 0.50 is above the R1 liquidity floor, so it holds.
    r1_position = _exit_position(parameterSnapshot=revision_one)
    first = strategy.evaluate_exit(state, r1_position)
    assert first.decision == "HOLD"

    # Configured/effective revision advances to R2.
    r2_position = _exit_position(parameterSnapshot=revision_two)
    assert strategy.evaluate_exit(state, r2_position).reason == (
        "LIQUIDITY_DETERIORATION"
    )

    # The already-open R1 trade still evaluates with R1 after R2 exists.
    repeated = strategy.evaluate_exit(state, r1_position)
    assert repeated.decision == "HOLD"
    assert r1_position["parameterSnapshot"]["parameters"][
        "exitLiquidityQualityMinimum"
    ]["value"] == 0.30


def test_entry_snapshot_binds_to_position_in_runtime(tmp_path):
    manager = BotManager()
    snapshot = _snapshot(
        minimumHoldMs=500,
        maximumHoldMs=3000,
        exitMomentumMinimum=0.40,
        exitLiquidityQualityMinimum=0.30,
        exitSpreadQualityMinimum=0.30,
    )
    manager.engine = SimpleNamespace(
        actual_position={"parameter_snapshot": snapshot}
    )
    received = {}

    def fake_evaluate(microstructure_state, position_info):
        received["position_info"] = position_info
        return "OK"

    evaluator = manager._build_snapshot_aware_exit_evaluator(fake_evaluate)
    assert evaluator(_exit_state(), _exit_position()) == "OK"
    assert received["position_info"]["parameterSnapshot"] == snapshot

    # An explicit per-call snapshot is never overwritten.
    explicit = {"scope": "LIVE_ONLY", "parameters": {}}
    evaluator(_exit_state(), _exit_position(parameterSnapshot=explicit))
    assert received["position_info"]["parameterSnapshot"] == explicit


def test_safety_exit_precedence_preserved(tmp_path):
    from Bot.engine.execution_engine import ExecutionEngine
    from backend.portfolio.portfolio_manager import PortfolioManager
    import time

    strategy = MicrostructureEdgeStrategy()
    engine = ExecutionEngine(portfolio=PortfolioManager(initial_balance=100.0))
    engine.symbol = "BTCUSDT"
    engine.mode = "paper"
    engine.status = "RUNNING"
    manager = BotManager()
    manager.engine = engine
    engine.set_exit_evaluator(
        manager._build_snapshot_aware_exit_evaluator(strategy.evaluate_exit)
    )
    engine.actual_position = {
        "state": "OPEN",
        "side": "BUY",
        "entry_price": 100.0,
        "qty": 1000,
        "coin_qty": 1.0,
        "multiplier": 0.001,
        "entry_time": time.time() - 0.1,
        "trace_id": "trace-safety",
        "sl": 99.0,
        "tp": 102.0,
        # A canonical snapshot whose strategy exit would otherwise fire.
        "parameter_snapshot": _snapshot(
            minimumHoldMs=1,
            maximumHoldMs=1,
            exitMomentumMinimum=0.99,
            exitLiquidityQualityMinimum=0.99,
            exitSpreadQualityMinimum=0.99,
        ),
    }
    engine.portfolio.open_position("BTCUSDT", 100.0, 1.0, "BUY")

    engine.on_price(
        "BTCUSDT",
        98.0,
        microstructure_state=_exit_state(momentumDirection="DOWN"),
    )

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    # SL retains precedence over any canonical strategy exit threshold.
    assert engine.trade_history[0]["reason"] == "SL"
