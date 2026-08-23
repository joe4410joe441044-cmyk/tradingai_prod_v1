"""Regression tests for the Microstructure Edge exit lifecycle.

Covers the deterministic typed ExitDecision contract, side-aware evaluation,
symbol / freshness safety, holding-time authority, and the ExecutionEngine
integration (single close, existing TP/SL preservation, PAPER close path,
FLAT transition, realized PnL).
"""

import time
from copy import deepcopy
from unittest.mock import Mock

from Bot.engine.execution_engine import ExecutionEngine
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy
from backend.strategy.normalized_parameters import PAPER_NORMALIZED_CALIBRATION


# ============================================================
# Helpers
# ============================================================

def state(**overrides):
    value = {
        "parameterAuthority": deepcopy(PAPER_NORMALIZED_CALIBRATION),
        "normalizedMomentum": 0.8,
        "momentumDirection": "UP",
        "momentumWarmupReady": True,
        "directionPurity": 1.0,
        "activityRatio": 0.5,
        "normalizedSpreadQuality": 0.9,
        "normalizedLiquidityQuality": 0.9,
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
            "spreadPct": 0.10,
        },
    }
    value.update(overrides)
    return value


def position(**overrides):
    value = {
        "symbol": "BTCUSDT",
        "positionSide": "BUY",
        "entryPrice": 100.0,
        "currentPrice": 100.0,
        "openedAt": 1000.0,
        "evaluatedAt": 1001.5,
        "traceId": "trace-exit-1",
    }
    value.update(overrides)
    return value


def paper_engine():
    portfolio = PortfolioManager(initial_balance=100.0)
    engine = ExecutionEngine(portfolio=portfolio)
    engine.symbol = "BTCUSDT"
    engine.mode = "paper"
    engine.status = "RUNNING"
    return engine


def open_paper_position(
    engine,
    entry=100.0,
    side="BUY",
    coin_qty=1.0,
    entry_time=None,
    trace_id="trace-exit-1",
):
    multiplier = 0.001
    contracts = coin_qty / multiplier
    engine.actual_position = {
        "state": "OPEN",
        "side": side,
        "entry_price": entry,
        "qty": contracts,
        "coin_qty": coin_qty,
        "multiplier": multiplier,
        "entry_time": (
            entry_time if entry_time is not None else time.time() - 0.1
        ),
        "trace_id": trace_id,
        "sl": entry * 0.99 if side == "BUY" else entry * 1.01,
        "tp": entry * 1.02 if side == "BUY" else entry * 0.98,
    }
    engine.portfolio.open_position(engine.symbol, entry, coin_qty, side)


# ============================================================
# A. HOLD
# ============================================================

def test_hold_fresh_continuation_no_close():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(timestamp=1001.5),
        position(),
    )

    assert decision.decision == "HOLD"
    assert decision.reason is None
    assert decision.feature_fresh is True
    assert decision.holding_duration_ms == 1500.0


# ============================================================
# B. MAX_HOLD
# ============================================================

def test_max_hold_reaches_formal_exit_authority():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(timestamp=1003.5),
        position(openedAt=1000.0, evaluatedAt=1003.5),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "MAX_HOLD"
    assert decision.holding_duration_ms == 3500.0


# ============================================================
# C / D. Direction-aware reversal
# ============================================================

def test_buy_position_exits_on_bearish_reversal():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(momentumDirection="DOWN", timestamp=1001.5),
        position(positionSide="BUY"),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "MICROSTRUCTURE_REVERSAL"


def test_sell_position_exits_on_bullish_reversal():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(momentumDirection="UP", timestamp=1001.5),
        position(positionSide="SELL"),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "MICROSTRUCTURE_REVERSAL"


def test_reversal_is_not_mirrored_for_same_side():
    strategy = MicrostructureEdgeStrategy()
    # BUY position with UP momentum must NOT be a reversal.
    buy_hold = strategy.evaluate_exit(
        state(momentumDirection="UP", timestamp=1001.5),
        position(positionSide="BUY"),
    )
    assert buy_hold.reason != "MICROSTRUCTURE_REVERSAL"

    # SELL position with DOWN momentum must NOT be a reversal.
    sell_hold = strategy.evaluate_exit(
        state(momentumDirection="DOWN", timestamp=1001.5),
        position(positionSide="SELL"),
    )
    assert sell_hold.reason != "MICROSTRUCTURE_REVERSAL"


# ============================================================
# E. Momentum decay
# ============================================================

def test_momentum_decay_when_direction_flattens():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(momentumDirection="FLAT", timestamp=1001.5),
        position(positionSide="BUY"),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "MOMENTUM_DECAY"


def test_momentum_decay_when_score_drops():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(momentumDirection="UP", normalizedMomentum=0.3, timestamp=1001.5),
        position(positionSide="BUY"),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "MOMENTUM_DECAY"


# ============================================================
# F. Liquidity deterioration
# ============================================================

def test_liquidity_deterioration_exit():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(liquidityCalibrationReady=False, timestamp=1001.5),
        position(),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "LIQUIDITY_DETERIORATION"


def test_liquidity_quality_below_exit_threshold():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(normalizedLiquidityQuality=0.2, timestamp=1001.5),
        position(),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "LIQUIDITY_DETERIORATION"


# ============================================================
# G. Spread deterioration
# ============================================================

def test_spread_deterioration_exit():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(normalizedSpreadQuality=0.2, timestamp=1001.5),
        position(),
    )

    assert decision.decision == "EXIT"
    assert decision.reason == "SPREAD_DIVERGENCE"


# ============================================================
# J / K. Symbol and freshness safety
# ============================================================

def test_symbol_mismatch_forbids_exit():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(symbol="MOVEUSDT", momentumDirection="DOWN", timestamp=1001.5),
        position(symbol="BTCUSDT", positionSide="BUY"),
    )

    assert decision.decision == "HOLD"
    assert decision.reason == "SYMBOL_MISMATCH"


def test_stale_features_forbid_fabricated_exit():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(momentumDirection="DOWN", timestamp=995.0),
        position(positionSide="BUY", openedAt=1000.0, evaluatedAt=1001.5),
    )

    assert decision.decision == "HOLD"
    assert decision.reason == "STALE_FEATURES"
    assert decision.feature_fresh is False


def test_invalid_position_info_forbids_exit():
    strategy = MicrostructureEdgeStrategy()
    decision = strategy.evaluate_exit(
        state(timestamp=1001.5),
        {"symbol": "BTCUSDT"},
    )

    assert decision.decision == "HOLD"
    assert decision.reason == "INVALID_POSITION_INFO"


# ============================================================
# H / I. Existing TP / SL preservation
# ============================================================

def test_existing_tp_still_closes():
    engine = paper_engine()
    open_paper_position(engine, entry=100.0, side="BUY")

    engine.on_price("BTCUSDT", 103.0, microstructure_state=state())

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["reason"] == "TP"


def test_existing_sl_still_closes():
    engine = paper_engine()
    open_paper_position(engine, entry=100.0, side="BUY")

    engine.on_price("BTCUSDT", 98.0, microstructure_state=state())

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["reason"] == "SL"


# ============================================================
# L. Duplicate exit closes exactly once
# ============================================================

def test_tp_priority_and_no_duplicate_close():
    engine = paper_engine()
    open_paper_position(engine, entry=100.0, side="BUY")

    # TP and a bearish microstructure reversal are both present.
    engine.on_price(
        "BTCUSDT", 103.0,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )
    # Second signal on the same (now closed) position must not close again.
    engine.on_price(
        "BTCUSDT", 103.0,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["reason"] == "TP"


def test_microstructure_exit_closes_exactly_once():
    engine = paper_engine()
    engine.set_exit_evaluator(MicrostructureEdgeStrategy().evaluate_exit)
    open_paper_position(engine, entry=100.0, side="BUY")

    engine.on_price(
        "BTCUSDT", 100.5,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )
    engine.on_price(
        "BTCUSDT", 100.5,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["reason"] == "MICROSTRUCTURE_REVERSAL"


# ============================================================
# M. FLAT -> no exit request
# ============================================================

def test_flat_position_produces_no_exit():
    engine = paper_engine()
    engine.actual_position = None

    engine.on_price(
        "BTCUSDT", 100.5,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )

    assert engine.actual_position is None
    assert len(engine.trade_history) == 0


def test_non_open_position_state_is_not_evaluated():
    engine = paper_engine()
    strategy = MicrostructureEdgeStrategy()
    engine.set_exit_evaluator(strategy.evaluate_exit)
    engine.actual_position = {
        "state": "PENDING",
        "side": "BUY",
        "entry_price": 100.0,
        "qty": 1000,
        "coin_qty": 1.0,
        "multiplier": 0.001,
        "entry_time": time.time() - 0.1,
        "trace_id": "trace-exit-1",
    }

    reason = engine._evaluate_strategy_exit(
        100.5, state(momentumDirection="DOWN", timestamp=time.time())
    )

    assert reason is None


# ============================================================
# N. PAPER lifecycle integration
# ============================================================

def test_paper_lifecycle_strategy_exit_returns_to_flat_with_realized_pnl():
    engine = paper_engine()
    strategy = MicrostructureEdgeStrategy()
    engine.set_exit_evaluator(strategy.evaluate_exit)
    open_paper_position(engine, entry=100.0, side="BUY")

    engine.on_price(
        "BTCUSDT", 100.5,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    record = engine.trade_history[0]
    assert record["reason"] == "MICROSTRUCTURE_REVERSAL"
    assert record["symbol"] == "BTCUSDT"
    assert record["side"] == "BUY"
    assert record["exitPrice"] == 100.5
    # Realized PnL via the authoritative PAPER accounting path.
    assert abs(engine.portfolio.realized_pnl - 0.5) < 1e-9
    assert abs(engine.portfolio.balance - 100.5) < 1e-9


# ============================================================
# O. Entry regression
# ============================================================

def test_entry_pipeline_is_unchanged():
    strategy = MicrostructureEdgeStrategy()
    result = strategy.process_microstructure_strategy(state())

    assert result["valid"] is True
    entry = result["strategy"]["entryReadiness"]
    assert entry["available"] is True
    assert entry["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"


# ============================================================
# P. LIVE safety
# ============================================================

def test_live_safety_exit_never_mutates_exchange():
    exchange = Mock()
    portfolio = PortfolioManager(initial_balance=100.0)
    engine = ExecutionEngine(portfolio=portfolio)
    engine.exchange = exchange
    engine.mode = "paper"
    engine.status = "RUNNING"
    engine.symbol = "BTCUSDT"
    strategy = MicrostructureEdgeStrategy()
    engine.set_exit_evaluator(strategy.evaluate_exit)
    open_paper_position(engine, entry=100.0, side="BUY")

    engine.on_price(
        "BTCUSDT", 100.5,
        microstructure_state=state(momentumDirection="DOWN", timestamp=time.time()),
    )

    assert engine.actual_position is None
    # Exit path must not create any exchange / LIVE mutation.
    assert len(exchange.method_calls) == 0
    assert engine.paper_orders == []
    assert all(record["mode"] == "paper" for record in engine.trade_history)
