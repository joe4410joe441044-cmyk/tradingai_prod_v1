"""D-LIVE-14R4: strategy exit ownership for MANUAL positions.

A MANUAL-created position must never be closed by the BOT strategy exit
evaluator (for example MICROSTRUCTURE_REVERSAL).  Explicit manual close and the
protective SL/TP/trailing paths remain unchanged.  BOT-owned positions keep the
existing strategy exit behaviour.  Missing / unknown entry ownership fails
closed: it is never treated as BOT-owned.
"""

import os
import time

import pytest

os.environ.setdefault("TEST_MODE", "1")

import test_manual_trade_d6_paper_buy_sell_e2e as d6

from Bot.engine.execution_engine import ExecutionEngine
from backend.bot_manager.bot_manager import (
    CONTROL_AUTHORITY_BOT,
    CONTROL_AUTHORITY_MANUAL,
    MANUAL_OPERATION_CLOSE_LONG,
    MANUAL_OPERATION_CLOSE_SHORT,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)

SYMBOL = d6.SYMBOL
REVERSAL = "MICROSTRUCTURE_REVERSAL"


@pytest.fixture(autouse=True)
def _reset_governance():
    previous = dict(governance_state)
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state.clear()
    governance_state.update(previous)


def _state():
    return {"symbol": SYMBOL, "timestamp": time.time()}


def _manual_manager():
    manager, engine, portfolio, price, recorder = d6._build_manager(price=100.0)
    manager.control_authority = CONTROL_AUTHORITY_MANUAL
    manager._mirror_control_authority()
    return manager, engine, portfolio, price, recorder


def _manual(manager, action, request_id):
    return manager.execute_manual_trade(
        {"action": action, "requestId": request_id,
         "expectedMode": "paper", "expectedSymbol": manager.activeSymbol,
         "expectedControlRevision": manager.control_revision}
    )


def _bind_reversal(engine, reason=REVERSAL):
    def _evaluate(microstructure_state, position_info):
        return {"decision": "EXIT", "reason": reason}

    engine.set_exit_evaluator(_evaluate)


def _bot_engine(side="BUY", entry_authority="BOT"):
    portfolio = PortfolioManager(initial_balance=100.0)
    engine = ExecutionEngine(portfolio=portfolio)
    engine.symbol = SYMBOL
    engine.mode = "paper"
    engine.status = "RUNNING"
    engine.set_config({
        "mode": "paper",
        "dry_run": True,
        "sl_percent": 1,
        "tp_percent": 2,
    })
    position = {
        "state": "OPEN",
        "side": side,
        "entry_price": 100.0,
        "qty": 1000,
        "coin_qty": 1.0,
        "multiplier": 0.001,
        "entry_time": time.time() - 0.1,
        "trace_id": f"trace-{side}",
        "sl": 99.0 if side == "BUY" else 101.0,
        "tp": 102.0 if side == "BUY" else 98.0,
    }
    if entry_authority is not None:
        position["entry_authority"] = entry_authority
    engine.actual_position = position
    engine.portfolio.open_position(SYMBOL, 100.0, 1.0, side)
    return engine


# ============================================================
# A / B. MANUAL positions ignore strategy reversal exits
# ============================================================

@pytest.mark.parametrize(
    ("action", "side"),
    [("BUY", "BUY"), ("SELL", "SELL")],
)
def test_manual_position_strategy_reversal_is_suppressed(action, side):
    manager, engine, _portfolio, price, _recorder = _manual_manager()
    assert _manual(manager, action, f"manual-reversal-{side}")["success"] is True
    position = engine.actual_position
    assert position["entry_authority"] == "MANUAL"

    _bind_reversal(engine)

    assert engine._evaluate_strategy_exit(price.price, _state()) is None
    engine.on_price(SYMBOL, price.price, _state())

    assert engine.actual_position is position
    assert engine.trade_history == []
    assert len(engine.paper_orders) == 1
    assert [fill["fillType"] for fill in engine.paper_fills] == ["ENTRY"]


# ============================================================
# C. BOT strategy exit behaviour is preserved
# ============================================================

def test_bot_position_strategy_reversal_still_closes():
    engine = _bot_engine(entry_authority="BOT")
    _bind_reversal(engine)

    assert engine._evaluate_strategy_exit(100.5, _state()) == REVERSAL
    engine.on_price(SYMBOL, 100.5, _state())

    assert engine.actual_position is None
    assert engine.trade_history[-1]["reason"] == REVERSAL


# ============================================================
# D. Missing / unknown ownership fails closed
# ============================================================

@pytest.mark.parametrize("authority", [None, "", "UNKNOWN", "SOMETHING"])
def test_unknown_entry_authority_fails_closed_for_strategy_exit(authority):
    engine = _bot_engine(entry_authority=authority)
    _bind_reversal(engine)

    assert engine._evaluate_strategy_exit(100.5, _state()) is None
    engine.on_price(SYMBOL, 100.5, _state())

    assert engine.actual_position is not None
    assert engine.trade_history == []


def test_missing_entry_authority_key_fails_closed_for_strategy_exit():
    engine = _bot_engine(entry_authority=None)
    assert "entry_authority" not in engine.actual_position
    _bind_reversal(engine)

    assert engine._evaluate_strategy_exit(100.5, _state()) is None
    engine.on_price(SYMBOL, 100.5, _state())

    assert engine.actual_position is not None
    assert engine.trade_history == []


# ============================================================
# E / F. Explicit manual close remains unchanged
# ============================================================

def test_manual_close_long_is_unchanged():
    manager, engine, portfolio, _price, _recorder = _manual_manager()
    assert _manual(manager, "BUY", "manual-close-long-entry")["success"] is True

    close = _manual(manager, "SELL", "manual-close-long")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert engine.actual_position is None
    assert portfolio.positions == {}


def test_manual_close_short_is_unchanged():
    manager, engine, portfolio, _price, _recorder = _manual_manager()
    assert _manual(manager, "SELL", "manual-close-short-entry")["success"] is True

    close = _manual(manager, "BUY", "manual-close-short")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert engine.actual_position is None
    assert portfolio.positions == {}


# ============================================================
# G / H. Protective SL / TP remain unchanged for MANUAL
# ============================================================

def test_manual_protective_sl_still_closes():
    manager, engine, _portfolio, _price, _recorder = _manual_manager()
    assert _manual(manager, "BUY", "manual-sl-entry")["success"] is True
    _bind_reversal(engine)

    engine.on_price(SYMBOL, 98.0, _state())

    assert engine.actual_position is None
    assert engine.trade_history[-1]["reason"] == "SL"


def test_manual_protective_tp_still_closes():
    manager, engine, _portfolio, _price, _recorder = _manual_manager()
    assert _manual(manager, "BUY", "manual-tp-entry")["success"] is True
    _bind_reversal(engine)

    engine.on_price(SYMBOL, 103.0, _state())

    assert engine.actual_position is None
    assert engine.trade_history[-1]["reason"] == "TP"


# ============================================================
# Trailing / time exit
# ============================================================

def test_manual_protective_trailing_stop_still_closes():
    manager, engine, _portfolio, price, _recorder = _manual_manager()
    engine.config["trailing_stop"] = True
    engine.config["trailing_stop_distance_percent"] = 1.0
    assert _manual(manager, "BUY", "manual-trailing-entry")["success"] is True
    assert engine.actual_position["trailing"] is True

    _bind_reversal(engine)

    # A favourable tick raises the protective stop; the strategy exit is
    # still suppressed because the position is MANUAL-owned.
    engine.on_price(SYMBOL, 101.0, _state())
    assert engine.actual_position is not None
    assert engine.actual_position["sl"] == pytest.approx(99.99)

    # The trailed protective stop still closes the MANUAL position.
    engine.on_price(SYMBOL, 99.5, _state())
    assert engine.actual_position is None
    assert engine.trade_history[-1]["reason"] == "SL"


def test_manual_strategy_owned_time_exit_is_suppressed():
    # There is no independent protective time-exit path: MAX_HOLD is a
    # strategy decision emitted by the same evaluator as MICROSTRUCTURE_REVERSAL.
    manager, engine, _portfolio, price, _recorder = _manual_manager()
    assert _manual(manager, "BUY", "manual-max-hold-entry")["success"] is True
    _bind_reversal(engine, reason="MAX_HOLD")

    assert engine._evaluate_strategy_exit(price.price, _state()) is None
    engine.on_price(SYMBOL, price.price, _state())
    assert engine.actual_position is not None


def test_bot_strategy_owned_time_exit_is_preserved():
    engine = _bot_engine(entry_authority="BOT")
    _bind_reversal(engine, reason="MAX_HOLD")

    assert engine._evaluate_strategy_exit(100.5, _state()) == "MAX_HOLD"


# ============================================================
# Entry ownership is bound from the manager-owned authority guard
# ============================================================

def test_bot_paper_entry_binds_bot_ownership():
    manager, engine, _portfolio, _price, _recorder = d6._build_manager(
        price=100.0
    )
    governance_state["execution_enabled"] = True
    manager.control_authority = CONTROL_AUTHORITY_BOT
    manager._mirror_control_authority()
    reservation = manager._begin_execution_admission("BOT")
    try:
        result = engine.try_entry({
            "id": "bot-ownership-entry",
            "side": "BUY",
            "runtimeSymbolContext": manager._manual_runtime_symbol_context(
                SYMBOL
            ),
        })
    finally:
        manager._end_execution_admission(reservation)

    assert result is None or result.get("success") is True
    assert engine.actual_position["entry_authority"] == "BOT"
