"""TRADINGAI-MANUAL-TRADING-D4: PAPER end-to-end acceptance.

Production-like PAPER acceptance for the D3 manual entry/close implementation.
These tests drive the real BotManager / ExecutionEngine / PortfolioManager /
money-management projection / paper markers through a complete cycle:

    MANUAL -> PAPER -> Canonical Active Symbol -> BUY/SELL
      -> existing MM/governance -> existing PAPER execution -> Fill
      -> Position -> Manual Close OR Auto Exit -> FLAT -> History
      -> Marker -> Result -> MM / Account status

They never place a LIVE order, never call an exchange, never start a runtime and
never mutate production state. ``exchange=None`` is the existing PAPER
simulation boundary.

Matrix:
  A. FLAT -> BUY -> LONG -> SELL -> FLAT
  B. FLAT -> SELL -> SHORT -> BUY -> FLAT
  C. FLAT -> Manual Entry -> Auto Exit -> FLAT
  D. duplicate requestId -> exactly-once
  E. open position -> CONTROL switch attempt -> DENY
  F. Market Selection AUTO + Execution Control MANUAL -> BOT entry denied
  G. UNKNOWN / PENDING -> backend deny
"""

import os
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
RUNTIME_ID = "manual-d4-runtime-1"
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


def _build_manager(price=100.0, position_size=100.0, selection_mode="MANUAL"):
    """Production-like PAPER runtime: real manager, engine, portfolio, guards."""

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
    engine.set_execution_entry_guard(recorder)
    # Production installs the manager-owned shared authority boundary on the
    # engine. Installing it here exercises the full authority chain (BOT
    # suppression and MANUAL revalidation), not only the manager pre-checks.
    engine.set_execution_authority_guard(
        manager._dispatch_execution_authority_guard
    )

    manager.engine = engine
    manager.config = {"mode": "paper", "dry_run": True}
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "RUNNING"
    manager._running = True
    manager.active_runtime_id = RUNTIME_ID
    manager._active_symbol = SYMBOL
    manager.selection_mode = selection_mode
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


def _markers(engine):
    return build_paper_execution_markers(
        engine,
        active_symbol=SYMBOL,
        context_key=CONTEXT_KEY,
        runtime_instance_id=RUNTIME_ID,
    )


def _marker_types(engine):
    return [marker["type"] for marker in _markers(engine)]


# =========================
# A. MANUAL LONG -> MANUAL CLOSE
# =========================

def test_d4_e2e_a_manual_long_then_manual_close():
    manager, engine, portfolio, price, recorder = _build_manager()
    preview_qty = engine.get_result()["preview"]["qty"]

    assert manager._execution_control_position_state() == "FLAT"
    preparation = manager.get_manual_trade_preparation()
    assert preparation["positionState"] == "FLAT"
    assert preparation["candidate"]["quantity"] == preview_qty

    entry = _trade(manager, "BUY", "d4-a-entry")
    assert entry["success"] is True
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_LONG
    assert entry["entryAuthority"] == "MANUAL"
    assert entry["mode"] == "paper"
    assert entry["symbol"] == SYMBOL
    assert entry["controlAuthority"] == "MANUAL"
    assert manager._execution_control_position_state() == "LONG"

    position = engine.actual_position
    assert position["side"] == "BUY"
    assert position["entry_authority"] == "MANUAL"
    assert position["request_id"] == "d4-a-entry"

    # Quantity identity: preview == MM request == MM approved == submitted
    # == filled == position coin qty.
    approved = entry["approvedQuantity"]
    assert float(recorder.intents[-1].requested_quantity) == pytest.approx(approved)
    assert approved == pytest.approx(preview_qty)
    assert engine.paper_orders[-1]["qty"] == pytest.approx(approved)
    assert engine.paper_fills[-1]["qty"] == pytest.approx(approved)
    assert position["coin_qty"] == pytest.approx(approved)
    assert portfolio.positions[SYMBOL]["size"] == pytest.approx(approved)

    # Exactly one ENTRY fill, one order, one open position.
    assert len(engine.paper_orders) == 1
    assert len(engine.paper_fills) == 1
    assert engine.paper_fills[0]["fillType"] == "ENTRY"
    assert engine.paper_fills[0]["entryAuthority"] == "MANUAL"

    # ENTRY marker is generated from the fill identity, not the UI.
    entry_markers = _markers(engine)
    assert [m["type"] for m in entry_markers] == ["ENTRY"]
    assert entry_markers[0]["entryAuthority"] == "MANUAL"
    assert entry_markers[0]["symbol"] == SYMBOL
    assert entry_markers[0]["quantity"] == pytest.approx(approved)

    # Account / MM reflect the open MANUAL position.
    account_open = manager._capture_account_snapshot()
    assert account_open["position"] is not None
    assert account_open["position"]["entry_authority"] == "MANUAL"
    assert account_open["realizedPnl"] == pytest.approx(0.0)
    assert manager._money_management_runtime_event_signature()["position"] is not None
    assert engine.pending_order is False

    # MANUAL CLOSE (SELL on a LONG) is a full close, never a reversal.
    price.price = 101.0
    close = _trade(manager, "SELL", "d4-a-close")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert close["closed"] is True
    assert close["closeReason"] == "MANUAL_CLOSE"
    assert close["quantity"] == pytest.approx(approved)
    assert close["positionId"] == entry["positionId"]

    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert manager._execution_control_position_state() == "FLAT"
    assert engine.pending_order is False

    # Exactly one CLOSE fill, one CLOSED history, one realized PnL event.
    assert len(engine.paper_orders) == 1
    assert len(engine.paper_fills) == 2
    close_fill = engine.paper_fills[-1]
    assert close_fill["fillType"] == "CLOSE"
    assert close_fill["reason"] == "MANUAL_CLOSE"
    assert close_fill["qty"] == pytest.approx(approved)
    assert close_fill["tradeId"] == entry["positionId"]

    assert len(engine.trade_history) == 1
    history = engine.trade_history[-1]
    assert history["status"] == "CLOSED"
    assert history["reason"] == "MANUAL_CLOSE"
    assert history["side"] == "BUY"
    assert history["qty"] == pytest.approx(approved)
    assert history["entryPrice"] == pytest.approx(100.0)
    assert history["exitPrice"] == pytest.approx(101.0)
    assert history["pnl"] == pytest.approx(1.0)
    assert history["balanceAfter"] == pytest.approx(1001.0)

    # No reverse SHORT position was created.
    assert portfolio.positions.get(SYMBOL) is None
    assert engine.pnl == pytest.approx(1.0)
    assert portfolio.balance == pytest.approx(1001.0)

    # EXIT marker bound to the same lifecycle.
    exit_markers = _markers(engine)
    assert set(m["type"] for m in exit_markers) == {"ENTRY", "EXIT"}
    assert len(exit_markers) == 2
    exit_marker = next(m for m in exit_markers if m["type"] == "EXIT")
    assert exit_marker["reason"] == "MANUAL_CLOSE"
    assert exit_marker["tradeId"] == entry["positionId"]

    # Result / MM / account after close.
    result = engine.get_result()
    assert result["balance"] == pytest.approx(1001.0)
    assert result["pnl"] == pytest.approx(1.0)
    account_closed = manager._capture_account_snapshot()
    assert account_closed["position"] is None
    assert account_closed["positions"] == []
    assert account_closed["realizedPnl"] == pytest.approx(1.0)
    assert account_closed["equity"] == pytest.approx(1001.0)
    mm_after = manager._money_management_runtime_event_signature()
    assert mm_after["position"] is None
    assert mm_after["balance"] == pytest.approx(1001.0)


# =========================
# B. MANUAL SHORT -> MANUAL CLOSE
# =========================

def test_d4_e2e_b_manual_short_then_manual_close():
    manager, engine, portfolio, price, recorder = _build_manager()
    preview_qty = engine.get_result()["preview"]["qty"]

    entry = _trade(manager, "SELL", "d4-b-entry")
    assert entry["success"] is True
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_SHORT
    assert entry["entryAuthority"] == "MANUAL"
    assert manager._execution_control_position_state() == "SHORT"

    position = engine.actual_position
    assert position["side"] == "SELL"
    assert position["entry_authority"] == "MANUAL"

    approved = entry["approvedQuantity"]
    assert float(recorder.intents[-1].requested_quantity) == pytest.approx(approved)
    assert approved == pytest.approx(preview_qty)
    assert engine.paper_orders[-1]["qty"] == pytest.approx(approved)
    assert engine.paper_fills[-1]["qty"] == pytest.approx(approved)
    assert position["coin_qty"] == pytest.approx(approved)
    assert portfolio.positions[SYMBOL]["size"] == pytest.approx(approved)

    assert _marker_types(engine) == ["ENTRY"]

    price.price = 99.0
    close = _trade(manager, "BUY", "d4-b-close")
    assert close["success"] is True
    assert close["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert close["closed"] is True
    assert close["quantity"] == pytest.approx(approved)

    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert manager._execution_control_position_state() == "FLAT"
    assert engine.pending_order is False

    # No reverse LONG position was created.
    assert portfolio.positions.get(SYMBOL) is None
    assert len(engine.trade_history) == 1
    history = engine.trade_history[-1]
    assert history["reason"] == "MANUAL_CLOSE"
    assert history["side"] == "SELL"
    assert history["pnl"] == pytest.approx(1.0)
    assert engine.pnl == pytest.approx(1.0)

    assert sorted(_marker_types(engine)) == ["ENTRY", "EXIT"]

    account = manager._capture_account_snapshot()
    assert account["position"] is None
    assert account["realizedPnl"] == pytest.approx(1.0)


# =========================
# C. MANUAL ENTRY -> AUTO EXIT
# =========================

def test_d4_e2e_c_manual_entry_auto_exit_preserves_manual_provenance():
    manager, engine, portfolio, price, _rec = _build_manager()

    entry = _trade(manager, "BUY", "d4-c-entry")
    assert entry["success"] is True
    assert engine.actual_position["entry_authority"] == "MANUAL"
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_LONG

    # The existing automated TP authority closes the manually opened position.
    price.price = 102.0
    engine.on_price(SYMBOL, 102.0)

    assert engine.actual_position is None
    assert portfolio.positions == {}
    assert engine.pending_order is False
    assert manager._execution_control_position_state() == "FLAT"

    # One close only, through the existing automated exit path.
    assert len(engine.trade_history) == 1
    history = engine.trade_history[-1]
    assert history["reason"] == "TP"
    assert history["pnl"] == pytest.approx(2.0)
    assert len(engine.paper_fills) == 2
    assert engine.paper_fills[-1]["fillType"] == "CLOSE"
    assert engine.paper_fills[-1]["reason"] == "TP"

    # Manual close was NOT used to fake the auto exit.
    assert all(
        record.get("reason") != "MANUAL_CLOSE"
        for record in engine.trade_history
    )

    # The MANUAL entry provenance survives into the ENTRY marker.
    markers = _markers(engine)
    assert sorted(m["type"] for m in markers) == ["ENTRY", "EXIT"]
    entry_marker = next(m for m in markers if m["type"] == "ENTRY")
    exit_marker = next(m for m in markers if m["type"] == "EXIT")
    assert entry_marker["entryAuthority"] == "MANUAL"
    assert exit_marker["reason"] == "TP"
    assert exit_marker["tradeId"] == entry["positionId"]

    account = manager._capture_account_snapshot()
    assert account["position"] is None
    assert account["realizedPnl"] == pytest.approx(2.0)
    assert account["equity"] == pytest.approx(1002.0)


# =========================
# D. DUPLICATE REQUEST ID -> EXACTLY ONCE
# =========================

def test_d4_e2e_d_duplicate_entry_and_close_are_exactly_once():
    manager, engine, portfolio, price, _rec = _build_manager()

    first = _trade(manager, "BUY", "d4-d-entry")
    duplicate = _trade(manager, "BUY", "d4-d-entry")
    assert first == duplicate
    assert len(engine.paper_orders) == 1
    assert len(engine.paper_fills) == 1
    assert len(portfolio.positions) == 1
    assert len(engine.trade_history) == 0

    price.price = 101.0
    close_first = _trade(manager, "SELL", "d4-d-close")
    close_duplicate = _trade(manager, "SELL", "d4-d-close")
    assert close_first == close_duplicate
    assert close_first["closed"] is True

    # Exactly one close fill, one CLOSED history, one PnL event.
    assert len(engine.paper_fills) == 2
    assert len(engine.trade_history) == 1
    assert engine.pnl == pytest.approx(1.0)
    assert engine.actual_position is None

    # A requestId reused for a different intent is denied, never executed.
    reused = _trade(manager, "SELL", "d4-d-entry")
    assert reused["success"] is False
    assert reused["reason"] == "REQUEST_ID_REUSED"
    assert len(engine.paper_orders) == 1
    assert len(engine.trade_history) == 1
    assert engine.actual_position is None


# =========================
# E. CONTROL SWITCH WHILE OPEN
# =========================

def test_d4_e2e_e_control_switch_denied_while_open_allowed_after_flat():
    manager, engine, portfolio, price, _rec = _build_manager()

    assert _trade(manager, "BUY", "d4-e-entry")["success"] is True
    revision_before = manager.control_revision

    denied = manager.set_execution_control(CONTROL_AUTHORITY_BOT)
    assert denied["success"] is False
    assert denied["reason"] == "POSITION_LONG_BLOCKS_CONTROL_SWITCH"
    assert manager.control_authority == CONTROL_AUTHORITY_MANUAL
    assert manager.control_revision == revision_before
    # The position was not closed or transferred by the denied switch.
    assert engine.actual_position is not None
    assert engine.actual_position["entry_authority"] == "MANUAL"
    assert portfolio.positions.get(SYMBOL) is not None

    price.price = 101.0
    assert _trade(manager, "SELL", "d4-e-close")["success"] is True
    assert engine.actual_position is None

    allowed = manager.set_execution_control(CONTROL_AUTHORITY_BOT)
    assert allowed["success"] is True
    assert manager.control_authority == CONTROL_AUTHORITY_BOT
    assert manager.control_revision == revision_before + 1


# =========================
# F. AUTO MARKET SELECTION + MANUAL CONTROL
# =========================

def test_d4_e2e_f_auto_market_selection_with_manual_control_denies_bot_entry():
    manager, engine, portfolio, _price, _rec = _build_manager(
        selection_mode="AUTO"
    )
    assert manager.selection_mode == "AUTO"
    assert manager.control_authority == CONTROL_AUTHORITY_MANUAL

    # The runtime / market automation stays alive; AUTO selection is unchanged.
    assert manager.lifecycle_state == "RUNNING"
    assert manager.loop_state == "RUNNING"
    assert manager._running is True
    assert manager.selection_mode == "AUTO"

    # A BOT strategy signal is denied at the shared authority boundary before
    # any MM preflight, order or position mutation.
    bot_decision = manager._authorize_bot_execution_entry({"side": "BUY"})
    assert bot_decision["allowed"] is False
    assert bot_decision["reason"] == "BOT_ENTRY_LOCKED_MANUAL_CONTROL"

    bot_entry = engine.try_entry({"id": "d4-f-bot", "side": "BUY"})
    assert bot_entry["submitted"] is False
    assert engine.paper_orders == []
    assert engine.actual_position is None

    # The human retains BUY/SELL direction authority.
    entry = _trade(manager, "BUY", "d4-f-manual")
    assert entry["success"] is True
    assert entry["operation"] == MANUAL_OPERATION_ENTRY_LONG
    assert engine.actual_position["entry_authority"] == "MANUAL"

    # MM was only ever requested for the human entry.
    assert len(_rec.intents) == 1


# =========================
# G. UNKNOWN / PENDING BACKEND DENY
# =========================

def test_d4_e2e_g_unknown_and_pending_are_denied_backend():
    manager, engine, _portfolio, _price, _rec = _build_manager()

    # UNKNOWN side: the backend resolves it to UNKNOWN (never FLAT) and denies.
    engine.actual_position = {"state": "OPEN", "side": "???", "qty": 1}
    assert manager._execution_control_position_state() == "UNKNOWN"
    unknown = _trade(manager, "BUY", "d4-g-unknown")
    assert unknown["success"] is False
    assert unknown["reason"] == "MANUAL_POSITION_UNKNOWN"
    assert unknown["operation"] == "DENY"
    assert len(engine.paper_orders) == 0

    # PENDING order present -> deny.
    engine.actual_position = None
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": True,
        "pending": True,
        "safe": False,
        "pending_order": True,
        "reason": "PENDING_ORDER_REMAINING",
    }
    pending = _trade(manager, "BUY", "d4-g-pending")
    assert pending["success"] is False
    assert pending["reason"] == "PENDING_ORDER_REMAINING"
    assert engine.paper_orders == []
    assert engine.actual_position is None

    # Unknown pending authority fails closed too.
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": False,
        "pending": None,
        "safe": False,
        "pending_order": None,
        "reason": "PENDING_ORDER_UNKNOWN",
    }
    pending_unknown = _trade(manager, "BUY", "d4-g-pending-unknown")
    assert pending_unknown["success"] is False
    assert pending_unknown["reason"] == "PENDING_ORDER_UNKNOWN"
    assert engine.paper_orders == []


# =========================
# SYMBOL / CONTEXT GUARD
# =========================

def test_d4_symbol_context_guard_denies_stale_symbol_intent():
    manager, engine, _portfolio, _price, _rec = _build_manager()

    stale = _trade(manager, "BUY", "d4-sym-stale", expectedSymbol="BTCUSDT")
    assert stale["success"] is False
    assert stale["reason"] == "DENY_STALE_INTENT"
    assert engine.actual_position is None
    assert engine.paper_orders == []

    # The canonical active symbol is the execution symbol.
    assert manager.activeSymbol == SYMBOL
    assert engine.symbol == SYMBOL
    valid = _trade(manager, "BUY", "d4-sym-valid", expectedSymbol=SYMBOL)
    assert valid["success"] is True
    assert valid["symbol"] == SYMBOL
    assert engine.actual_position["runtimeSymbolContext"]["symbol"] == SYMBOL
