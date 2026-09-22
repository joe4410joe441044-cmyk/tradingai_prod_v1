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
import tempfile
import time

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
    governance_state["mode"] = "PAPER"
    yield
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    governance_state["mode"] = "PAPER"


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


# =========================
# SWITCH GUARD: POST-RESTART MODE AUTHORITY
# =========================
# After a backend restart self.config is empty (it is populated only at
# start()) while the manager is in a legitimate STOPPED bootstrap. The guard
# must resolve the canonical stopped-runtime mode rather than reporting
# RUNTIME_MODE_UNKNOWN, but it must stay fail-closed for genuinely unknown or
# conflicting mode authorities.

def test_empty_runtime_config_with_canonical_paper_allows_switch():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = "PAPER"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert result["changed"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1


def test_empty_runtime_config_with_canonical_live_allows_switch():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = "LIVE"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1


def test_unknown_runtime_mode_denies_switch():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = "UNRESOLVED"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "RUNTIME_MODE_UNKNOWN"
    assert manager.control_revision == 0


def test_missing_canonical_mode_denies_switch():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = None
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "RUNTIME_MODE_UNKNOWN"
    assert manager.control_revision == 0


def test_post_restart_bootstrap_allows_bot_to_manual_switch():
    """Exact Production bootstrap: fresh manager after a backend restart."""

    manager = BotManager()
    manager.engine = None
    manager.config = {}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "STOPPED"
    manager._running = False
    manager.pending_order = False
    manager.state.position_state = "FLAT"
    manager._active_symbol = None
    manager.get_authoritative_pending_order_state = Mock(
        return_value=_flat_pending()
    )
    manager.control_authority = CONTROL_AUTHORITY_BOT
    manager.control_revision = 0
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["mode"] = "PAPER"

    result = manager.set_execution_control(
        "MANUAL", expected_revision=0
    )

    assert result["success"] is True
    assert result["changed"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1

    # The authority switch must never mutate the runtime bootstrap.
    assert manager.lifecycle_state == "STOPPED"
    assert manager.loop_state == "STOPPED"
    assert manager._running is False
    assert manager.engine is None
    assert manager.activeSymbol is None
    assert manager.pending_order is False
    assert manager.state.actual_position is None
    assert manager.state.position_state == "FLAT"
    assert governance_state["execution_enabled"] is False


def test_post_restart_stale_expected_revision_denied():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = "PAPER"
    assert manager.set_execution_control(
        "MANUAL", expected_revision=0
    )["success"] is True
    stale = manager.set_execution_control("BOT", expected_revision=0)
    assert stale["success"] is False
    assert stale["reason"] == "DENY_STALE_CONTROL_REVISION"
    assert manager.control_revision == 1


def test_canonical_live_mode_resolves_live_not_paper():
    manager = _manager()
    manager.config = {}
    governance_state["mode"] = "LIVE"
    resolution = manager._stopped_paper_mode_resolution()
    assert resolution["mode"] == "live"
    assert resolution["source"] == "governance_state.mode"


def test_conflicting_canonical_modes_fail_closed():
    manager = _manager()
    manager.config = {"mode": "live", "dry_run": False}
    governance_state["mode"] = "PAPER"
    resolution = manager._stopped_paper_mode_resolution()
    assert resolution["mode"] is None
    assert resolution["reason"] == "MODE_CONFLICT"


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
    manager = _manager(engine=engine, lifecycle_state="RUNNING", loop_state="RUNNING")
    governance_state["execution_enabled"] = True
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


# =========================
# STOPPED PAPER STALE SNAPSHOT: SYNCHRONOUS REVALIDATION
# =========================
# WORK D defect: with the PAPER runtime STOPPED the authoritative
# stopped-PAPER safety snapshot ages past account_stale_after (90s). A human
# BOT -> MANUAL switch was then rejected with SNAPSHOT_STALE even though the
# runtime was legitimately STOPPED + PAPER + FLAT with no pending order. The
# switch admission path now synchronously revalidates stopped-PAPER safety
# authority (instead of forcing the operator to race a manual refresh), while
# still failing closed on any unproven safety state.

def _stale_pending():
    return {
        "known": False,
        "pending": None,
        "safe": False,
        "pending_order": True,
        "reason": "SNAPSHOT_STALE",
        "source": "stopped_paper_authoritative",
    }


def _stale_manager(revalidation):
    manager = _manager()
    manager.get_authoritative_pending_order_state = Mock(
        return_value=_stale_pending()
    )
    manager._revalidate_stopped_paper_authority_for_control_switch = Mock(
        return_value=revalidation
    )
    return manager


def _production_like_stopped_paper_snapshot(generation, last_update):
    return {
        "source": "stopped_paper_engine_portfolio_snapshot",
        "authorityReason": "STOPPED_PAPER_ENGINE_STATE_CAPTURED",
        "available": True,
        "generation": generation,
        "stateUnknown": False,
        "tradeMode": "paper",
        "mode": "paper",
        "selectedMode": "PAPER",
        "lifecycleState": "STOPPED",
        "operationId": None,
        "capturedAt": last_update,
        "timestamp": last_update,
        "timestampEpoch": last_update,
        "last_update": last_update,
        "position": None,
        "positions": [],
        "positionRemaining": False,
        "positionStateSource": (
            "execution_engine.actual_position+portfolio.positions"
        ),
        "pendingOrder": False,
        "pending_order": False,
        "pendingStateSource": (
            "execution_engine.pending_order_duplicate_lock"
        ),
        "pendingOrderStateSource": (
            "execution_engine.pending_order_duplicate_lock"
        ),
        "openOrderCount": 0,
        "openOrderStateSource": (
            "execution_engine."
            "paper_immediate_fill_no_open_order_collection"
        ),
        "runtimeInstanceId": "test-runtime",
        "evidenceGeneration": generation,
        "evidenceCapturedAt": last_update,
        "evidenceRuntimeInstanceId": "test-runtime",
        "evidenceSource": "stopped_paper_engine_portfolio_snapshot",
    }


def _stale_stopped_paper_manager():
    manager = BotManager()
    manager.engine = None
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "STOPPED"
    manager.loop_state = "STOPPED"
    manager._running = False
    manager.pending_order = False
    manager.state.position_state = "FLAT"
    manager.stopped_paper_durable_snapshot_path = os.path.join(
        tempfile.mkdtemp(),
        "stopped_paper_safety_snapshot.json",
    )
    manager.account_snapshot_generation = 0
    manager.account_snapshot = _production_like_stopped_paper_snapshot(
        0,
        time.time() - 1000,
    )
    manager.control_authority = CONTROL_AUTHORITY_BOT
    manager.control_revision = 0
    governance_state["control_authority"] = CONTROL_AUTHORITY_BOT
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["mode"] = "PAPER"
    return manager


def test_stale_stopped_paper_snapshot_bot_to_manual_revalidates():
    manager = _stale_manager(_flat_pending())
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert result["changed"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_called_once()


def test_stale_stopped_paper_snapshot_manual_to_bot_revalidates():
    manager = _stale_manager(_flat_pending())
    assert manager.set_execution_control("MANUAL")["success"] is True
    manager.get_authoritative_pending_order_state = Mock(
        return_value=_stale_pending()
    )
    manager._revalidate_stopped_paper_authority_for_control_switch = Mock(
        return_value=_flat_pending()
    )
    result = manager.set_execution_control("BOT")
    assert result["success"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_BOT
    assert result["controlRevision"] == 2


def test_stale_revalidation_unknown_denies_switch():
    manager = _stale_manager({
        "known": False,
        "pending": None,
        "safe": False,
        "reason": "PENDING_ORDER_UNKNOWN",
    })
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_UNKNOWN"
    assert manager.control_revision == 0


def test_stale_revalidation_pending_true_denies_switch():
    manager = _stale_manager({
        "known": True,
        "pending": True,
        "safe": False,
        "reason": "PENDING_ORDER_REMAINING",
    })
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_REMAINING"
    assert manager.control_revision == 0


def test_stale_revalidation_unsafe_denies_switch():
    manager = _stale_manager({
        "known": False,
        "pending": None,
        "safe": False,
        "reason": "POSITION_STATE_UNKNOWN",
    })
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "POSITION_STATE_UNKNOWN"
    assert manager.control_revision == 0


def test_stale_revalidation_position_non_flat_denies_switch():
    manager = _stale_manager(_flat_pending())
    manager.state.position_state = "LONG"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "POSITION_LONG_BLOCKS_CONTROL_SWITCH"
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_not_called()


def test_stale_revalidation_mode_unknown_denies_switch():
    manager = _stale_manager(_flat_pending())
    manager.config = {}
    governance_state["mode"] = "UNRESOLVED"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    assert result["reason"] == "RUNTIME_MODE_UNKNOWN"
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_not_called()


def test_stale_revalidation_mode_conflict_denies_switch():
    manager = _stale_manager(_flat_pending())
    manager.config = {"mode": "live", "dry_run": False}
    governance_state["mode"] = "PAPER"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_not_called()


def test_live_mode_does_not_use_stopped_paper_revalidation():
    manager = _stale_manager(_flat_pending())
    manager.config = {}
    governance_state["mode"] = "LIVE"
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is False
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_not_called()


def test_stale_snapshot_stale_expected_revision_denied():
    manager = _stale_manager(_flat_pending())
    assert manager.set_execution_control("MANUAL")["success"] is True
    manager.get_authoritative_pending_order_state = Mock(
        return_value=_stale_pending()
    )
    manager._revalidate_stopped_paper_authority_for_control_switch = Mock(
        return_value=_flat_pending()
    )
    result = manager.set_execution_control("BOT", expected_revision=0)
    assert result["success"] is False
    assert result["reason"] == "DENY_STALE_CONTROL_REVISION"
    manager._revalidate_stopped_paper_authority_for_control_switch \
        .assert_not_called()


def test_stale_snapshot_switch_never_creates_order_or_engine():
    manager = _stale_manager(_flat_pending())
    result = manager.set_execution_control("MANUAL")
    assert result["success"] is True
    assert manager.engine is None
    assert manager.pending_order is False
    assert manager.state.actual_position is None


def test_revalidation_calls_real_refresh_and_maps_safe_state():
    manager = _manager()
    manager._stopped_paper_authoritative_safety_state = Mock(
        return_value={
            "safe": True,
            "reason": "STOPPED_PAPER_AUTHORITATIVE_SAFE",
        }
    )
    payload = manager._revalidate_stopped_paper_authority_for_control_switch()
    manager._stopped_paper_authoritative_safety_state.assert_called_once_with(
        refresh_snapshot=True
    )
    assert payload["known"] is True
    assert payload["pending"] is False
    assert payload["safe"] is True


def test_real_stale_snapshot_bot_to_manual_revalidates_end_to_end():
    manager = _stale_stopped_paper_manager()

    pending = manager.get_authoritative_pending_order_state()
    assert pending["known"] is False
    assert pending["reason"] == "SNAPSHOT_STALE"

    result = manager.set_execution_control("MANUAL", expected_revision=0)

    assert result["success"] is True
    assert result["changed"] is True
    assert result["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert result["controlRevision"] == 1
    assert manager.engine is None
    assert manager.pending_order is False
    assert manager.state.actual_position is None
