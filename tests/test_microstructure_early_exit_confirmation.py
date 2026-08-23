"""Tests for early exit confirmation mechanism."""

from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy

from tests.test_microstructure_edge_exit_lifecycle import state, position


def test_first_pre_min_hold_liquidity_deterioration_holds():
    strategy = MicrostructureEdgeStrategy()

    decision = strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.2),
        position(openedAt=1000.0, evaluatedAt=1000.2),
    )

    assert decision.decision == "HOLD"
    assert abs(decision.holding_duration_ms - 200.0) < 0.01  # Less than MIN_HOLD_MS (500)
    assert decision.reason is None


def test_required_consecutive_deterioration_confirmed():
    strategy = MicrostructureEdgeStrategy()

    # First observation - not confirmed
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.2),
        position(openedAt=1000.0, evaluatedAt=1000.2),
    )

    # Second observation - confirmed
    decision = strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.3),
        position(openedAt=1000.0, evaluatedAt=1000.3),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "LIQUIDITY_DETERIORATION"


def test_deterioration_recovery_resets_confirmation():
    strategy = MicrostructureEdgeStrategy()

    # First observation - not confirmed
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.2),
        position(openedAt=1000.0, evaluatedAt=1000.2),
    )

    # Recovery
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=True, timestamp=1000.3),
        position(openedAt=1000.0, evaluatedAt=1000.3),
    )

    # Deterioration again - should not inherit old confirmation
    decision = strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.4),
        position(openedAt=1000.0, evaluatedAt=1000.4),
    )

    assert decision.decision == "HOLD"


def test_deterioration_recovery_re_deterioration():
    strategy = MicrostructureEdgeStrategy()

    # First observation
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.2),
        position(openedAt=1000.0, evaluatedAt=1000.2),
    )

    # Recovery
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=True, timestamp=1000.3),
        position(openedAt=1000.0, evaluatedAt=1000.3),
    )

    # Deterioration again - first observation
    strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.4),
        position(openedAt=1000.0, evaluatedAt=1000.4),
    )

    # Deterioration again - second observation
    decision = strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1000.5),
        position(openedAt=1000.0, evaluatedAt=1000.5),
    )

    assert decision.decision == "EXIT"


def test_499ms_behavior():
    strategy = MicrostructureEdgeStrategy()

    strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.499),
        position(openedAt=1000.0, evaluatedAt=1000.499),
    )

    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.499),
        position(openedAt=1000.0, evaluatedAt=1000.499),
    )

    assert decision.decision == "EXIT"


def test_500ms_behavior():
    strategy = MicrostructureEdgeStrategy()

    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.5),
        position(openedAt=1000.0, evaluatedAt=1000.5),
    )

    assert decision.decision == "EXIT"


def test_501ms_behavior():
    strategy = MicrostructureEdgeStrategy()

    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.501),
        position(openedAt=1000.0, evaluatedAt=1000.501),
    )

    assert decision.decision == "EXIT"


def test_new_position_no_confirmation_state():
    strategy = MicrostructureEdgeStrategy()

    strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.2),
        position(symbol="BTCUSDT", openedAt=1000.0, evaluatedAt=1000.2),
    )

    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.2),
        position(symbol="ETHUSDT", openedAt=1000.0, evaluatedAt=1000.2),
    )

    assert decision.decision == "HOLD"


def test_symbol_mismatch_no_confirmation():
    strategy = MicrostructureEdgeStrategy()

    decision = strategy.evaluate_exit(
        state(symbol="ETHUSDT", normalizedLiquidityQuality=0.2, timestamp=1000.2),
        position(symbol="BTCUSDT", openedAt=1000.0, evaluatedAt=1000.2),
    )

    assert decision.decision == "HOLD"
    assert decision.reason == "SYMBOL_MISMATCH"


def test_reset_confirmation_state():
    strategy = MicrostructureEdgeStrategy()

    strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.2),
        position(symbol="BTCUSDT", openedAt=1000.0, evaluatedAt=1000.2),
    )

    strategy._reset_confirmation_state("BTCUSDT")

    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1000.3),
        position(symbol="BTCUSDT", openedAt=1000.0, evaluatedAt=1000.3),
    )

    assert decision.decision == "HOLD"