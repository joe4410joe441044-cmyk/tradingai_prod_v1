import json
import math
from copy import deepcopy

from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder,
)
from backend.runtime.trading_trace import (
    sanitize_metadata,
    strategy_decision_snapshot,
)
from backend.strategy.MicrostructureEdgeStrategy import (
    MicrostructureEdgeStrategy,
)
from backend.strategy.normalized_parameters import (
    PAPER_NORMALIZED_CALIBRATION,
)


def paper_builder():
    return MicrostructureStateBuilder(
        parameter_set=deepcopy(PAPER_NORMALIZED_CALIBRATION)
    )


def observe(builder, price, timestamp):
    return builder.compute_strategy_momentum_features(price, timestamp)


def test_time_normalized_momentum_all_up_all_down_and_alternating():
    up = paper_builder()
    down = paper_builder()
    alternating = paper_builder()
    up_result = down_result = alternating_result = None
    for second in range(61):
        up_result = observe(up, 100.0 + second, 1_000.0 + second)
        down_result = observe(down, 100.0 - second, 1_000.0 + second)
        alternating_result = observe(
            alternating,
            100.0 + (second % 2),
            1_000.0 + second,
        )

    assert up_result["warmupReady"] is True
    assert up_result["momentumDirection"] == "UP"
    assert up_result["directionPurity"] == 1.0
    assert up_result["activityRatio"] == 1.0
    assert up_result["normalizedMomentum"] == 1.0
    assert down_result["momentumDirection"] == "DOWN"
    assert down_result["normalizedMomentum"] == 1.0
    assert alternating_result["directionPurity"] == 0.5
    assert alternating_result["normalizedMomentum"] == 0.5


def test_callback_rate_invariance_uses_one_sample_per_time_bucket():
    slow = paper_builder()
    fast = paper_builder()
    slow_result = fast_result = None
    for second in range(61):
        price = 100.0 + math.floor(second / 10)
        slow_result = observe(slow, price, 2_000.0 + second)
        for offset in (0.0, 0.2, 0.5, 0.9):
            fast_result = observe(
                fast,
                price,
                2_000.0 + second + offset,
            )

    for key in (
        "momentumDirection",
        "directionPurity",
        "activityRatio",
        "normalizedMomentum",
        "totalObservationSlots",
    ):
        assert fast_result[key] == slow_result[key]


def test_flat_heavy_market_separates_purity_from_activity():
    builder = paper_builder()
    result = None
    for second in range(61):
        price = 101.0 if second >= 30 else 100.0
        result = observe(builder, price, 3_000.0 + second)

    assert result["directionPurity"] == 1.0
    assert result["nonFlatMoves"] == 1
    assert result["activityRatio"] == round(1 / 60, 4)
    assert 0.12 < result["normalizedMomentum"] < 0.14


def test_candidate_direction_alignment_is_explicit():
    strategy = MicrostructureEdgeStrategy()
    state = {
        "parameterAuthority": deepcopy(PAPER_NORMALIZED_CALIBRATION),
        "normalizedMomentum": 0.4,
        "momentumDirection": "UP",
        "momentumWarmupReady": True,
        "directionPurity": 1.0,
        "activityRatio": 0.16,
        "buyPressure": 0.6,
        "sellPressure": 0.4,
    }
    aligned = strategy.evaluate_momentum_continuation(state)
    state["buyPressure"], state["sellPressure"] = 0.4, 0.6
    conflicting = strategy.evaluate_momentum_continuation(state)

    assert aligned["candidateDirection"] == "BUY"
    assert aligned["directionAligned"] is True
    assert conflicting["candidateDirection"] == "SELL"
    assert conflicting["directionAligned"] is False


def test_spread_and_liquidity_quality_are_cross_symbol_invariant():
    builder = paper_builder()
    assert builder.compute_normalized_spread_quality(0.20, 0.50) == 0.6
    assert builder.compute_normalized_spread_quality(0.60, 0.50) == 0.0
    assert builder.compute_normalized_liquidity_quality(900.0, 1000.0) == 0.9
    assert (
        builder.compute_normalized_liquidity_quality(9_000_000.0, 10_000_000.0)
        == 0.9
    )


def test_full_feature_contract_is_invariant_across_price_and_depth_scales():
    results = []
    for base_price, base_volume in (
        (65_000.0, 100_000.0),
        (0.50, 10_000_000.0),
        (0.0065, 12_000_000.0),
    ):
        builder = paper_builder()
        state = None
        for second in range(61):
            last_price = base_price * (1.0 + math.floor(second / 10) * 0.001)
            spread_pct = 0.20
            half_spread = last_price * (spread_pct / 100.0) / 2.0
            state = builder.build_microstructure_state({
                "buyVolume": base_volume * 0.55,
                "sellVolume": base_volume * 0.45,
                "bestBid": last_price - half_spread,
                "bestAsk": last_price + half_spread,
                "lastPrice": last_price,
                "pricePathDebug": {"marketUpdateTime": 10_000.0 + second},
            })
        results.append(state)

    comparable = [
        (
            state["momentumDirection"],
            state["directionPurity"],
            state["activityRatio"],
            state["normalizedMomentum"],
            state["normalizedSpreadQuality"],
            state["normalizedLiquidityQuality"],
        )
        for state in results
    ]
    assert comparable[0] == comparable[1] == comparable[2]


def test_warmup_is_fail_closed_but_eventually_ready():
    builder = paper_builder()
    first = observe(builder, 100.0, 4_000.0)
    assert first["warmupReady"] is False
    result = first
    for second in range(1, 21):
        result = observe(builder, 100.0 + second, 4_000.0 + second)
    assert result["warmupReady"] is True


def normalized_strategy_state():
    return {
        "parameterAuthority": deepcopy(PAPER_NORMALIZED_CALIBRATION),
        "imbalanceStrength": 0.2,
        "normalizedMomentum": 0.1,
        "momentumDirection": "UP",
        "momentumWarmupReady": True,
        "directionPurity": 1.0,
        "activityRatio": 0.01,
        "normalizedSpreadQuality": 0.5,
        "normalizedLiquidityQuality": 1.0,
        "spread": 0.0001,
        "spreadVolatility": 0.0,
        "buyPressure": 0.6,
        "sellPressure": 0.4,
        "absorptionDetected": False,
        "stagnantHeavyFlow": False,
        "fakePressureDetected": False,
        "liquidityCalibrationReady": True,
        "liquidityInstabilityDebug": {
            "totalVolume": 1000.0,
            "spreadPct": 0.25,
            "parameterAuthority": deepcopy(PAPER_NORMALIZED_CALIBRATION),
            "detectorDetails": {},
        },
    }


def test_paper_gate_contract_uses_one_composite_gate_and_diagnostic_confidence():
    result = MicrostructureEdgeStrategy().process_microstructure_strategy(
        normalized_strategy_state()
    )["strategy"]
    condition_codes = {
        condition["code"]
        for condition in result["entryReadiness"]["conditions"]
    }

    assert result["edge"] == 0.375
    assert result["confidence"] < 0.23
    assert result["executionAllowed"] is True
    assert result["direction"] == "LONG"
    assert "COMPOSITE_SCORE" in condition_codes
    assert "CONFIDENCE_DIAGNOSTIC" in condition_codes
    assert "EDGE" not in condition_codes
    assert "CONFIDENCE" not in condition_codes
    assert result["hardGateResults"] == {
        "marketSpreadSafety": True,
        "liquiditySafety": True,
        "momentumWarmup": True,
        "directionConsistency": True,
        "compositeDecisionScore": True,
    }


def test_live_default_keeps_legacy_momentum_and_gate_contract():
    builder = MicrostructureStateBuilder()
    builder.compute_momentum_persistence(100.0)
    for _ in range(19):
        builder.compute_momentum_persistence(100.0)
    assert builder.compute_momentum_persistence(101.0) == 0.05

    state = normalized_strategy_state()
    state.pop("parameterAuthority")
    state["momentumPersistence"] = 1.0
    state["spreadQuality"] = 1.0
    state["liquidityQuality"] = 1.0
    result = MicrostructureEdgeStrategy().process_microstructure_strategy(state)[
        "strategy"
    ]
    codes = {item["code"] for item in result["entryReadiness"]["conditions"]}
    assert result["featureContract"] == "LEGACY_CALLBACK_WINDOW"
    assert {"MOMENTUM", "PRESSURE_ALIGNMENT", "EDGE", "CONFIDENCE"} <= codes


def test_trace_contains_normalized_features_within_size_and_sanitizes_secrets():
    state = MicrostructureEdgeStrategy().process_microstructure_strategy(
        normalized_strategy_state()
    )["strategy"]
    snapshot = strategy_decision_snapshot(state)
    traced = snapshot["strategy"]

    for key in (
        "momentumDirection",
        "directionPurity",
        "activityRatio",
        "normalizedMomentum",
        "directionAligned",
        "normalizedSpreadQuality",
        "normalizedLiquidityQuality",
        "hardGateResults",
        "edge",
        "confidence",
    ):
        assert key in traced
    assert snapshot.get("truncated") is not True
    assert len(json.dumps(snapshot).encode("utf-8")) < 8192
    assert sanitize_metadata({"apiKey": "secret", "safe": 1}) == {"safe": 1}
