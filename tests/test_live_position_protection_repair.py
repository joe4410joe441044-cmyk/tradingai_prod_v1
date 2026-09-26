"""TRADINGAI-WORK-AA-LIVE-POSITION-SLTP-MULTIPLIER-REPAIR-1.

Defect (Audit C, post-E2E003 authority audit):
    A LIVE position was replaced by the exchange-shaped dict returned from
    ``KucoinTradeClient.get_positions`` (symbol/qty/side/entry_price only) in
    both LIVE sync paths (ExecutionEngine.start() and the try_entry post-fill
    sync).  ``on_price`` then read ``sl``/``tp`` with a default of 0: a LONG was
    closed as "TP" and a SHORT as "SL" on the first tick, and the contract
    multiplier fell back to 0.001 in on_price and _close_position_body.

Coverage A-G of the repair task.  Everything is an offline test double: the
exchange is a ``Mock``, close is recorded (or the reduce-only primitive is a
mock), durable trade recording is stubbed and outbound sockets are blocked,
so no real exchange order can ever be generated.
"""

import socket
import time
from unittest.mock import Mock, patch

import pytest

import backend.config as backend_config
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import governance_state
from Bot.engine.execution_engine import (
    LIVE_POSITION_PROTECTION_UNAVAILABLE,
    ExecutionEngine,
)
from sizing_support import account, contract_rules, install_sizing


ENTRY = 0.00217          # GALAUSDTM-like price scale
SL_PCT = 1.0
TP_PCT = 1.0


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in this suite")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    # Durable Stage-13 recording must never touch a real store from tests.
    import backend.runtime.parameter_performance as parameter_performance
    monkeypatch.setattr(parameter_performance, "record_completed_trade", lambda *a, **k: False)
    monkeypatch.setenv("TRADING_E2E_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    saved = dict(governance_state)
    yield
    governance_state.clear()
    governance_state.update(saved)


def _exchange_position(side, qty=364.0, entry=ENTRY, symbol="GALAUSDTM"):
    """Exact shape produced by KucoinTradeClient.get_positions."""
    return {"symbol": symbol, "qty": qty, "side": side, "entry_price": entry}


def _mock_exchange(position, multiplier, symbol="GALAUSDT"):
    exchange = Mock()
    exchange.api_key = "k"
    exchange.api_secret = "s"
    exchange.passphrase = "p"
    exchange.get_account_overview.return_value = account()
    exchange.get_positions.return_value = position
    exchange.get_symbol_rules.return_value = contract_rules(symbol, multiplier=multiplier)
    exchange.place_order.return_value = {"success": True}
    return exchange


def _live_engine(exchange, symbol="GALAUSDT", sl_pct=SL_PCT, tp_pct=TP_PCT, trailing=False):
    engine = ExecutionEngine(exchange=exchange, portfolio=PortfolioManager(1000.0))
    engine.symbol = symbol
    engine.mode = "live"
    engine.config["mode"] = "live"
    engine.config["dry_run"] = False
    engine.config["sl_percent"] = sl_pct
    engine.config["tp_percent"] = tp_pct
    engine.config["trailing_stop"] = trailing
    engine.config["leverage"] = 5
    engine.config["effective_leverage"] = 5
    engine.update_drawdown_state = lambda *a, **k: {"riskTradingDisabled": False}
    return engine


def _record_closes(engine):
    closes = []
    engine.close_position = lambda price, reason: closes.append((price, reason))
    return closes


def _start_synced(side, multiplier=1.0, qty=364.0, entry=ENTRY, record=True, **engine_kwargs):
    exchange = _mock_exchange(_exchange_position(side, qty=qty, entry=entry), multiplier)
    engine = _live_engine(exchange, **engine_kwargs)
    engine.start()
    assert engine.status == "RUNNING"
    closes = _record_closes(engine) if record else None
    return engine, exchange, closes


def _entry_synced(side, multiplier=1.0, qty=364.0, entry=ENTRY):
    """Drive the real try_entry LIVE branch with a mocked adapter (no network)."""
    exchange = _mock_exchange(None, multiplier)
    engine = _live_engine(exchange)
    install_sizing(engine)
    exchange.get_symbol_rules.return_value = contract_rules("GALAUSDT", multiplier=multiplier)
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = entry
    engine.config["realOrderAllowed"] = True
    engine.config["executionEntryAllowed"] = True
    engine.config["liveOrderEntryAllowed"] = True
    engine.get_price = lambda: entry
    engine.get_result = lambda: {"preview": {"qty": qty * multiplier, "valid": True}}
    engine.refresh_balance = lambda: None
    engine.set_execution_authority_guard(lambda signal: {"allowed": True, "entryAuthority": "BOT"})
    engine._live_order_allowed = lambda authority_context: True
    engine._evaluate_execution_entry_guard = lambda order: (True, None)
    exchange.get_positions.return_value = _exchange_position(side, qty=qty, entry=entry)
    engine.try_entry({"id": f"live-{side}", "side": side, "qty": qty * multiplier})
    exchange.place_order.assert_called_once()
    assert engine.actual_position, "LIVE branch did not sync the exchange position"
    engine.status = "RUNNING"
    closes = _record_closes(engine)
    return engine, exchange, closes


def _confirmed_close(engine):
    calls = []

    def _close(symbol):
        calls.append(symbol)
        return {"success": True, "status": "CONFIRMED", "confirmed": True, "closed": True,
                "accepted": True, "order_id": "close-1", "symbol": "GALAUSDTM"}
    engine._live_close_via_exchange = _close
    return calls


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------

def test_control_explicit_levels_first_in_range_tick_does_not_close():
    engine, _, closes = _start_synced("BUY")
    engine.actual_position = dict(engine.actual_position, sl=ENTRY * 0.99, tp=ENTRY * 1.01, multiplier=1.0)
    engine.on_price("GALAUSDT", ENTRY)
    assert closes == []


# ---------------------------------------------------------------------------
# A / B: LIVE LONG / SHORT reconstruction (both sync paths)
# ---------------------------------------------------------------------------

def test_start_sync_long_first_in_range_tick_is_not_false_tp():
    engine, exchange, closes = _start_synced("BUY")
    engine.on_price("GALAUSDT", ENTRY)
    assert closes == [], f"LONG closed on first in-range tick: {closes}"
    exchange.place_order.assert_not_called()


def test_start_sync_short_first_in_range_tick_is_not_false_sl():
    engine, exchange, closes = _start_synced("SELL")
    engine.on_price("GALAUSDT", ENTRY)
    assert closes == [], f"SHORT closed on first in-range tick: {closes}"
    exchange.place_order.assert_not_called()


def test_start_sync_long_protection_levels_reconstructed():
    engine, _, _ = _start_synced("BUY")
    pos = engine.actual_position
    assert pos.get("sl") == pytest.approx(ENTRY * (1 - SL_PCT / 100)), pos
    assert pos.get("tp") == pytest.approx(ENTRY * (1 + TP_PCT / 100)), pos
    assert pos["sl"] < ENTRY < pos["tp"]
    assert pos["state"] == "OPEN" and pos["protection_state"] == "ACTIVE"


def test_start_sync_short_protection_levels_reconstructed():
    engine, _, _ = _start_synced("SELL")
    pos = engine.actual_position
    assert pos.get("sl") == pytest.approx(ENTRY * (1 + SL_PCT / 100)), pos
    assert pos.get("tp") == pytest.approx(ENTRY * (1 - TP_PCT / 100)), pos
    assert pos["tp"] < ENTRY < pos["sl"]


def test_entry_sync_long_first_in_range_tick_is_not_false_tp():
    engine, _, closes = _entry_synced("BUY")
    engine.on_price("GALAUSDT", ENTRY)
    assert closes == [], f"LONG closed on first in-range tick after entry: {closes}"


def test_entry_sync_short_first_in_range_tick_is_not_false_sl():
    engine, _, closes = _entry_synced("SELL")
    engine.on_price("GALAUSDT", ENTRY)
    assert closes == [], f"SHORT closed on first in-range tick after entry: {closes}"


@pytest.mark.parametrize("path", ["start", "entry"])
def test_a_long_tp_crossing_closes_as_tp(path):
    engine, _, closes = (_start_synced if path == "start" else _entry_synced)("BUY")
    engine.on_price("GALAUSDT", ENTRY * 1.004)
    assert closes == []
    engine.on_price("GALAUSDT", ENTRY * 1.0101)
    assert [reason for _, reason in closes] == ["TP"]


@pytest.mark.parametrize("path", ["start", "entry"])
def test_a_long_sl_crossing_closes_as_sl(path):
    engine, _, closes = (_start_synced if path == "start" else _entry_synced)("BUY")
    engine.on_price("GALAUSDT", ENTRY * 0.996)
    assert closes == []
    engine.on_price("GALAUSDT", ENTRY * 0.9899)
    assert [reason for _, reason in closes] == ["SL"]


@pytest.mark.parametrize("path", ["start", "entry"])
def test_b_short_tp_crossing_closes_as_tp(path):
    engine, _, closes = (_start_synced if path == "start" else _entry_synced)("SELL")
    engine.on_price("GALAUSDT", ENTRY * 0.996)
    assert closes == []
    engine.on_price("GALAUSDT", ENTRY * 0.9899)
    assert [reason for _, reason in closes] == ["TP"]


@pytest.mark.parametrize("path", ["start", "entry"])
def test_b_short_sl_crossing_closes_as_sl(path):
    engine, _, closes = (_start_synced if path == "start" else _entry_synced)("SELL")
    engine.on_price("GALAUSDT", ENTRY * 1.004)
    assert closes == []
    engine.on_price("GALAUSDT", ENTRY * 1.0101)
    assert [reason for _, reason in closes] == ["SL"]


# ---------------------------------------------------------------------------
# C: resync keeps / reconstructs protection; trailed SL is preserved
# ---------------------------------------------------------------------------

def test_c_resync_same_position_preserves_trailed_sl():
    engine, exchange, closes = _start_synced("BUY", trailing=True)
    initial_sl = engine.actual_position["sl"]
    engine.on_price("GALAUSDT", ENTRY * 1.005)       # trails the SL upward, no TP
    trailed_sl = engine.actual_position["sl"]
    assert trailed_sl > initial_sl and closes == []
    engine.start()                                     # normal resync without sl/tp fields
    pos = engine.actual_position
    assert pos["sl"] == pytest.approx(trailed_sl)
    assert pos["tp"] == pytest.approx(ENTRY * 1.01)
    assert pos["multiplier"] == 1.0 and pos["protection_state"] == "ACTIVE"


def test_c_resync_keeps_multiplier_when_contract_read_fails():
    engine, exchange, _ = _start_synced("BUY", multiplier=10.0, qty=5.0)
    exchange.get_symbol_rules.side_effect = RuntimeError("contract endpoint down")
    engine._sizing_contract_cache = None
    engine.start()
    pos = engine.actual_position
    assert pos["multiplier"] == 10.0
    assert pos["sl"] == pytest.approx(ENTRY * 0.99) and pos["tp"] == pytest.approx(ENTRY * 1.01)
    assert engine.live_position_protection_status()["state"] == "ACTIVE"


def test_c_resync_new_entry_price_reconstructs_levels():
    engine, exchange, _ = _start_synced("BUY")
    new_entry = ENTRY * 1.02
    exchange.get_positions.return_value = _exchange_position("BUY", qty=500.0, entry=new_entry)
    engine.start()
    pos = engine.actual_position
    assert pos["sl"] == pytest.approx(new_entry * 0.99)
    assert pos["tp"] == pytest.approx(new_entry * 1.01)
    assert pos["qty"] == 500.0


def test_c_resync_uses_sizing_contract_cache_when_fresh_read_fails():
    exchange = _mock_exchange(_exchange_position("BUY", qty=5.0), 10.0)
    engine = _live_engine(exchange)
    engine._sizing_contract_cache = ("GALAUSDT", time.time(), contract_rules("GALAUSDT", multiplier=10.0))
    exchange.get_symbol_rules.side_effect = RuntimeError("contract endpoint down")
    engine.start()
    assert engine.actual_position["multiplier"] == 10.0
    assert engine.actual_position["protection_state"] == "ACTIVE"


# ---------------------------------------------------------------------------
# D: authoritative multiplier (never 0.001) in position, unrealized, realized PnL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("multiplier", [1.0, 10.0])
def test_start_sync_position_carries_contract_multiplier(multiplier):
    engine, _, _ = _start_synced("BUY", multiplier=multiplier, qty=5.0)
    assert engine.actual_position.get("multiplier") == multiplier, engine.actual_position
    assert engine.actual_position["coin_qty"] == pytest.approx(5.0 * multiplier)


def test_start_sync_unrealized_pnl_uses_contract_multiplier():
    multiplier, qty = 1.0, 364.0
    engine, _, _ = _start_synced("BUY", multiplier=multiplier, qty=qty)
    price = ENTRY * 1.005   # inside the 1% bracket
    engine.on_price("GALAUSDT", price)
    expected = (price - ENTRY) * qty * multiplier
    assert engine.unrealized_pnl == pytest.approx(expected), (engine.unrealized_pnl, expected)


@pytest.mark.parametrize("multiplier,side", [(1.0, "BUY"), (10.0, "BUY"), (10.0, "SELL")])
def test_d_unrealized_pnl_multiplier(multiplier, side):
    engine, _, _ = _start_synced(side, multiplier=multiplier, qty=5.0)
    price = ENTRY * (1.005 if side == "BUY" else 0.995)
    engine.on_price("GALAUSDT", price)
    direction = 1 if side == "BUY" else -1
    assert engine.unrealized_pnl == pytest.approx(direction * (price - ENTRY) * 5.0 * multiplier)
    assert engine.unrealized_pnl_available is True


@pytest.mark.parametrize("multiplier", [1.0, 10.0])
def test_d_close_realized_pnl_uses_contract_multiplier(multiplier):
    engine, _, _ = _start_synced("BUY", multiplier=multiplier, qty=5.0, record=False)
    _confirmed_close(engine)
    pnl_before = engine.pnl
    exit_price = ENTRY * 1.0101
    engine.close_position(exit_price, "TP")
    expected = (exit_price - ENTRY) * 5.0 * multiplier
    assert engine.actual_position is None
    assert engine.pnl - pnl_before == pytest.approx(expected)
    record = engine.trade_history[-1]
    assert record["estimatedPnl"] == pytest.approx(expected)
    assert record["estimatedPnlAvailable"] is True
    assert record["qty"] == pytest.approx(5.0 * multiplier)


def test_d_invalid_multiplier_marks_pnl_unavailable_never_0001():
    exchange = _mock_exchange(_exchange_position("BUY", qty=5.0), None)
    engine = _live_engine(exchange)
    engine.start()
    pos = engine.actual_position
    assert "multiplier" not in pos and pos["protection_state"] == "UNAVAILABLE"
    closes = _record_closes(engine)
    engine.on_price("GALAUSDT", ENTRY * 1.5)
    assert engine.unrealized_pnl == 0.0 and engine.unrealized_pnl_available is False
    assert closes == []
    del engine.close_position
    _confirmed_close(engine)
    engine.close_position(ENTRY * 1.5, "MANUAL")
    record = engine.trade_history[-1]
    assert record["estimatedPnl"] is None and record["estimatedPnlAvailable"] is False
    assert engine.actual_position is None


def test_d_status_metrics_unavailable_without_live_multiplier():
    exchange = _mock_exchange(_exchange_position("BUY", qty=5.0), None)
    engine = _live_engine(exchange)
    engine.start()
    metrics = engine._active_position_metrics()
    assert metrics["activePositionQty"] is None and metrics["activePositionNotional"] is None


# ---------------------------------------------------------------------------
# E: missing / zero protection cannot false-trigger; fail closed and visible
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sl_pct,tp_pct", [(0, 1.0), (1.0, 0), (None, None)])
def test_e_invalid_settings_mark_protection_unavailable(sl_pct, tp_pct):
    engine, _, closes = _start_synced("BUY", sl_pct=sl_pct, tp_pct=tp_pct)
    pos = engine.actual_position
    assert pos["protection_state"] == "UNAVAILABLE"
    assert "sl" not in pos and "tp" not in pos
    for price in (ENTRY * 0.5, ENTRY, ENTRY * 2):
        engine.on_price("GALAUSDT", price)
    assert closes == []
    status = engine.live_position_protection_status()
    assert status["state"] == "UNAVAILABLE" and status["protected"] is False and status["reasons"]


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_e_zero_levels_never_trigger(side):
    engine, _, closes = _start_synced(side)
    engine.actual_position = dict(engine.actual_position, sl=0, tp=0)
    for price in (ENTRY * 0.5, ENTRY, ENTRY * 2):
        engine.on_price("GALAUSDT", price)
    assert closes == []
    assert engine.live_position_protection_status()["state"] == "UNAVAILABLE"


def test_e_contract_symbol_mismatch_is_unavailable():
    exchange = _mock_exchange(_exchange_position("BUY"), 1.0)
    exchange.get_symbol_rules.return_value = contract_rules("DYMUSDT", multiplier=0.1)
    engine = _live_engine(exchange)
    engine.start()
    assert engine.actual_position["protection_state"] == "UNAVAILABLE"
    assert "LIVE_CONTRACT_METADATA_MISMATCH" in engine.actual_position["protection_reason"]


def test_e_unprotected_live_position_blocks_entry_and_arm_visibly():
    engine, exchange, _ = _start_synced("BUY", sl_pct=0)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(backend_config, "TRADE_MODE", "live"):
        governance_state["execution_enabled"] = True
        governance_state["emergency_stop"] = False
        engine.config["liveOrderEntryAllowed"] = True
        readiness = engine.build_live_readiness(entry_authority="BOT")
        assert LIVE_POSITION_PROTECTION_UNAVAILABLE in readiness["blockReasons"]
        assert readiness["realOrderAllowed"] is False
        assert readiness["livePositionProtection"]["state"] == "UNAVAILABLE"
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False
        engine.config["liveOrderEntryAllowed"] = False
        arm = engine.set_live_order_entry_authority(True)
        assert arm["success"] is False
        assert LIVE_POSITION_PROTECTION_UNAVAILABLE in arm["blockReasons"]
    exchange.place_order.assert_not_called()


def test_e_protected_live_position_has_no_protection_block_reason():
    engine, _, _ = _start_synced("BUY")
    readiness = engine.build_live_readiness(entry_authority="BOT")
    assert LIVE_POSITION_PROTECTION_UNAVAILABLE not in readiness["blockReasons"]
    assert readiness["livePositionProtection"]["state"] == "ACTIVE"
    assert readiness["livePositionProtection"]["stopLoss"] == pytest.approx(ENTRY * 0.99)


def test_e_unprotected_position_close_remains_available():
    engine, _, _ = _start_synced("BUY", sl_pct=0, record=False)
    calls = _confirmed_close(engine)
    engine.close_position(ENTRY, "EMERGENCY_MANUAL")
    assert calls == ["GALAUSDT"] and engine.actual_position is None


# ---------------------------------------------------------------------------
# F: PAPER SL/TP behavior unchanged
# ---------------------------------------------------------------------------

def _paper_engine():
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    exchange.place_order.return_value = {"success": True}
    engine = ExecutionEngine(exchange=exchange, portfolio=PortfolioManager(1000.0))
    engine.mode = "paper"
    engine.symbol = "XRPUSDT"
    install_sizing(engine)
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    engine.config["leverage"] = 5
    engine.config["sl_percent"] = 1.0
    engine.config["tp_percent"] = 1.0
    engine.config["trailing_stop"] = False
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100
    engine.config["dry_run"] = True
    engine.get_price = lambda: 100
    engine.get_result = lambda: {"preview": {"qty": 1, "valid": True}}
    engine.refresh_balance = lambda: None
    engine._evaluate_execution_entry_guard = lambda order: (True, None)
    engine.update_drawdown_state = lambda *a, **k: {"riskTradingDisabled": False}
    return engine, exchange


@pytest.mark.parametrize("side,tp_price,sl_price", [("BUY", 101.01, 98.99), ("SELL", 98.99, 101.01)])
def test_f_paper_sl_tp_unchanged(side, tp_price, sl_price):
    for target, expected in ((tp_price, "TP"), (sl_price, "SL")):
        engine, exchange = _paper_engine()
        engine.try_entry({"id": "paper-1", "side": side, "qty": 1})
        pos = engine.actual_position
        assert pos and pos["multiplier"] == 1 and "protection_state" not in pos
        if side == "BUY":
            assert pos["sl"] == pytest.approx(99.0) and pos["tp"] == pytest.approx(101.0)
        else:
            assert pos["sl"] == pytest.approx(101.0) and pos["tp"] == pytest.approx(99.0)
        engine.status = "RUNNING"
        closes = _record_closes(engine)
        engine.on_price("XRPUSDT", 100)
        assert closes == []
        engine.on_price("XRPUSDT", target)
        assert [reason for _, reason in closes] == [expected]
        exchange.place_order.assert_not_called()
        assert engine.live_position_protection_status()["state"] == "NOT_LIVE"


def test_f_paper_position_without_multiplier_keeps_legacy_default():
    engine, _ = _paper_engine()
    engine.config["mode"] = "paper"
    engine.actual_position = {"state": "OPEN", "side": "BUY", "qty": 10, "entry_price": 100,
                              "sl": 99.0, "tp": 101.0}
    engine.status = "RUNNING"
    _record_closes(engine)
    engine.on_price("XRPUSDT", 100.5)
    assert engine.unrealized_pnl == pytest.approx(0.5 * 10 * 0.001)


# ---------------------------------------------------------------------------
# G: DISARMED + Governance OFF with a synthetic LIVE position
# ---------------------------------------------------------------------------

def _disarmed_gov_off(engine):
    engine.config["liveOrderEntryAllowed"] = False
    engine.config["realOrderAllowed"] = False
    engine.config["executionEntryAllowed"] = False
    governance_state["execution_enabled"] = False
    governance_state["emergency_stop"] = False


def test_g_disarmed_gov_off_denies_new_entry():
    engine, exchange, _ = _start_synced("BUY")
    _disarmed_gov_off(engine)
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(backend_config, "TRADE_MODE", "live"):
        readiness = engine.build_live_readiness(entry_authority="BOT")
        assert {"EXECUTION_DISABLED", "LIVE_ORDER_ENTRY_DISARMED"} <= set(readiness["blockReasons"])
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False
        engine.try_entry({"id": "live-2", "side": "BUY", "qty": 364.0})
    exchange.place_order.assert_not_called()


def test_g_disarmed_gov_off_natural_sl_exit_still_fires():
    engine, _, closes = _start_synced("BUY")
    _disarmed_gov_off(engine)
    engine.on_price("GALAUSDT", ENTRY * 0.9899)
    assert [reason for _, reason in closes] == ["SL"]


def test_g_disarmed_gov_off_strategy_exit_still_fires():
    engine, _, closes = _start_synced("SELL")
    _disarmed_gov_off(engine)
    engine.exit_evaluator = lambda state, info: {"decision": "EXIT", "reason": "MOMENTUM_DECAY"}
    engine.on_price("GALAUSDT", ENTRY, microstructure_state={"k": 1})
    assert [reason for _, reason in closes] == ["MOMENTUM_DECAY"]


def test_g_disarmed_gov_off_reduce_only_close_primitive_is_used():
    engine, exchange, _ = _start_synced("BUY", record=False)
    _disarmed_gov_off(engine)
    exchange.flatten_current_position.return_value = {"accepted": False, "error_code": "TEST_REJECT"}
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(backend_config, "TRADE_MODE", "live"):
        result = engine.close_position(ENTRY * 0.9899, "SL")
    exchange.flatten_current_position.assert_called_once_with("GALAUSDT")
    exchange.place_order.assert_not_called()
    assert result["status"] == "REJECTED" and engine.actual_position is not None


def test_g_disarmed_gov_off_safety_close_confirmed_clears_position():
    engine, _, _ = _start_synced("BUY", record=False)
    _disarmed_gov_off(engine)
    calls = _confirmed_close(engine)
    engine.close_position(ENTRY, "SAFETY_CLOSE")
    assert calls == ["GALAUSDT"] and engine.actual_position is None


# ---------------------------------------------------------------------------
# H (phase 4a): LIVE close with unavailable PnL never books a fabricated 0
# ---------------------------------------------------------------------------

from Bot.engine.execution_engine import LIVE_PNL_ACCOUNTING_UNAVAILABLE  # noqa: E402


def _unavailable_multiplier_closed_engine():
    exchange = _mock_exchange(_exchange_position("BUY", qty=5.0), None)
    engine = _live_engine(exchange)
    del engine.update_drawdown_state          # use the real risk gate
    engine.start()
    assert engine.actual_position["protection_state"] == "UNAVAILABLE"
    engine.peak_equity = engine.initial_equity = engine._current_equity()
    engine.current_drawdown_pct = 0.0
    before = {"pnl": engine.pnl, "balance": engine.balance,
              "portfolio": engine.portfolio.balance,
              "drawdown": engine.current_drawdown_pct,
              "halted": engine.risk_trading_disabled}
    _confirmed_close(engine)
    engine.close_position(ENTRY * 0.5, "MANUAL")
    assert engine.actual_position is None
    return engine, exchange, before


def test_h_unavailable_close_pnl_is_not_booked_as_zero():
    engine, _, before = _unavailable_multiplier_closed_engine()
    assert engine.pnl == before["pnl"]
    assert engine.balance == before["balance"]
    assert engine.portfolio.balance == before["portfolio"]
    assert engine.live_pnl_accounting_unavailable["reason"] == LIVE_PNL_ACCOUNTING_UNAVAILABLE
    record = engine.trade_history[-1]
    assert record["estimatedPnl"] is None and record["estimatedPnlAvailable"] is False
    risk = engine.get_risk_state()
    assert risk["pnlAccountingAvailable"] is False
    assert risk["pnlAccountingBlockReason"] == LIVE_PNL_ACCOUNTING_UNAVAILABLE


def test_h_unavailable_close_pnl_blocks_new_live_entry_visibly():
    engine, exchange, _ = _unavailable_multiplier_closed_engine()
    with patch.object(backend_config, "ALLOW_LIVE", True), patch.object(backend_config, "TRADE_MODE", "live"):
        governance_state["execution_enabled"] = True
        governance_state["emergency_stop"] = False
        engine.config["liveOrderEntryAllowed"] = True
        readiness = engine.build_live_readiness(entry_authority="BOT")
        assert LIVE_PNL_ACCOUNTING_UNAVAILABLE in readiness["blockReasons"]
        assert readiness["realOrderAllowed"] is False
        assert readiness["livePnlAccounting"]["state"] == "UNAVAILABLE"
        assert engine._live_order_allowed({"entryAuthority": "BOT"}) is False
    exchange.place_order.assert_not_called()


def test_h_drawdown_is_not_recomputed_from_non_authoritative_equity():
    engine, _, before = _unavailable_multiplier_closed_engine()
    engine.update_drawdown_state(1.0)          # would be ~100% drawdown
    assert engine.current_drawdown_pct == before["drawdown"]
    assert engine.risk_trading_disabled == before["halted"]


def test_h_resolved_by_canonical_live_account_equity():
    engine, _, _ = _unavailable_multiplier_closed_engine()
    assert engine.apply_live_risk_equity_authority(
        initial_equity=900.0, peak_equity=1000.0,
        authority_source="REAL_LIVE_ACCOUNT_EQUITY") is True
    assert engine.live_pnl_accounting_unavailable is None
    assert engine.balance == 900.0
    assert engine.current_drawdown_pct == pytest.approx(10.0)
    assert engine.get_risk_state()["pnlAccountingAvailable"] is True
    assert LIVE_PNL_ACCOUNTING_UNAVAILABLE not in engine.build_live_readiness()["blockReasons"]


def test_h_not_resolved_by_non_canonical_authority_or_bad_balance():
    engine, exchange, _ = _unavailable_multiplier_closed_engine()
    assert engine.apply_live_risk_equity_authority(
        initial_equity=900.0, peak_equity=1000.0,
        authority_source="PAPER_RUNTIME_EQUITY") is False
    exchange.get_balance.return_value = 0.0
    engine.refresh_balance()
    assert engine.live_pnl_accounting_unavailable is not None


def test_h_resolved_by_authoritative_exchange_balance_refresh():
    engine, exchange, _ = _unavailable_multiplier_closed_engine()
    exchange.get_balance.return_value = 950.0
    engine.refresh_balance()
    assert engine.live_pnl_accounting_unavailable is None
    assert engine.balance == 950.0


def test_h_unrealized_unavailable_does_not_move_drawdown():
    exchange = _mock_exchange(_exchange_position("BUY", qty=5.0), None)
    engine = _live_engine(exchange)
    del engine.update_drawdown_state
    engine.start()
    engine.peak_equity = engine.initial_equity = engine._current_equity()
    engine.current_drawdown_pct = 0.0
    _record_closes(engine)
    engine.on_price("GALAUSDT", ENTRY * 0.1)
    assert engine.unrealized_pnl_available is False
    assert engine.current_drawdown_pct == 0.0
    risk = engine.get_risk_state()
    assert risk["pnlAccountingAvailable"] is False
    assert risk["pnlAccountingBlockReason"] == "LIVE_UNREALIZED_PNL_UNAVAILABLE"


def test_h_valid_live_close_still_books_pnl_and_sets_no_flag():
    engine, _, _ = _start_synced("BUY", multiplier=10.0, qty=5.0, record=False)
    _confirmed_close(engine)
    pnl_before, balance_before = engine.pnl, engine.balance
    exit_price = ENTRY * 1.0101
    engine.close_position(exit_price, "TP")
    expected = (exit_price - ENTRY) * 5.0 * 10.0
    assert engine.pnl - pnl_before == pytest.approx(expected)
    assert engine.balance - balance_before == pytest.approx(expected)
    assert engine.live_pnl_accounting_unavailable is None
    assert engine.get_risk_state()["pnlAccountingAvailable"] is True


def test_h_paper_close_accounting_unchanged():
    engine, _ = _paper_engine()
    engine.try_entry({"id": "paper-h", "side": "BUY", "qty": 1})
    engine.status = "RUNNING"
    balance_before = engine.portfolio.balance
    engine.close_position(101.0, "TP")
    assert engine.actual_position is None
    assert engine.live_pnl_accounting_unavailable is None
    assert engine.trade_history[-1]["pnl"] == pytest.approx(1.0)
    assert engine.portfolio.balance - balance_before == pytest.approx(1.0)
    assert engine.get_risk_state()["pnlAccountingAvailable"] is True


# ---------------------------------------------------------------------------
# Bot-status projection: derive_live_readiness rebuilds reasons from checks,
# so the fail-closed reasons must survive into liveReadiness/liveBlockReasons.
# ---------------------------------------------------------------------------

from backend.auto_market_selection.live_status_consistency import derive_live_readiness  # noqa: E402

_ACCOUNT = {"authenticated": True, "stale": False, "balanceSource": "KUCOIN_FUTURES_READ_ONLY",
            "equity": 10.0, "positionSource": "KUCOIN_FUTURES_READ_ONLY", "positionSummary": "OPEN"}


def test_status_projection_keeps_protection_unavailable_reason():
    engine, _, _ = _start_synced("BUY", sl_pct=0)
    projected = derive_live_readiness(engine.build_live_readiness(), _ACCOUNT,
                                      reported_reasons=engine.build_live_readiness()["blockReasons"])
    assert LIVE_POSITION_PROTECTION_UNAVAILABLE in projected["blockReasons"]
    assert projected["realOrderAllowed"] is False
    assert projected["livePositionProtection"]["state"] == "UNAVAILABLE"


def test_status_projection_keeps_pnl_accounting_unavailable_reason():
    engine, _, _ = _unavailable_multiplier_closed_engine()
    flat = dict(_ACCOUNT, positionSummary="FLAT")
    projected = derive_live_readiness(engine.build_live_readiness(), flat)
    assert LIVE_PNL_ACCOUNTING_UNAVAILABLE in projected["blockReasons"]
    assert projected["livePnlAccounting"]["state"] == "UNAVAILABLE"


def test_status_projection_protected_or_flat_has_no_new_reason():
    engine, _, _ = _start_synced("BUY")
    projected = derive_live_readiness(engine.build_live_readiness(), _ACCOUNT)
    assert LIVE_POSITION_PROTECTION_UNAVAILABLE not in projected["blockReasons"]
    assert LIVE_PNL_ACCOUNTING_UNAVAILABLE not in projected["blockReasons"]
    exchange = _mock_exchange(None, 1.0)
    flat_engine = _live_engine(exchange)
    flat_engine.start()
    flat_projected = derive_live_readiness(flat_engine.build_live_readiness(), dict(_ACCOUNT, positionSummary="FLAT"))
    assert flat_projected["livePositionProtection"]["state"] == "NO_POSITION"
    assert flat_projected["livePnlAccounting"]["state"] == "AVAILABLE"
    assert LIVE_POSITION_PROTECTION_UNAVAILABLE not in flat_projected["blockReasons"]
