from datetime import datetime, timezone

from backend.auto_market_selection import BotManagerSwitchRuntime, PreparedFeed
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.adapters.execution_signal_adapter import ExecutionSignalAdapter
from backend.runtime.runtime_symbol_context import (
    build_runtime_symbol_context, symbol_context_matches,
)


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


def test_runtime_symbol_context_is_derived_and_rejects_old_identity():
    context = build_runtime_symbol_context("btcusdt", "runtime-new", evaluated_at=NOW)
    assert context.to_dict() == {
        "symbol": "BTCUSDT", "runtimeId": "runtime-new",
        "evaluatedAt": "2026-08-09T03:00:00Z",
    }
    assert symbol_context_matches(context, "BTCUSDT", "runtime-new")
    assert not symbol_context_matches(context, "ETHUSDT", "runtime-new")
    assert not symbol_context_matches(context, "BTCUSDT", "runtime-old")


def test_execution_fails_closed_when_strategy_or_governance_symbol_is_stale():
    runtime = ExecutionRuntime()
    runtime.engine = type("Engine", (), {"symbol": "BTCUSDT"})()
    new_context = build_runtime_symbol_context("BTCUSDT", "new", evaluated_at=NOW).to_dict()
    old_context = build_runtime_symbol_context("ETHUSDT", "old", evaluated_at=NOW).to_dict()
    strategy = {"executionAllowed": True, "direction": "BUY", "edge": 1,
                "confidence": 1, "risk": 0, "runtimeSymbolContext": old_context}
    governance = {"allowed": True, "direction": "BUY",
                  "runtimeSymbolContext": new_context}
    result = runtime.process_execution_runtime(
        strategy, governance, runtime_symbol_context=new_context,
    )
    assert result["valid"] is False
    assert result["runtime"]["reason"] == "RUNTIME_SYMBOL_CONTEXT_MISMATCH"
    assert runtime.handoff_attempted is False


def test_order_intent_keeps_runtime_symbol_context():
    context = build_runtime_symbol_context("BTCUSDT", "new", evaluated_at=NOW).to_dict()
    intent = ExecutionSignalAdapter.adapt({
        "executed": True, "direction": "LONG", "runtimeSymbolContext": context,
    })
    assert intent["runtimeSymbolContext"] == context


def test_bot_manager_sync_boundary_seeds_validated_dom_and_engine_before_resume():
    class Engine:
        symbol = "ETHUSDT"
    class Manager:
        engine = Engine()
        def _synchronize_market_intelligence_for_safe_switch(self, symbol, runtime_id, snapshot):
            self.synced = (symbol, runtime_id, snapshot)
            return True
    manager = Manager()
    adapter = BotManagerSwitchRuntime(
        manager, position_provider=lambda: "FLAT", mm_provider=lambda: None,
        emergency_provider=lambda: True,
    )
    snapshot = {"symbol": "BTCUSDT", "bids": {99: 1}, "asks": {101: 1}}
    handle = PreparedFeed(None, "new", None, "old", "BTCUSDT", "XBTUSDTM", snapshot)
    assert adapter.sync_downstream("BTCUSDT", handle)
    assert manager.engine.symbol == "BTCUSDT"
    assert manager.synced == ("BTCUSDT", "new", snapshot)


def test_bot_manager_invalidates_old_current_state_and_seeds_new_dom():
    from backend.bot_manager.bot_manager import BotManager
    from backend.core.orderbook_manager import OrderBookManager

    manager = BotManager()
    manager._active_symbol = "BTCUSDT"
    manager.active_runtime_id = "new"
    manager.ob_manager = OrderBookManager()
    manager.last_signal = "OLD_BUY"
    manager.latest_runtime_result = {"symbol": "ETHUSDT"}
    manager.state.strategy_state = {"symbol": "ETHUSDT"}
    old_builder = manager.microstructure_builder
    snapshot = {
        "symbol": "BTCUSDT", "exchange_symbol": "XBTUSDTM",
        "market_type": "FUTURES", "market_timestamp": NOW.timestamp(),
        "sequence": 7, "price": 100, "best_bid": 99, "best_ask": 101,
        "spread": 2, "bids": {99.0: 1.0}, "asks": {101.0: 1.0},
        "order_book": {"timestamp": NOW.timestamp(), "sequence": 7,
                       "depth": 1, "bids": [{"price": 99, "size": 1}],
                       "asks": [{"price": 101, "size": 1}],
                       "dataQuality": "VALID", "syncState": "SYNCED"},
    }
    assert manager._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "new", snapshot,
    )
    assert manager.last_signal is None and manager.latest_runtime_result is None
    assert manager.state.strategy_state == {}
    assert manager.microstructure_builder is not old_builder
    assert manager.ob_manager.bids == {99.0: 1.0}
    assert manager.market_snapshot["exchangeSymbol"] == "XBTUSDTM"


def test_sync_logic_does_not_create_orders_or_subscriptions():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    context_source = (root / "backend/runtime/runtime_symbol_context.py").read_text()
    execution_source = (root / "backend/runtime/ExecutionRuntime.py").read_text()
    assert all(term not in context_source for term in
               ("create_order", "submit_order", "create_market_ws", "subscribe"))
    assert "ORDER_INTENT_SYMBOL_MISMATCH" in execution_source
