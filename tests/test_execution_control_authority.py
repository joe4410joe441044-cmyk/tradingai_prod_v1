"""TRADINGAI-MANUAL-TRADING-D2: BOT/MANUAL execution control authority.

These tests are isolated. They never place a paper order, never call an
exchange, never start a runtime, and never mutate production state.

The BotManager backend is the authority owner for ``controlAuthority``
(BOT|MANUAL) and the monotonic ``controlRevision``. A switch fails closed
unless the strict V1 switch guard holds; a denied switch never increments the
revision and never stops the runtime. While control is MANUAL, automatic BOT
new-entry is denied by the manager-owned shared authority boundary.
"""

import os

os.environ.setdefault("TEST_MODE", "1")

from unittest.mock import Mock

import pytest

from backend.bot_manager.bot_manager import (
    BotManager,
    CONTROL_AUTHORITY_BOT,
    CONTROL_AUTHORITY_MANUAL,
)
from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    EMERGENCY_READY,
    governance_state,
)
from Bot.engine.execution_engine import ExecutionEngine


@pytest.fixture(autouse=True)
def _reset_governance():
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY


def _flat_pending():
    return {
        "known": True,
        "pending": False,
        "safe": True,
        "pending_order": False,
        "reason": "NO_PENDING_ORDER",
    }


def _manager(**attrs):
    manager = BotManager()
    manager.engine = None
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "STOPPED"
    manager._running = False
    manager.pending_order = False
    manager.state.position_state = "FLAT"
    manager.get_authoritative_pending_order_state = Mock(
        return_value=_flat_pending()
    )
    manager.control_authority = CONTROL_AUTHORITY_BOT
    manager.control_revision = 0
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


# =========================
# CONTROL STATE + REVISION
# =========================

def test_control_default_is_bot():
    manager = _manager()
    state = manager.get_execution_control_state()
    assert state["controlAuthority"] == CONTROL_AUTHORITY_BOT
    assert state["controlRevision"] == 0
    assert state["owner"] == "BOT_MANAGER_BACKEND"
    assert state["controlAuthorityValues"] == ["BOT", "MANUAL"]


def test_control_revision_is_monotonic():
    manager = _manager()
    revisions = [manager.control_revision]
    for authority in ("MANUAL", "BOT", "MANUAL", "BOT"):
        result = manager.set_execution_control(authority)
        assert result["success"] is True
        revisions.append(manager.control_revision)
    assert revisions == [0, 1, 2, 3, 4]


def test_invalid_control_authority_denied():
    manager = _manager()
    result = manager.set_execution_control("HUMAN")
    assert result["success"] is False
    assert result["reason"] == "INVALID_CONTROL_AUTHORITY"
    assert manager.control_revision == 0


def test_same_authority_does_not_increment_revision():
    manager = _manager()
    result = manager.set_execution_control("BOT")
    assert result["success"] is True
    assert result["changed"] is False
    assert manager.control_revision == 0


def test_stale_expected_revision_denied():
    manager = _manager()
    manager.set_execution_control("MANUAL")
    result = manager.set_execution_control("BOT", expected_revision=0)
    assert result["success"] is False
    assert result["reason"] == "DENY_STALE_CONTROL_REVISION"
    assert manager.control_revision == 1


def test_failed_switch_does_not_increment_revision():
    engine = Mock()
    engine.actual_position = {"state": "OPEN", "side": "BUY", "qty": 1}
    engine.pending_order = False
    engine.execution_entry_admission_in_progress = False
    manager = _manager(engine=engine)
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert manager.control_revision == 0
    assert manager.control_authority == CONTROL_AUTHORITY_BOT


# =========================
# SWITCH GUARD: POSITION
# =========================

@pytest.mark.parametrize(
    "side, expected_reason",
    [
        ("BUY", "POSITION_LONG_BLOCKS_CONTROL_SWITCH"),
        ("LONG", "POSITION_LONG_BLOCKS_CONTROL_SWITCH"),
        ("SELL", "POSITION_SHORT_BLOCKS_CONTROL_SWITCH"),
        ("SHORT", "POSITION_SHORT_BLOCKS_CONTROL_SWITCH"),
        ("???", "POSITION_UNKNOWN_BLOCKS_CONTROL_SWITCH"),
    ],
)
def test_open_or_unknown_position_denies_switch(side, expected_reason):
    engine = Mock()
    engine.actual_position = {"state": "OPEN", "side": side, "qty": 1}
    engine.pending_order = False
    engine.execution_entry_admission_in_progress = False
    manager = _manager(engine=engine)
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == expected_reason
    assert manager.control_revision == 0


# =========================
# SWITCH GUARD: PENDING
# =========================

def test_pending_true_denies_switch():
    manager = _manager()
    manager.get_authoritative_pending_order_state = Mock(return_value={
        "known": True,
        "pending": True,
        "safe": False,
        "pending_order": True,
        "reason": "PENDING_ORDER_REMAINING",
    })
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_REMAINING"
    assert manager.control_revision == 0


def test_pending_unknown_denies_switch():
    manager = _manager()
    manager.get_authoritative_pending_order_state = Mock(return_value={
        "known": False,
        "pending": None,
        "safe": False,
        "pending_order": None,
        "reason": "PENDING_ORDER_UNKNOWN",
    })
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_UNKNOWN"
    assert manager.control_revision == 0


# =========================
# SWITCH GUARD: EMERGENCY / SYMBOL SWITCH / ADMISSION
# =========================

def test_emergency_unsafe_denies_switch():
    manager = _manager()
    governance_state["emergency_stop"] = True
    governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "EMERGENCY_STOP_ACTIVE"
    assert manager.control_revision == 0


def test_symbol_switch_in_progress_denies_switch():
    manager = _manager()
    manager._symbol_switch_entry_paused = True
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "SYMBOL_SWITCH_IN_PROGRESS"
    assert manager.control_revision == 0


def test_entry_admission_in_progress_denies_switch():
    manager = _manager()
    manager.execution_admission_reservation = {
        "source": "BOT",
        "reservationId": 1,
    }
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "ENTRY_ADMISSION_IN_PROGRESS"
    assert manager.control_revision == 0


def test_unknown_runtime_mode_denies_switch():
    manager = _manager()
    manager.config = {}
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "RUNTIME_MODE_UNKNOWN"


# =========================
# AUTO TRADE INTERACTION
# =========================

def test_bot_to_manual_forces_auto_trade_off():
    manager = _manager()
    governance_state["execution_enabled"] = True
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1
    assert governance_state["execution_enabled"] is False


def test_manual_to_bot_leaves_auto_trade_off():
    manager = _manager()
    manager.set_execution_control("MANUAL")
    result = manager.set_execution_control("BOT")
    assert result["success"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_BOT
    assert result["controlRevision"] == 2
    assert governance_state["execution_enabled"] is False


def test_control_switch_never_creates_order_or_engine():
    manager = _manager()
    manager.set_execution_control("MANUAL")
    assert manager.engine is None
    assert manager.pending_order is False
    assert manager.state.actual_position is None


# =========================
# RUNTIME STAYS RUNNING IN MANUAL
# =========================

def test_control_manual_keeps_runtime_running():
    engine = Mock()
    engine.actual_position = None
    engine.pending_order = False
    engine.execution_entry_admission_in_progress = False
    engine.symbol = "XRPUSDT"
    manager = _manager(engine=engine)
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "RUNNING"
    manager._running = True

    result = manager.set_execution_control("MANUAL")

    assert result["success"] is True
    assert manager.lifecycle_state == "RUNNING"
    assert manager.loop_state == "RUNNING"
    assert manager._running is True
    assert manager.engine is engine


# =========================
# MARKET SELECTION DECOUPLED
# =========================

def test_market_selection_auto_with_manual_control_is_legal():
    manager = _manager()
    manager.selection_mode = "AUTO"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert manager.selection_mode == "AUTO"
    assert manager.control_authority == CONTROL_AUTHORITY_MANUAL


# =========================
# BOT ENTRY AUTHORITY BOUNDARY
# =========================

def test_bot_entry_denied_in_manual():
    manager = _manager()
    manager.set_execution_control("MANUAL")
    decision = manager._authorize_bot_execution_entry({"side": "BUY"})
    assert decision["allowed"] is False
    assert decision["reason"] == "BOT_ENTRY_LOCKED_MANUAL_CONTROL"


def test_bot_entry_requires_active_admission_reservation():
    engine = Mock()
    engine.symbol = "XRPUSDT"
    manager = _manager(engine=engine)
    decision = manager._authorize_bot_execution_entry({
        "side": "BUY",
        "runtimeSymbolContext": {"symbol": "XRPUSDT", "runtimeId": "r1"},
    })
    assert decision["allowed"] is False
    assert decision["reason"] == "EXECUTION_ADMISSION_NOT_RESERVED"


def test_stale_symbol_context_denied_at_entry():
    engine = Mock()
    engine.symbol = "XRPUSDT"
    manager = _manager(engine=engine)
    with manager.execution_authority_lock:
        manager._begin_execution_admission("BOT")
    decision = manager._authorize_bot_execution_entry({
        "side": "BUY",
        "runtimeSymbolContext": {"symbol": "BTCUSDT", "runtimeId": "r1"},
    })
    assert decision["allowed"] is False
    assert decision["reason"] == "DENY_STALE_INTENT"


def test_matching_symbol_context_allows_bot_entry():
    engine = Mock()
    engine.symbol = "XRPUSDT"
    manager = _manager(engine=engine)
    with manager.execution_authority_lock:
        manager._begin_execution_admission("BOT")
    decision = manager._authorize_bot_execution_entry({
        "side": "BUY",
        "runtimeSymbolContext": {"symbol": "XRPUSDT", "runtimeId": "r1"},
    })
    assert decision["allowed"] is True
    assert decision["reason"] == "BOT_ENTRY_AUTHORIZED"


def test_stale_control_revision_denied_at_entry():
    engine = Mock()
    engine.symbol = "XRPUSDT"
    manager = _manager(engine=engine)
    with manager.execution_authority_lock:
        reservation = manager._begin_execution_admission("BOT")
        reservation["controlRevision"] = manager.control_revision - 1
    decision = manager._authorize_bot_execution_entry({
        "side": "BUY",
        "runtimeSymbolContext": {"symbol": "XRPUSDT", "runtimeId": "r1"},
    })
    assert decision["allowed"] is False
    assert decision["reason"] == "DENY_STALE_CONTROL_REVISION"


# =========================
# ENGINE FINAL AUTHORITY REVALIDATION
# =========================

def test_mm_preflight_dispatch_blocked_in_manual_control():
    manager = _manager()
    calls = []
    manager.set_money_management_execution_entry_guard(
        lambda intent: (calls.append(intent) or "ok")
    )
    manager.set_execution_control("MANUAL")

    result = manager._dispatch_money_management_execution_entry_guard(
        object()
    )

    assert result is None
    assert calls == []


def test_engine_authority_guard_precedes_mm_and_blocks_order():
    engine = ExecutionEngine()
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    mm_calls = []
    engine.set_execution_entry_guard(
        lambda intent: (mm_calls.append(intent) or None)
    )
    engine.set_execution_authority_guard(
        lambda signal: {
            "allowed": False,
            "reason": "BOT_ENTRY_LOCKED_MANUAL_CONTROL",
        }
    )

    result = engine.try_entry({"id": "1", "side": "BUY"})

    assert mm_calls == []
    assert result["submitted"] is False
    assert result["orderCreated"] is False
    assert result["providerCall"] is False
    assert result["exchangeCall"] is False
    assert result["reason"] == "BOT_ENTRY_LOCKED_MANUAL_CONTROL"
    assert engine.pending_order is False
    assert engine.actual_position is None


def test_engine_authority_guard_fails_closed_on_unknown_callback_result():
    engine = ExecutionEngine()
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    engine.set_execution_authority_guard(lambda signal: "not-a-dict")
    result = engine.try_entry({"id": "1", "side": "BUY"})
    assert result["submitted"] is False
    assert result["reason"] == "EXECUTION_AUTHORITY_UNKNOWN"


def test_engine_without_authority_guard_is_unaffected():
    engine = ExecutionEngine()
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    engine.price_ready = False
    result = engine.try_entry({"id": "1", "side": "BUY"})
    # No authority guard installed: the legacy entry path runs and simply
    # blocks on its own existing gates (no order, no crash).
    assert engine.pending_order is False
    assert engine.actual_position is None
    assert result is None or result.get("submitted") is not True


# =========================
# MANUAL BUY/SELL IS NOT IMPLEMENTED IN D2
# =========================

def test_manual_execution_not_implemented_in_d2():
    manager = _manager()
    manager.set_execution_control("MANUAL")
    # No manual entry/close entrypoints exist yet; control switch alone must
    # never create an order or a position.
    assert not hasattr(manager, "manual_buy")
    assert not hasattr(manager, "manual_sell")
    assert not hasattr(manager, "manual_close")
    assert manager.engine is None
