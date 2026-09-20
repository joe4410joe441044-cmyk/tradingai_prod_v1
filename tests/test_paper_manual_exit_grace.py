"""Focused tests for the acceptance-only PAPER MANUAL exit grace.

The grace is a bounded, default-OFF, PAPER-only mechanism that defers ONLY the
strategy/microstructure automatic exit evaluator for MANUAL-origin positions
while the position age is below ``PAPER_MANUAL_EXIT_GRACE_MS``.  It must never
affect LIVE, BOT-origin positions, manual close, or emergency flatten, and it
must resume normal automatic exits once the grace expires.
"""

import os
import time

import pytest

os.environ.setdefault("TEST_MODE", "1")

import test_manual_trade_d6_paper_buy_sell_e2e as d6

from backend.bot_manager.bot_manager import (
    CONTROL_AUTHORITY_BOT,
    CONTROL_AUTHORITY_MANUAL,
    MANUAL_OPERATION_CLOSE_LONG,
    MANUAL_OPERATION_CLOSE_SHORT,
)
from backend.runtime.governance_runtime import (
    EMERGENCY_READY,
    governance_state,
)

SYMBOL = d6.SYMBOL
GRACE_ENV = "PAPER_MANUAL_EXIT_GRACE_MS"


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


def _manual_manager():
    manager, engine, portfolio, price, recorder = d6._build_manager(price=100.0)
    manager.control_authority = CONTROL_AUTHORITY_MANUAL
    manager._mirror_control_authority()
    return manager, engine, portfolio, price, recorder


def _open(manager, action, request_id):
    return manager.execute_manual_trade(
        {"action": action, "requestId": request_id}
    )


def _bind_exit(manager, engine, reason="TEST_EXIT"):
    def fake_evaluate_exit(microstructure_state, position_info):
        return {"decision": "EXIT", "reason": reason}

    engine.set_exit_evaluator(
        manager._build_snapshot_aware_exit_evaluator(fake_evaluate_exit)
    )


def _state():
    return {"symbol": SYMBOL, "timestamp": time.time()}


def _strategy_exit(engine, price):
    return engine._evaluate_strategy_exit(price, _state())


def test_default_grace_off_keeps_existing_automatic_exit(monkeypatch):
    monkeypatch.delenv(GRACE_ENV, raising=False)
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-default-entry")["success"] is True
    assert engine.actual_position is not None

    _bind_exit(manager, engine)
    engine.on_price(SYMBOL, price.price, _state())

    # Default grace 0 => the strategy automatic exit still closes the position.
    assert engine.actual_position is None


def test_paper_manual_grace_defers_then_resumes(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-defer-entry")["success"] is True
    position = engine.actual_position
    assert position["entry_authority"] == "MANUAL"

    _bind_exit(manager, engine)

    # Inside the grace: the strategy automatic exit is deferred (no exit).
    engine.on_price(SYMBOL, price.price, _state())
    assert engine.actual_position is not None
    assert _strategy_exit(engine, price.price) is None

    # After the grace: normal automatic exits resume and close the position.
    position["entry_time"] = time.time() - 20.0
    assert _strategy_exit(engine, price.price) == "TEST_EXIT"
    engine.on_price(SYMBOL, price.price, _state())
    assert engine.actual_position is None


def test_bot_origin_position_has_no_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-bot-entry")["success"] is True

    engine.actual_position["entry_authority"] = "BOT"
    _bind_exit(manager, engine)

    assert _strategy_exit(engine, price.price) == "TEST_EXIT"


def test_live_mode_has_no_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-live-entry")["success"] is True

    engine.mode = "live"
    _bind_exit(manager, engine)

    assert _strategy_exit(engine, price.price) == "TEST_EXIT"


def test_unknown_mode_has_no_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-unknown-mode-entry")["success"] is True

    engine.mode = "something-else"
    _bind_exit(manager, engine)

    assert _strategy_exit(engine, price.price) == "TEST_EXIT"


def test_unknown_position_origin_has_no_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-unknown-origin-entry")["success"] is True

    engine.actual_position["entry_authority"] = None
    _bind_exit(manager, engine)

    assert _strategy_exit(engine, price.price) == "TEST_EXIT"


def test_grace_requires_manual_control_authority(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-bot-control-entry")["success"] is True

    manager.control_authority = CONTROL_AUTHORITY_BOT
    _bind_exit(manager, engine)

    assert _strategy_exit(engine, price.price) == "TEST_EXIT"


def test_manual_close_long_allowed_during_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-close-long-entry")["success"] is True

    _bind_exit(manager, engine)
    assert _strategy_exit(engine, price.price) is None  # grace active

    close = _open(manager, "SELL", "grace-close-long")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.pending_order is False


def test_manual_close_short_allowed_during_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "SELL", "grace-close-short-entry")["success"] is True

    _bind_exit(manager, engine)
    assert _strategy_exit(engine, price.price) is None  # grace active

    close = _open(manager, "BUY", "grace-close-short")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.pending_order is False


def test_emergency_flatten_unaffected_during_grace(monkeypatch):
    monkeypatch.setenv(GRACE_ENV, "10000")
    manager, engine, portfolio, price, recorder = _manual_manager()
    assert _open(manager, "BUY", "grace-emergency-entry")["success"] is True

    _bind_exit(manager, engine)
    assert _strategy_exit(engine, price.price) is None  # grace active

    flatten = engine.flatten_paper_position(reason="EMERGENCY_FLATTEN")
    assert flatten["success"] is True
    assert engine.actual_position is None
