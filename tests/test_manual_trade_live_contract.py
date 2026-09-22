"""TRADINGAI-MANUAL-TRADING-D7: MANUAL LIVE contract (no real orders).

Proves that MANUAL is an entry authority, not a PAPER-only feature, and that a
resolved LIVE manual request is routed through the existing canonical LIVE
ExecutionEngine path (same MM, Governance, entry admission and reduceOnly
close primitive as BOT LIVE).

Every test is isolated: the exchange boundary is mocked, no real order is ever
submitted, no real position is created and no LIVE runtime is started.
"""

import os
import time

os.environ.setdefault("TEST_MODE", "1")

from unittest.mock import Mock, patch

import pytest

from backend import config as backend_config
from backend.bot_manager.bot_manager import (
    BotManager,
    CONTROL_AUTHORITY_MANUAL,
    MANUAL_OPERATION_CLOSE_LONG,
    MANUAL_OPERATION_CLOSE_SHORT,
    MANUAL_OPERATION_ENTRY_LONG,
    MANUAL_OPERATION_ENTRY_SHORT,
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
from Bot.engine.execution_engine import ExecutionEngine

from datetime import datetime, timezone


SYMBOL = "XRPUSDT"
EXCHANGE_SYMBOL = "XRPUSDTM"
RUNTIME_ID = "manual-live-runtime-1"


class PriceManager:
    def __init__(self, price):
        self.price = price

    def get_current_price(self):
        return self.price


class AdmissionRecorder:
    """Records MM intents and allows entry (the canonical MM boundary)."""

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


def _flat_position_authority():
    return {
        "success": True,
        "exchange": "kucoin",
        "source": "kucoin",
        "found": False,
        "symbol": EXCHANGE_SYMBOL,
        "quantity": 0.0,
        "signed_quantity": 0.0,
        "entry_price": None,
        "timestamp": time.time(),
    }


def _live_position(side="BUY", qty=10):
    return {
        "symbol": EXCHANGE_SYMBOL,
        "qty": qty,
        "side": side,
        "entry_price": 100.0,
    }


def _fake_exchange():
    exchange = Mock()
    exchange.api_key = "k"
    exchange.api_secret = "s"
    exchange.passphrase = "p"
    exchange.get_symbol_rules.return_value = {
        "multiplier": 0.001,
        "min_size": 1,
    }
    exchange.get_balance.return_value = 1000.0
    exchange.place_order.return_value = {
        "success": True,
        "order_id": "live-entry-1",
        "raw": {"orderId": "live-entry-1"},
    }
    exchange.get_positions.return_value = None
    exchange.get_open_orders.return_value = {
        "success": True,
        "count": 0,
        "orders": [],
        "timestamp": time.time(),
    }
    exchange.flatten_current_position.return_value = {
        "accepted": True,
        "confirmed": False,
        "skipped": False,
        "order_id": "live-close-1",
        "symbol": EXCHANGE_SYMBOL,
        "final_position": _flat_position_authority(),
    }
    return exchange


@pytest.fixture(autouse=True)
def _reset_governance():
    previous = dict(governance_state)
    governance_state["control_authority"] = "BOT"
    governance_state["control_revision"] = 0
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    yield
    governance_state.clear()
    governance_state.update(previous)


def _build_live_manager(exchange=None):
    exchange = exchange or _fake_exchange()
    manager = BotManager()
    portfolio = PortfolioManager(1000.0)
    engine = ExecutionEngine(
        exchange=exchange,
        portfolio=portfolio,
        price_manager=PriceManager(100.0),
    )
    engine.symbol = SYMBOL
    engine.set_config({
        "mode": "live",
        "dry_run": False,
        "position_size": 100.0,
        "leverage": 5,
        "sl_percent": 1,
        "tp_percent": 2,
        "liveOrderEntryAllowed": True,
        "realOrderAllowed": True,
        "executionEntryAllowed": True,
        "effective_leverage": 5,
    })
    engine.mode = "live"
    engine.config["mode"] = "live"
    engine.config["dry_run"] = False
    engine.config["liveOrderEntryAllowed"] = True
    engine.config["realOrderAllowed"] = True
    engine.config["executionEntryAllowed"] = True
    engine.config["effective_leverage"] = 5
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100.0
    engine.balance_check_ok = True
    engine.position_check_ok = True
    engine.balance_check_error = None
    engine.position_check_error = None
    engine.real_balance = 1000.0
    engine.real_equity = 1000.0

    recorder = AdmissionRecorder()
    engine.set_execution_entry_guard(recorder)
    engine.set_execution_authority_guard(
        manager._dispatch_execution_authority_guard
    )

    manager.engine = engine
    manager.config = {"mode": "live", "dry_run": False}
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

    manager.loop_state = "STOPPED"
    assert governance_state["execution_enabled"] is False

    return manager, engine, exchange, recorder


def _trade(manager, action, request_id, **extra):
    payload = {
        "action": action, "requestId": request_id,
        "expectedMode": manager.config["mode"],
        "expectedSymbol": manager.activeSymbol,
        "expectedControlRevision": manager.control_revision,
    }
    payload.update(extra)
    return manager.execute_manual_trade(payload)


@pytest.fixture(autouse=True)
def _live_env():
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(
        backend_config, "TRADE_MODE", "live"
    ):
        yield


# =========================
# MODE RESOLUTION
# =========================

def test_live_manual_mode_resolves_to_live():
    manager, _engine, _exchange, _rec = _build_live_manager()
    assert manager._manual_trade_mode() == "live"
    prep = manager.get_manual_trade_preparation()
    assert prep["mode"] == "live"


def test_divergent_mode_authority_fails_closed():
    manager, engine, _exchange, _rec = _build_live_manager()
    engine.config["mode"] = "paper"
    assert manager._manual_trade_mode() == ""
    result = _trade(manager, "BUY", "divergent-1")
    assert result["success"] is False
    assert result["reason"] == "MANUAL_MODE_UNRESOLVED"


# =========================
# LIVE ENTRY -> canonical LIVE adapter
# =========================

def test_live_manual_entry_long_routes_to_live_adapter():
    exchange = _fake_exchange()
    exchange.get_positions.return_value = _live_position("BUY", 10)
    manager, engine, exchange, recorder = _build_live_manager(exchange)

    result = _trade(manager, "BUY", "live-long-1")

    assert result["success"] is True
    assert result["mode"] == "live"
    assert result["operation"] == MANUAL_OPERATION_ENTRY_LONG
    assert exchange.place_order.call_count == 1
    _, kwargs = exchange.place_order.call_args
    assert kwargs["symbol"] == SYMBOL
    assert kwargs["side"] == "BUY"
    # Canonical MM boundary was invoked exactly once.
    assert len(recorder.intents) == 1
    # The simulated PAPER portfolio never received a fabricated position.
    assert engine.portfolio.get_positions().get(SYMBOL) is None


def test_live_manual_entry_short_routes_to_live_adapter():
    exchange = _fake_exchange()
    exchange.get_positions.return_value = _live_position("SELL", 10)
    manager, engine, exchange, recorder = _build_live_manager(exchange)

    result = _trade(manager, "SELL", "live-short-1")

    assert result["success"] is True
    assert result["mode"] == "live"
    assert result["operation"] == MANUAL_OPERATION_ENTRY_SHORT
    assert exchange.place_order.call_count == 1
    _, kwargs = exchange.place_order.call_args
    assert kwargs["side"] == "SELL"
    assert engine.portfolio.get_positions().get(SYMBOL) is None


def test_live_manual_entry_blocked_when_disarmed():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    engine.config["liveOrderEntryAllowed"] = False
    engine.config["realOrderAllowed"] = False
    engine.config["executionEntryAllowed"] = False

    result = _trade(manager, "BUY", "live-disarmed-1")

    assert result["success"] is False
    assert result["reason"] == "LIVE_ORDER_ENTRY_DISARMED"
    assert exchange.place_order.call_count == 0


def test_live_manual_entry_allowed_with_loop_and_auto_trade_off():
    exchange = _fake_exchange()
    exchange.get_positions.return_value = _live_position("BUY", 10)
    manager, engine, exchange, recorder = _build_live_manager(exchange)
    assert manager.loop_state == "STOPPED"
    assert governance_state["execution_enabled"] is False
    result = _trade(manager, "BUY", "live-exec-off-1")
    assert result["success"] is True
    assert len(recorder.intents) == 1
    exchange.place_order.assert_called_once()
    assert manager.loop_state == "STOPPED"
    assert governance_state["execution_enabled"] is False


def test_live_manual_entry_blocked_by_emergency():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    governance_state["emergency_stop"] = True
    governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED

    result = _trade(manager, "BUY", "live-emergency-1")

    assert result["success"] is False
    assert result["reason"] == "EMERGENCY_STOP_ACTIVE"
    assert exchange.place_order.call_count == 0


def test_live_manual_entry_blocked_by_pending_order():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    manager.get_authoritative_pending_order_state = lambda **kw: {
        "known": True,
        "pending": True,
        "safe": False,
        "pending_order": True,
        "reason": "PENDING_ORDER_REMAINING",
    }

    result = _trade(manager, "BUY", "live-pending-1")

    assert result["success"] is False
    assert result["reason"] == "PENDING_ORDER_REMAINING"
    assert exchange.place_order.call_count == 0


def test_live_manual_entry_requires_manual_control():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    manager.control_authority = "BOT"

    result = _trade(manager, "BUY", "live-bot-control-1")

    assert result["success"] is False
    assert result["reason"] == "MANUAL_CONTROL_REQUIRED"
    assert exchange.place_order.call_count == 0


# =========================
# POSITION SEMANTICS / REVERSAL
# =========================

def test_live_manual_same_side_entry_is_denied():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    engine.actual_position = _live_position("BUY", 10)

    result = _trade(manager, "BUY", "live-same-side-1")

    assert result["success"] is False
    assert result["reason"] == "MANUAL_SAME_SIDE_DENIED"
    assert exchange.place_order.call_count == 0


# =========================
# LIVE CLOSE -> canonical reduceOnly flatten
# =========================

def test_live_manual_close_long_uses_reduce_only_flatten():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    engine.actual_position = _live_position("BUY", 10)

    result = _trade(manager, "SELL", "live-close-long-1")

    assert result["success"] is True
    assert result["mode"] == "live"
    assert result["operation"] == MANUAL_OPERATION_CLOSE_LONG
    assert exchange.flatten_current_position.call_count == 1
    # Close must never be submitted as a blind opposite entry.
    assert exchange.place_order.call_count == 0
    assert engine.actual_position is None


def test_live_manual_close_short_uses_reduce_only_flatten():
    exchange = _fake_exchange()
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    engine.actual_position = _live_position("SELL", 10)

    result = _trade(manager, "BUY", "live-close-short-1")

    assert result["success"] is True
    assert result["mode"] == "live"
    assert result["operation"] == MANUAL_OPERATION_CLOSE_SHORT
    assert exchange.flatten_current_position.call_count == 1
    assert exchange.place_order.call_count == 0
    assert engine.actual_position is None


def test_live_manual_close_unconfirmed_preserves_position():
    exchange = _fake_exchange()
    # Adapter accepted the close but exchange evidence is not confirmed.
    exchange.flatten_current_position.return_value = {
        "accepted": True,
        "confirmed": False,
        "skipped": False,
        "order_id": "live-close-unconfirmed",
        "symbol": EXCHANGE_SYMBOL,
        "final_position": {
            "success": True,
            "found": True,
            "quantity": 10.0,
            "signed_quantity": 10.0,
            "timestamp": time.time(),
        },
    }
    manager, engine, exchange, _rec = _build_live_manager(exchange)
    engine.actual_position = _live_position("BUY", 10)

    result = _trade(manager, "SELL", "live-close-unconfirmed-1")

    assert result["success"] is False
    # Fail closed: the local position is preserved, never fabricated flat.
    assert engine.actual_position is not None


# Work D authority/Governance repair: all exchange effects below are mocks.
from backend.runtime.governance_runtime import GovernanceRuntime
from backend.auto_market_selection.live_status_consistency import derive_live_readiness


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_manual_mm_then_governance_then_execution_order(monkeypatch, side):
    manager, engine, exchange, recorder = _build_live_manager()
    exchange.get_positions.return_value = _live_position(side)
    events = []
    mm = engine.preflight_execution_entry
    governance = GovernanceRuntime.evaluate_entry

    def preflight(*args):
        events.append("MM")
        return mm(*args)

    def decision(self, *args, **kwargs):
        events.append("GOVERNANCE")
        return governance(self, *args, **kwargs)

    engine.preflight_execution_entry = preflight
    monkeypatch.setattr(GovernanceRuntime, "evaluate_entry", decision)
    exchange.place_order.side_effect = lambda **kw: (events.append("EXCHANGE") or {"success": True})
    assert _trade(manager, side, "ordered-" + side)["success"] is True
    assert events == ["MM", "GOVERNANCE", "GOVERNANCE", "EXCHANGE"]
    assert engine.execution_entry_preapproval is None
    assert manager.execution_admission_reservation is None


@pytest.mark.parametrize("reason", ["NO_TRADE_ZONE", "GOVERNANCE_SUSPENDED"])
def test_manual_canonical_governance_deny_clears_mm(monkeypatch, reason):
    manager, engine, exchange, recorder = _build_live_manager()
    if reason == "NO_TRADE_ZONE":
        monkeypatch.setitem(governance_state, "no_trade_zone", True)
    else:
        monkeypatch.setattr(GovernanceRuntime, "evaluate_entry", lambda *a, **kw: {
            "allowed": False, "reason": reason, "direction": None,
        })
    result = _trade(manager, "BUY", "gov-denied")
    assert result["reason"] == reason
    assert len(recorder.intents) == 1
    assert engine.execution_entry_preapproval is None
    assert manager.execution_admission_reservation is None
    exchange.place_order.assert_not_called()


def test_manual_mm_deny_never_reaches_governance(monkeypatch):
    manager, engine, exchange, _ = _build_live_manager()
    engine.set_execution_entry_guard(lambda intent: None)
    decision = Mock(side_effect=AssertionError("Governance must follow MM ALLOW"))
    monkeypatch.setattr(GovernanceRuntime, "evaluate_entry", decision)
    assert _trade(manager, "BUY", "mm-denied")["success"] is False
    decision.assert_not_called()
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("field", ["realOrderAllowed", "executionEntryAllowed", "liveOrderEntryAllowed"])
def test_manual_each_live_permission_is_required(field):
    manager, engine, exchange, _ = _build_live_manager()
    engine.config[field] = False
    assert _trade(manager, "BUY", field)["reason"] == "LIVE_ORDER_ENTRY_DISARMED"
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("context", [
    {"expectedControlRevision": 0}, {"expectedMode": "paper"},
    {"expectedSymbol": "BTCUSDTM"},
])
def test_manual_stale_identity_denied(context):
    manager, engine, exchange, _ = _build_live_manager()
    assert _trade(manager, "BUY", "stale", **context)["success"] is False
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("missing", ["expectedMode", "expectedSymbol", "expectedControlRevision"])
def test_manual_missing_identity_denied_in_schema_and_manager(missing):
    from backend.api.bot_api import ManualTradeRequest
    from pydantic import ValidationError
    manager, engine, exchange, _ = _build_live_manager()
    payload = {"action": "BUY", "requestId": "missing", "expectedMode": "live",
               "expectedSymbol": SYMBOL, "expectedControlRevision": manager.control_revision}
    del payload[missing]
    with pytest.raises(ValidationError):
        ManualTradeRequest(**payload)
    assert manager.execute_manual_trade(payload)["reason"] == "MANUAL_INTENT_CONTEXT_REQUIRED"
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("pending", [
    {"known": False, "pending": None, "safe": False},
    {"known": True, "pending": False, "safe": False},
])
def test_manual_unknown_or_unsafe_pending_denied(pending):
    manager, engine, exchange, _ = _build_live_manager()
    manager.get_authoritative_pending_order_state = lambda **kw: pending
    assert _trade(manager, "BUY", "unsafe")["success"] is False
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("origin", [None, "BOT", "MANUAL", "FORGED"])
def test_unreserved_or_unknown_live_origin_cannot_submit(origin):
    manager, engine, exchange, _ = _build_live_manager()
    signal = {"side": "BUY", "id": "forged", "entryAuthority": origin,
              "governanceAllowed": True, "boundQuantity": 1}
    assert engine.try_entry(signal)["success"] is False
    exchange.place_order.assert_not_called()
    engine.set_execution_authority_guard(None)
    assert engine.try_entry(signal)["reason"] == "EXECUTION_AUTHORITY_UNKNOWN"
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("loop,auto,allowed", [
    ("STOPPED", False, False), ("STOPPED", True, False),
    ("RUNNING", False, False), ("RUNNING", True, True),
])
def test_bot_admission_still_requires_automation(loop, auto, allowed):
    manager, engine, exchange, _ = _build_live_manager()
    manager.control_authority = "BOT"
    manager.loop_state = loop
    governance_state["execution_enabled"] = auto
    manager._begin_execution_admission("BOT")
    decision = manager._dispatch_execution_authority_guard({
        "side": "BUY", "entryAuthority": "BOT",
        "runtimeSymbolContext": manager._manual_runtime_symbol_context(SYMBOL),
    })
    assert decision["allowed"] is allowed
    exchange.place_order.assert_not_called()


@pytest.mark.parametrize("change", ["governance", "revision", "pending", "runtime", "quantity"])
def test_manual_rechecks_context_at_execution_boundary(monkeypatch, change):
    manager, engine, exchange, _ = _build_live_manager()
    original = engine.try_entry

    def changed(signal):
        if change == "governance":
            monkeypatch.setitem(governance_state, "no_trade_zone", True)
        elif change == "revision":
            manager.control_revision += 1
        elif change == "pending":
            manager.pending_order = True
            manager.get_authoritative_pending_order_state = lambda **kw: {"known": True, "pending": True, "safe": False}
        elif change == "runtime":
            manager.lifecycle_state = "STOPPED"
        elif change == "quantity":
            signal["boundQuantity"] *= 2
        return original(signal)

    monkeypatch.setattr(engine, "try_entry", changed)
    assert _trade(manager, "BUY", "changed")["success"] is False
    exchange.place_order.assert_not_called()
    assert engine.execution_entry_preapproval is None


def test_manual_status_preserves_arm_and_auto_trade_separation():
    manager, engine, exchange, _ = _build_live_manager()
    readiness = derive_live_readiness(engine.build_live_readiness())
    assert readiness["realOrderAllowed"] is True
    assert readiness["executionEnabled"] is False
    engine.config["liveOrderEntryAllowed"] = False
    readiness = derive_live_readiness(engine.build_live_readiness())
    assert readiness["realOrderAllowed"] is False
    assert "LIVE_ORDER_ENTRY_DISARMED" in readiness["blockReasons"]


def test_shared_governance_preserves_bot_and_manual_rules(monkeypatch):
    runtime = GovernanceRuntime()
    strategy = {"direction": "BUY", "executionAllowed": True}
    assert runtime.process_governance(strategy)["reason"] == "EXECUTION_DISABLED"
    assert runtime.evaluate_entry("BUY", entry_authority="MANUAL")["allowed"] is True
    monkeypatch.setitem(governance_state, "execution_enabled", True)
    assert runtime.process_governance(strategy)["allowed"] is True
    monkeypatch.setitem(governance_state, "no_trade_zone", True)
    assert runtime.process_governance(strategy)["reason"] == "NO_TRADE_ZONE"
    assert runtime.evaluate_entry("BUY", entry_authority="MANUAL")["reason"] == "NO_TRADE_ZONE"
    assert runtime.evaluate_entry("BUY", entry_authority="UNKNOWN")["allowed"] is False


@pytest.mark.parametrize("failure", ["runtime", "local_risk", "credentials", "contract"])
def test_manual_other_final_safety_gates_preserved(failure):
    manager, engine, exchange, _ = _build_live_manager()
    if failure == "runtime":
        manager.lifecycle_state = "STOPPED"
    elif failure == "local_risk":
        engine.update_drawdown_state = lambda: {"riskTradingDisabled": True}
    elif failure == "credentials":
        engine._exchange_credentials_ready = lambda: False
    else:
        exchange.get_symbol_rules.return_value = {"multiplier": 0, "min_size": 1}
    assert _trade(manager, "BUY", failure)["success"] is False
    exchange.place_order.assert_not_called()


def test_governance_exception_releases_reservation_and_mm(monkeypatch):
    manager, engine, exchange, _ = _build_live_manager()
    monkeypatch.setattr(GovernanceRuntime, "evaluate_entry", Mock(side_effect=RuntimeError("unavailable")))
    with pytest.raises(RuntimeError):
        _trade(manager, "BUY", "exception")
    assert manager.execution_admission_reservation is None
    assert engine.execution_entry_preapproval is None
    exchange.place_order.assert_not_called()


def test_manual_arm_does_not_allow_automatic_bot_intent():
    manager, engine, exchange, _ = _build_live_manager()
    manager._begin_execution_admission("BOT")
    result = engine.try_entry({
        "id": "automatic", "side": "BUY", "entryAuthority": "BOT",
        "runtimeSymbolContext": manager._manual_runtime_symbol_context(SYMBOL),
    })
    assert result["reason"] == "BOT_ENTRY_LOCKED_MANUAL_CONTROL"
    exchange.place_order.assert_not_called()


def test_same_request_id_cannot_rebind_new_control_revision():
    manager, engine, exchange, _ = _build_live_manager()
    engine.config["liveOrderEntryAllowed"] = False
    assert _trade(manager, "BUY", "same")["success"] is False
    manager.control_revision += 1
    assert _trade(manager, "BUY", "same")["reason"] == "REQUEST_ID_REUSED"
    exchange.place_order.assert_not_called()
