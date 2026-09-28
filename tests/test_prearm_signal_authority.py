"""Regression coverage for PRE-ARM signal generation authority."""

from unittest.mock import MagicMock, patch

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.runtime.governance_runtime import EMERGENCY_READY, governance_state


@pytest.fixture(autouse=True)
def safe_governance_state():
    previous = dict(governance_state)
    governance_state.update({
        "execution_enabled": False,
        "emergency_stop": False,
        "emergency_state": EMERGENCY_READY,
        "control_authority": "BOT",
        "control_revision": 0,
    })
    yield
    governance_state.clear()
    governance_state.update(previous)


def _prearm_manager():
    manager = BotManager()
    manager.lifecycle_state = "RUNNING"
    manager.loop_state = "STOPPED"
    manager.config.update({
        "mode": "live",
        "dry_run": False,
        "liveOrderEntryAllowed": False,
        "executionEntryAllowed": False,
        "realOrderAllowed": False,
        "autoTradeEnabled": False,
    })
    manager.symbol = "BTCUSDT"
    manager.active_runtime_id = "runtime-1"
    manager._running = True
    manager.runtime_instance_id = "instance-1"
    manager._symbol_switch_entry_paused = False
    manager.attach_orderbook_runtime_debug = MagicMock()
    manager.engine = MagicMock()
    manager.engine.symbol = "BTCUSDT"
    manager.engine.exchange = MagicMock()
    return manager


def _decision(direction, evaluated_at):
    return {
        "valid": True,
        "strategyOutput": {
            "strategy": {
                "direction": direction,
                "executionAllowed": direction in {"BUY", "SELL"},
                "evaluatedAt": evaluated_at,
            }
        },
        "runtimeStageTrace": {
            "strategy-plugin": {"timestamp": evaluated_at},
        },
        "runtime": {
            "executionAllowed": False,
            "reason": "EXECUTION_DISABLED",
        },
    }


@pytest.mark.parametrize("direction", ["HOLD", "BUY", "SELL"])
def test_prearm_loop_off_refreshes_natural_decision_without_order(direction):
    manager = _prearm_manager()
    runtime = MagicMock()
    runtime.process_runtime.return_value = _decision(direction, 101.0)

    with patch(
        "backend.bot_manager.bot_manager.runtime_registry.trading_runtime",
        runtime,
    ):
        result = manager._observe_runtime_decision(
            {"fresh": True},
            active_symbol="BTCUSDT",
            runtime_id="runtime-1",
        )

    runtime.process_runtime.assert_called_once()
    assert result["strategyOutput"]["strategy"]["direction"] == direction
    assert result["runtimeStageTrace"]["strategy-plugin"]["timestamp"] == 101.0
    assert result["runtimeSnapshotAuthority"]["signalGenerationAuthority"] == "MARKET_OBSERVATION"
    manager.engine.exchange.place_order.assert_not_called()


def test_prearm_new_evaluation_replaces_stale_hold_and_advances_timestamp():
    manager = _prearm_manager()
    manager.latest_runtime_result = _decision("HOLD", 1.0)
    runtime = MagicMock()
    runtime.process_runtime.side_effect = [
        _decision("HOLD", 101.0),
        _decision("HOLD", 102.0),
    ]

    with patch(
        "backend.bot_manager.bot_manager.runtime_registry.trading_runtime",
        runtime,
    ):
        first = manager._observe_runtime_decision({}, runtime_id="runtime-1")
        second = manager._observe_runtime_decision({}, runtime_id="runtime-1")

    assert first["runtimeStageTrace"]["strategy-plugin"]["timestamp"] == 101.0
    assert second["runtimeStageTrace"]["strategy-plugin"]["timestamp"] == 102.0
    assert manager.latest_runtime_result is second
    manager.engine.exchange.place_order.assert_not_called()


def test_symbol_switch_pause_still_blocks_strategy_observation():
    manager = _prearm_manager()
    manager._symbol_switch_entry_paused = True
    runtime = MagicMock()

    with patch(
        "backend.bot_manager.bot_manager.runtime_registry.trading_runtime",
        runtime,
    ):
        assert manager._observe_runtime_decision({}, runtime_id="runtime-1") is None

    runtime.process_runtime.assert_not_called()


def test_loop_off_remains_final_bot_order_gate_for_fresh_buy():
    manager = _prearm_manager()
    governance_state["execution_enabled"] = True
    with manager.execution_authority_lock:
        manager._begin_execution_admission("BOT")

    decision = manager._authorize_bot_execution_entry({
        "side": "BUY",
        "runtimeSymbolContext": {
            "symbol": "BTCUSDT",
            "runtimeId": "runtime-1",
        },
    })

    assert decision == {"allowed": False, "reason": "BOT_RUNTIME_LOOP_REQUIRED"}
    manager.engine.exchange.place_order.assert_not_called()


def test_governance_off_remains_final_bot_order_gate_for_fresh_sell():
    manager = _prearm_manager()
    manager.loop_state = "RUNNING"
    with manager.execution_authority_lock:
        manager._begin_execution_admission("BOT")

    decision = manager._authorize_bot_execution_entry({
        "side": "SELL",
        "runtimeSymbolContext": {
            "symbol": "BTCUSDT",
            "runtimeId": "runtime-1",
        },
    })

    assert decision == {"allowed": False, "reason": "EXECUTION_DISABLED"}
    manager.engine.exchange.place_order.assert_not_called()
