"""TRADINGAI-MANUAL-TRADING-D3: manual PAPER entry and close.

These tests are isolated. They never place a LIVE order, never call an
exchange, never start a runtime, and never mutate production state. They use
the existing in-memory PAPER ExecutionEngine/Portfolio lifecycle only.

Covered contracts:
  * position-aware BUY/SELL classification (immutable operation type)
  * reverse-entry prevention and same-side denial
  * PAPER-only backend guard and MANUAL control requirement
  * approved-quantity identity binding (no silent recalculation)
  * request idempotency (entry and close)
  * shared close boundary / double-close prevention (manual vs TP/SL)
  * auto-exit preservation for a manually opened position
  * MM / account lifecycle projection and ENTRY/EXIT markers
"""

import copy
import os
import threading
import time
from datetime import datetime, timezone

os.environ.setdefault("TEST_MODE", "1")

import pytest

from Bot.engine.execution_engine import ExecutionEngine
from backend.bot_manager.bot_manager import (
    BotManager,
    CONTROL_AUTHORITY_BOT,
    CONTROL_AUTHORITY_MANUAL,
    MANUAL_OPERATION_CLOSE_LONG,
    MANUAL_OPERATION_CLOSE_SHORT,
    MANUAL_OPERATION_ENTRY_LONG,
    MANUAL_OPERATION_ENTRY_SHORT,
)
from backend.market.paper_execution_markers import (
    build_paper_execution_markers,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionReason,
    LossExecutionAdmissionResult,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    EMERGENCY_READY,
    governance_state,
)


SYMBOL = "XRPUSDT"
EXCHANGE_SYMBOL = "XRPUSDTM"
RUNTIME_ID = "manual-runtime-1"
CONTEXT_KEY = "KUCOIN:FUTURES:XRPUSDTM"


class PriceManager:
    def __init__(self, price):
        self.price = price

    def get_current_price(self):
        return self.price


class AdmissionRecorder:
    """Records the exact MM-requested quantity, then allows entry."""

    def __init__(self):
        self.intents = []

    def __call__(self, intent):
        self.intents.append(intent)
        operation = {
            "BUY": LossExecutionOperation.NEW_BUY,
            "SELL": LossExecutionOperation.NEW_SELL,
        }[intent.requested_side]
        return LossExecutionAdmissionResult(
            operation=operation,
            decision=LossExecutionEntryDecision.ALLOW,
            allowed=True,
            reason=LossExecutionAdmissionReason.ENTRY_ALLOWED,
            generated_at=datetime.now(timezone.utc),
            revision=1,
            sequence=1,
            accepted=True,
        )


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


def _build_manager(price=100.0, position_size=100.0):
    manager = BotManager()
    price_manager = PriceManager(price)
    portfolio = PortfolioManager(1000.0)
    engine = ExecutionEngine(
        exchange=None,
        portfolio=portfolio,
        price_manager=price_manager,
    )
    engine.symbol = SYMBOL
    engine.set_config({
        "mode": "paper",
        "dry_run": True,
        "position_size": position_size,
        "leverage": 5,
        "sl_percent": 1,
        "tp_percent": 2,
    })
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = price

    recorder = AdmissionRecorder()
    from sizing_support import install_sizing
    install_sizing(engine)
    engine.set_execution_entry_guard(recorder)
    engine.set_execution_authority_guard(manager._dispatch_execution_authority_guard)

    manager.engine = engine
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "RUNNING"
    manager._running = True
    manager.active_runtime_id = RUNTIME_ID
    manager._active_symbol = SYMBOL
    manager.exchange_name = "kucoin"
    manager.market_type = "FUTURES"
    manager.orderbook_symbol = EXCHANGE_SYMBOL
    manager.state.position_state = "FLAT"
    manager.pending_order = False
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": True,
        "pending": False,
        "safe": True,
        "pending_order": False,
        "reason": "NO_PENDING_ORDER",
    }

    governance_state["emergency_state"] = EMERGENCY_READY
    governance_state["emergency_stop"] = False

    result = manager.set_execution_control(CONTROL_AUTHORITY_MANUAL)
    assert result["success"] is True
    assert manager.control_authority == CONTROL_AUTHORITY_MANUAL

    return manager, engine, portfolio, price_manager, recorder


def _trade(manager, action, request_id, **extra):
    payload = {
        "action": action, "requestId": request_id,
        "expectedMode": manager.config["mode"],
        "expectedSymbol": manager.activeSymbol,
        "expectedControlRevision": manager.control_revision,
    }
    payload.update(extra)
    return manager.execute_manual_trade(payload)


# =========================
# OPERATION CLASSIFICATION
# =========================

@pytest.mark.parametrize(
    "position_state, action, expected",
    [
        ("FLAT", "BUY", MANUAL_OPERATION_ENTRY_LONG),
        ("FLAT", "SELL", MANUAL_OPERATION_ENTRY_SHORT),
        ("LONG", "SELL", MANUAL_OPERATION_CLOSE_LONG),
        ("SHORT", "BUY", MANUAL_OPERATION_CLOSE_SHORT),
        ("LONG", "BUY", "DENY_SAME_SIDE"),
        ("SHORT", "SELL", "DENY_SAME_SIDE"),
        ("UNKNOWN", "BUY", "DENY"),
        ("UNKNOWN", "SELL", "DENY"),
        ("PENDING", "BUY", "DENY"),
        ("PENDING", "SELL", "DENY"),
    ],
)
def test_position_aware_classification(position_state, action, expected):
    assert (
        BotManager._classify_manual_operation(position_state, action)
        == expected
    )


# =========================
# ENTRY
# =========================

def test_manual_entry_long_uses_engine_preview_and_mm_approval():
    manager, engine, portfolio, _price, recorder = _build_manager()
    result = _trade(manager, "BUY", "long-1")

    assert result["success"] is True
    assert result["operation"] == MANUAL_OPERATION_ENTRY_LONG
    assert result["entryAuthority"] == "MANUAL"
    assert engine.actual_position["side"] == "BUY"
    assert engine.actual_position["entry_authority"] == "MANUAL"
    assert SYMBOL in portfolio.positions

    approved = result["approvedQuantity"]
    assert recorder.intents[-1].requested_quantity == approved
    assert engine.actual_position["coin_qty"] == approved
    assert portfolio.positions[SYMBOL]["size"] == approved
    assert len(engine.paper_fills) == 1
    assert engine.paper_fills[0]["entryAuthority"] == "MANUAL"

    snapshot = result["authoritySnapshot"]
    assert snapshot["controlAuthority"] == "MANUAL"
    assert snapshot["controlRevision"] == manager.control_revision
    assert snapshot["mode"] == "paper"
    assert snapshot["symbol"] == SYMBOL
    assert snapshot["mmRevision"] == 1
    assert snapshot["positionState"] == "FLAT"


def test_manual_entry_short_creates_short_position():
    manager, engine, portfolio, _price, _rec = _build_manager()
    result = _trade(manager, "SELL", "short-1")

    assert result["success"] is True
    assert result["operation"] == MANUAL_OPERATION_ENTRY_SHORT
    assert engine.actual_position["side"] == "SELL"
    assert portfolio.positions[SYMBOL]["side"] == "SELL"


def test_manual_entry_allowed_with_auto_trade_off():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    governance_state["execution_enabled"] = False
    result = _trade(manager, "BUY", "auto-off-1")
    assert result["success"] is True
    assert engine.actual_position is not None


def test_manual_entry_denied_when_control_is_bot():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    manager.control_authority = CONTROL_AUTHORITY_BOT
    result = _trade(manager, "BUY", "bot-1")
    assert result["success"] is False
    assert result["reason"] == "MANUAL_CONTROL_REQUIRED"
    assert engine.actual_position is None


def test_manual_entry_live_fails_closed_without_canonical_readiness():
    # MANUAL is no longer PAPER-only.  When the resolved mode is LIVE the
    # request must reach the canonical LIVE entry gate and fail closed there
    # (never with a manual-specific PAPER-only rejection).
    manager, engine, _portfolio, _price, _rec = _build_manager()
    engine.mode = "live"
    engine.config["mode"] = "live"
    engine.config["dry_run"] = False
    manager.config = {"mode": "live", "dry_run": False}
    result = _trade(manager, "BUY", "live-1")
    assert result["success"] is False
    assert result["reason"] == "SIZING_AUTHORITY_UNAVAILABLE"
    assert result["reason"] != "MANUAL_TRADE_PAPER_ONLY"


def test_manual_entry_denied_when_mode_authority_unresolved():
    # A divergent engine/config mode must not silently fall back to PAPER.
    manager, engine, _portfolio, _price, _rec = _build_manager()
    engine.mode = "live"
    result = _trade(manager, "BUY", "unresolved-1")
    assert result["success"] is False
    assert result["reason"] == "MANUAL_MODE_UNRESOLVED"
    assert engine.actual_position is None


def test_manual_entry_denied_when_position_unknown():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    engine.actual_position = {"state": "OPEN", "side": "???", "qty": 1}
    result = _trade(manager, "BUY", "unknown-1")
    assert result["success"] is False
    assert result["reason"] == "MANUAL_POSITION_UNKNOWN"
    assert result["operation"] == "DENY"


def test_manual_entry_denied_when_pending_order_present():
    manager, _engine, _portfolio, _price, _rec = _build_manager()
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": True,
        "pending": True,
        "safe": False,
        "pending_order": True,
        "reason": "PENDING_ORDER_REMAINING",
    }
    result = _trade(manager, "BUY", "pending-1")
    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_REMAINING"


def test_manual_entry_denied_when_emergency_active():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    governance_state["emergency_stop"] = True
    governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
    result = _trade(manager, "BUY", "emergency-1")
    assert result["success"] is False
    assert result["reason"] == "EMERGENCY_STOP_ACTIVE"
    assert engine.actual_position is None


# =========================
# CLOSE
# =========================

def test_manual_close_long_is_full_close_and_never_reverses():
    manager, engine, portfolio, price, _rec = _build_manager()
    entry = _trade(manager, "BUY", "c-long-entry")
    assert entry["success"] is True

    price.price = 101.0
    result = _trade(manager, "SELL", "c-long-close")

    assert result["success"] is True
    assert result["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert result["closed"] is True
    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.trade_history[-1]["reason"] == "MANUAL_CLOSE"
    # No reverse position was created.
    assert portfolio.positions.get(SYMBOL) is None


def test_manual_close_short_is_full_close_and_never_reverses():
    manager, engine, portfolio, price, _rec = _build_manager()
    entry = _trade(manager, "SELL", "c-short-entry")
    assert entry["success"] is True

    price.price = 99.0
    result = _trade(manager, "BUY", "c-short-close")

    assert result["success"] is True
    assert result["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert engine.actual_position is None
    assert portfolio.positions == {}


def test_same_side_denied_for_long_and_short():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    assert _trade(manager, "BUY", "ss-1")["success"] is True
    denied = _trade(manager, "BUY", "ss-2")
    assert denied["success"] is False
    assert denied["operation"] == "DENY_SAME_SIDE"
    # Still exactly one position.
    assert engine.actual_position["side"] == "BUY"


def test_manual_close_denied_when_quantity_mismatch():
    manager, engine, portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "mm-1")["success"] is True
    # Corrupt the portfolio quantity so it no longer matches the engine.
    portfolio.positions[SYMBOL]["size"] = 999.0
    result = _trade(manager, "SELL", "mm-2")
    assert result["success"] is False
    assert result["reason"] == "POSITION_PORTFOLIO_QUANTITY_MISMATCH"
    assert engine.actual_position is not None


def test_manual_close_denied_when_portfolio_position_missing():
    manager, engine, portfolio, _price, _rec = _build_manager()
    assert _trade(manager, "BUY", "pm-1")["success"] is True
    portfolio.positions.clear()
    result = _trade(manager, "SELL", "pm-2")
    assert result["success"] is False
    assert result["reason"] == "PORTFOLIO_POSITION_MISSING"
    assert engine.actual_position is not None


# =========================
# IDEMPOTENCY
# =========================

def test_duplicate_entry_request_produces_one_fill():
    manager, engine, portfolio, _price, _rec = _build_manager()
    first = _trade(manager, "BUY", "dup-entry")
    second = _trade(manager, "BUY", "dup-entry")

    assert first == second
    assert len(engine.paper_fills) == 1
    assert len(portfolio.positions) == 1
    assert len(engine.paper_orders) == 1


def test_duplicate_close_request_produces_one_close():
    manager, engine, _portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "dup-close-entry")["success"] is True
    price.price = 101.0
    first = _trade(manager, "SELL", "dup-close")
    second = _trade(manager, "SELL", "dup-close")
    assert first == second
    assert len(engine.trade_history) == 1


def test_request_id_reuse_with_different_side_denied():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    assert _trade(manager, "BUY", "reuse-1")["success"] is True
    reused = _trade(manager, "SELL", "reuse-1")
    assert reused["success"] is False
    assert reused["reason"] == "REQUEST_ID_REUSED"


# =========================
# STALE INTENT
# =========================

def test_stale_control_revision_denied():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    result = _trade(
        manager, "BUY", "stale-rev",
        expectedControlRevision=manager.control_revision - 1,
    )
    assert result["success"] is False
    assert result["reason"] == "DENY_STALE_CONTROL_REVISION"
    assert engine.actual_position is None


def test_stale_symbol_denied():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    result = _trade(
        manager, "BUY", "stale-sym", expectedSymbol="BTCUSDT"
    )
    assert result["success"] is False
    assert result["reason"] == "DENY_STALE_INTENT"
    assert engine.actual_position is None


def test_manual_entry_never_recalculates_after_approval(monkeypatch):
    """Lose MM approval inside a real reservation, not before admission."""
    manager, engine, _portfolio, _price, recorder = _build_manager()
    original = engine.try_entry

    def expired(signal):
        engine.clear_execution_entry_preflight(signal["traceId"])
        return original(signal)

    monkeypatch.setattr(engine, "try_entry", expired)
    result = _trade(manager, "BUY", "stale-quantity")
    assert result["success"] is False
    assert result["reason"] == "DENY_STALE_INTENT"
    assert len(recorder.intents) == 1
    assert engine.actual_position is None


# =========================
# SHARED CLOSE BOUNDARY
# =========================

def test_manual_close_vs_tp_race_commits_one_close():
    manager, engine, portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "race-tp-entry")["success"] is True

    # Auto exit (TP) wins the race before the human close is applied.
    price.price = 102.0
    engine.on_price(SYMBOL, 102.0)
    assert engine.actual_position is None
    history_after_tp = len(engine.trade_history)
    assert history_after_tp == 1

    result = _trade(manager, "SELL", "race-tp-close")
    assert result["success"] is False
    # FLAT + SELL is a new entry, but the cooldown/existing state means it
    # must not double-close or reverse the already-closed position.
    assert len(engine.trade_history) == 1
    assert engine.actual_position is None or (
        engine.actual_position.get("entry_authority") == "MANUAL"
    )
    # No second close history record was created.
    assert all(
        record.get("reason") != "MANUAL_CLOSE"
        for record in engine.trade_history
    )


def test_manual_close_vs_sl_race_commits_one_close():
    manager, engine, _portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "race-sl-entry")["success"] is True
    price.price = 98.0
    engine.on_price(SYMBOL, 98.0)
    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert engine.trade_history[0]["reason"] == "SL"

    result = _trade(manager, "SELL", "race-sl-close")
    assert result["success"] is False
    assert len(engine.trade_history) == 1


def test_engine_close_reservation_denies_reentrant_close():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    assert _trade(manager, "BUY", "res-1")["success"] is True

    engine.close_reservation = {
        "positionId": engine.actual_position["order_id"],
        "reason": "TP",
        "startedAt": time.time(),
    }
    try:
        result = engine.close_position(101.0, "SL")
    finally:
        engine.close_reservation = None

    assert isinstance(result, dict)
    assert result["reason"] == "CLOSE_IN_PROGRESS"
    assert engine.actual_position is not None
    assert engine.trade_history == []


def test_concurrent_engine_closes_commit_only_once():
    manager, engine, _portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "res-2")["success"] is True

    entered = threading.Event()
    release = threading.Event()
    results = []

    original = engine._close_position_body

    def slow_close(close_price, reason):
        entered.set()
        release.wait(timeout=2)
        return original(close_price, reason)

    engine._close_position_body = slow_close

    def first():
        results.append(engine.close_position(101.0, "TP"))

    def second():
        results.append(engine.close_position(101.0, "SL"))

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    assert entered.wait(timeout=2)
    t2.start()
    time.sleep(0.05)
    release.set()
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert engine.actual_position is None
    assert len(engine.trade_history) == 1
    assert results.count(None) >= 1


# =========================
# AUTO EXIT PRESERVATION
# =========================

def test_manual_position_still_has_existing_auto_exit():
    manager, engine, portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "auto-exit-entry")["success"] is True
    assert engine.actual_position is not None

    # The existing TP authority closes a manually opened position.
    price.price = 102.0
    engine.on_price(SYMBOL, 102.0)

    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.trade_history[-1]["reason"] == "TP"
    assert engine.trade_history[-1]["pnl"] == pytest.approx(2.0)


# =========================
# MM / ACCOUNT / MARKERS
# =========================

def test_manual_entry_and_close_update_account_and_markers():
    manager, engine, _portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "acct-1")["success"] is True

    account = manager._capture_account_snapshot()
    assert account["position"] is not None
    assert account["position"]["entry_authority"] == "MANUAL"

    price.price = 101.0
    assert _trade(manager, "SELL", "acct-2")["success"] is True

    account_after = manager._capture_account_snapshot()
    assert account_after["position"] is None
    assert account_after["positions"] == []

    markers = build_paper_execution_markers(
        engine,
        active_symbol=SYMBOL,
        context_key=CONTEXT_KEY,
        runtime_instance_id=RUNTIME_ID,
    )
    types = [marker["type"] for marker in markers]
    assert set(types) == {"ENTRY", "EXIT"}


def test_manual_entry_marker_carries_manual_authority():
    manager, engine, _portfolio, _price, _rec = _build_manager()
    assert _trade(manager, "BUY", "marker-1")["success"] is True
    markers = build_paper_execution_markers(
        engine,
        active_symbol=SYMBOL,
        context_key=CONTEXT_KEY,
        runtime_instance_id=RUNTIME_ID,
    )
    assert markers[0]["type"] == "ENTRY"
    assert markers[0].get("entryAuthority") == "MANUAL"


def test_manual_close_updates_money_management_projection():
    manager, engine, _portfolio, price, _rec = _build_manager()
    assert _trade(manager, "BUY", "mm-close-1")["success"] is True
    before = manager._money_management_runtime_event_signature()
    assert before["position"] is not None

    price.price = 101.0
    assert _trade(manager, "SELL", "mm-close-2")["success"] is True
    after = manager._money_management_runtime_event_signature()
    assert after["position"] is None
    assert after["balance"] == pytest.approx(1001.0)


# =========================
# PREPARATION (READ ONLY)
# =========================

def test_manual_preparation_is_read_only_candidate():
    manager, engine, _portfolio, _price, recorder = _build_manager()
    before_calls = len(recorder.intents)
    before_position = copy.deepcopy(engine.actual_position)

    preparation = manager.get_manual_trade_preparation()

    assert preparation["controlAuthority"] == CONTROL_AUTHORITY_MANUAL
    assert preparation["positionState"] == "FLAT"
    assert preparation["candidate"]["state"] == "CANDIDATE"
    assert preparation["candidate"]["quantityUnit"] == "coin"
    # No MM preflight side effect and no position mutation.
    assert len(recorder.intents) == before_calls
    assert engine.actual_position == before_position
