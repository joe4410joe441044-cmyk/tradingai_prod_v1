from copy import deepcopy
from types import SimpleNamespace

from backend.aggregation.MicrostructureStateBuilder import MicrostructureStateBuilder
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import governance_state
from backend.runtime.trading_trace import strategy_decision_snapshot
from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy
from backend.strategy.normalized_parameters import (
    PAPER_NORMALIZED_CALIBRATION,
    paper_calibration_for_mode,
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


def warmed_builder(mid_price=100.0, total_volume=1000.0):
    builder = MicrostructureStateBuilder(
        parameter_set=deepcopy(PAPER_NORMALIZED_CALIBRATION)
    )
    for _ in range(20):
        builder.build_microstructure_state(packet(mid_price, total_volume))
    return builder


def confidence_state(parameter_authority=None):
    state = {
        "imbalanceStrength": 1.0,
        "momentumPersistence": 1.0,
        "spreadQuality": 1.0,
        "liquidityQuality": 1.0,
        "spread": 0.0001,
        "spreadVolatility": 0.1,
        "buyPressure": 0.8,
        "sellPressure": 0.2,
        "absorptionDetected": False,
        "stagnantHeavyFlow": False,
        "fakePressureDetected": False,
        "liquidityCalibrationReady": True,
        "liquidityInstabilityDebug": {
            "totalVolume": 100000.0,
            "spreadPct": 0.10,
        },
    }
    if parameter_authority is not None:
        state["parameterAuthority"] = parameter_authority
    return state


def test_normalized_absorption_uses_prior_rolling_p90():
    builder = warmed_builder()
    state = builder.build_microstructure_state(packet(100.0, 1000.0))
    details = state["liquidityInstabilityDebug"]["detectorDetails"]

    assert details["calibrationReady"] is True
    assert details["historyCount"] == 20
    assert details["absorption"]["thresholdRollingVolume"] == 1000.0
    assert details["absorption"]["totalVolumeOperator"] == ">="
    assert state["absorptionDetected"] is True


def test_normalized_detectors_are_symbol_scale_invariant():
    low = warmed_builder(mid_price=0.0065, total_volume=12_000_000.0)
    high = warmed_builder(mid_price=65_000.0, total_volume=120_000.0)

    low_state = low.build_microstructure_state(
        packet(0.0065, 13_500_000.0, spread_pct=0.20)
    )
    high_state = high.build_microstructure_state(
        packet(65_000.0, 135_000.0, spread_pct=0.20)
    )

    assert low_state["absorptionDetected"] == high_state["absorptionDetected"]
    assert low_state["stagnantHeavyFlow"] == high_state["stagnantHeavyFlow"]
    assert low_state["fakePressureDetected"] == high_state["fakePressureDetected"]
    strategy = MicrostructureEdgeStrategy()
    assert strategy.evaluate_spread_safety(low_state)["spreadSafe"] is True
    assert strategy.evaluate_spread_safety(high_state)["spreadSafe"] is True


def test_price_delta_is_percent_normalized_and_strict_at_boundary():
    below = warmed_builder()
    below_state = below.build_microstructure_state(
        packet(100.099, 1100.0, last_price=100.099)
    )
    above = warmed_builder()
    above_state = above.build_microstructure_state(
        packet(100.101, 1100.0, last_price=100.101)
    )

    below_absorption = below_state["liquidityInstabilityDebug"][
        "detectorDetails"
    ]["absorption"]
    above_absorption = above_state["liquidityInstabilityDebug"][
        "detectorDetails"
    ]["absorption"]
    assert below_absorption["observedAbsPriceDeltaPct"] < 0.10
    assert below_absorption["absPriceDeltaConditionPassed"] is True
    assert above_absorption["observedAbsPriceDeltaPct"] > 0.10
    assert above_absorption["absPriceDeltaConditionPassed"] is False


def test_stagnant_spread_is_percent_normalized_and_strict():
    narrow = warmed_builder(total_volume=100_000.0)
    narrow_state = narrow.build_microstructure_state(
        packet(100.0, 110_000.0, spread_pct=0.49)
    )
    wide = warmed_builder(total_volume=100_000.0)
    wide_state = wide.build_microstructure_state(
        packet(100.0, 110_000.0, spread_pct=0.51)
    )

    assert narrow_state["stagnantHeavyFlow"] is False
    assert wide_state["stagnantHeavyFlow"] is True
    strategy = MicrostructureEdgeStrategy()
    assert strategy.evaluate_spread_safety(narrow_state)["spreadSafe"] is True
    assert strategy.evaluate_spread_safety(wide_state)["spreadSafe"] is False


def test_normalized_cold_start_is_fail_closed_without_false_detector():
    builder = MicrostructureStateBuilder(
        parameter_set=deepcopy(PAPER_NORMALIZED_CALIBRATION)
    )
    state = builder.build_microstructure_state(packet(0.1, 100_000.0))
    result = MicrostructureEdgeStrategy().process_microstructure_strategy(state)

    assert state["liquidityCalibrationReady"] is False
    assert state["absorptionDetected"] is False
    assert result["strategy"]["executionAllowed"] is False
    assert result["strategy"]["suppressionReason"] == "LIQUIDITY_INSTABILITY"
    assert "normalizedCalibrationWarmup" in result["strategy"][
        "liquidityInstabilityDebug"
    ]["triggeredReasons"]


def test_paper_confidence_boundary_and_default_separation():
    strategy = MicrostructureEdgeStrategy()
    safe = {"spreadSafe": True}
    liquid = {"liquiditySafe": True}
    momentum = {"momentumValid": True}

    assert strategy.evaluate_execution_suppression(
        {"edgeScore": 0.60, "confidence": 0.23},
        safe,
        liquid,
        momentum,
        minimum_confidence=0.23,
    )["executionAllowed"] is True
    assert strategy.evaluate_execution_suppression(
        {"edgeScore": 0.60, "confidence": 0.2299},
        safe,
        liquid,
        momentum,
        minimum_confidence=0.23,
    )["suppressionReason"] == "LOW_CONFIDENCE"
    assert strategy.evaluate_execution_suppression(
        {"edgeScore": 0.60, "confidence": 0.23},
        safe,
        liquid,
        momentum,
    )["suppressionReason"] == "LOW_CONFIDENCE"

    paper = strategy.process_microstructure_strategy(
        confidence_state(deepcopy(PAPER_NORMALIZED_CALIBRATION))
    )["strategy"]
    default = strategy.process_microstructure_strategy(
        confidence_state()
    )["strategy"]
    paper_condition = next(
        item for item in paper["entryReadiness"]["conditions"]
        if item["code"] == "CONFIDENCE_DIAGNOSTIC"
    )
    default_condition = next(
        item for item in default["entryReadiness"]["conditions"]
        if item["code"] == "CONFIDENCE"
    )
    assert paper_condition["threshold"] is None
    assert paper_condition["status"] == "DIAGNOSTIC"
    assert default_condition["threshold"] == 0.60


def test_execution_runtime_honors_calibration_only_for_paper():
    previous = dict(governance_state)
    strategy_state = {
        "confidence": 0.30,
        "parameterAuthority": deepcopy(PAPER_NORMALIZED_CALIBRATION),
    }
    governance_result = {"executionAllowed": True}
    try:
        governance_state["execution_enabled"] = True
        paper = ExecutionRuntime()
        paper.engine = SimpleNamespace(mode="paper", get_risk_state=lambda: {})
        live = ExecutionRuntime()
        live.engine = SimpleNamespace(mode="live", get_risk_state=lambda: {})

        assert paper.evaluate_execution_permission(
            strategy_state,
            governance_result,
            canonical_direction="LONG",
        )["executionAllowed"] is True
        assert live.evaluate_execution_permission(
            strategy_state,
            governance_result,
            canonical_direction="LONG",
        )["reason"] == "LOW_CONFIDENCE"
    finally:
        governance_state.clear()
        governance_state.update(previous)


def test_parameter_authority_has_name_value_unit_authority_and_description():
    for name, parameter in PAPER_NORMALIZED_CALIBRATION["parameters"].items():
        assert name
        assert set(parameter) == {"value", "unit", "authority", "description"}
        assert parameter["unit"]
        assert parameter["authority"]
        assert parameter["description"]

    paper = paper_calibration_for_mode("paper")
    assert paper == PAPER_NORMALIZED_CALIBRATION
    assert paper is not PAPER_NORMALIZED_CALIBRATION
    assert paper_calibration_for_mode("live") is None
    assert paper_calibration_for_mode(None) is None


def test_normalized_authority_and_thresholds_are_present_in_trace_snapshot():
    builder = warmed_builder(mid_price=0.0065, total_volume=12_000_000.0)
    state = builder.build_microstructure_state(
        packet(0.0065, 13_500_000.0, spread_pct=0.20)
    )
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(
        state
    )["strategy"]
    snapshot = strategy_decision_snapshot(strategy)

    assert snapshot.get("truncated") is not True
    assert snapshot["detectors"]["calibrationReady"] is True
    assert snapshot["strategy"]["minimumConfidence"] == 0.23
    assert snapshot["parameterAuthority"]["scope"] == "PAPER_ONLY"
    absorption = snapshot["detectors"]["details"]["absorption"]
    assert absorption["thresholdVolumePercentile"] == 0.90
    assert absorption["thresholdMaxPriceDeltaPct"] == 0.10
