import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import Mock, call, patch
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import HTTPException

from backend.api.governance import (
    emergency_orchestrate,
    emergency_retry,
    emergency_stop,
    emergency_unlock,
    router as governance_router,
    set_execution,
)
from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import KucoinTradeClient
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    EMERGENCY_LOCKED,
    EMERGENCY_PROCESSING,
    EMERGENCY_READY,
    EMERGENCY_RESULT_FAILED,
    EMERGENCY_RESULT_NONE,
    EMERGENCY_RESULT_PARTIAL,
    EMERGENCY_RESULT_SUCCESS,
    begin_emergency_operation,
    complete_emergency_operation,
    emergency_pending_order_block_reason,
    emergency_unlock_block_reason,
    governance_state,
)
from Bot.engine.execution_engine import ExecutionEngine


class FakeEngine:
    balance = 4321.25
    pnl = 12.5
    unrealized_pnl = -2.25
    actual_position = {
        "symbol": "BTCUSDT",
        "side": "BUY",
    }
    pending_order = False


class FakeReadOnlyEngine:
    balance = 9876.54
    pnl = 3.0
    unrealized_pnl = 1.5
    actual_position = {
        "symbol": "XRPUSDTM",
        "side": "BUY",
        "qty": 12,
    }
    pending_order = False
    real_available_balance = 9000.12
    config = {
        "mode": "live",
        "dry_run": True,
        "risk_percent": 1,
        "position_size": 100,
        "max_drawdown_pct": 5,
        "sl_percent": 1,
        "tp_percent": 2,
        "timeframe": "1m",
        "leverage": 5,
        "trailing_stop": False,
    }

    def get_risk_state(self):
        return {}

    def build_live_readiness(self):
        return {
            "ready": False,
            "realOrderAllowed": False,
            "checks": {},
            "blockReasons": [
                "LIVE_NOT_ENABLED",
                "TRADE_MODE_NOT_LIVE",
                "DRY_RUN_ACTIVE",
            ],
            "selectedMode": "LIVE",
            "dryRun": True,
            "tradeMode": "paper",
            "allowLive": False,
            "exchangeClientReady": True,
            "exchangeAuthReady": True,
            "balanceCheckOk": True,
            "positionCheckOk": True,
            "executionEnabled": False,
            "emergencyStop": False,
            "realBalance": self.balance,
            "realEquity": self.balance + self.unrealized_pnl,
            "realAvailableBalance": self.real_available_balance,
            "realPosition": self.actual_position,
            "realPositionState": "OPEN",
            "realAccountLastSync": 1234567890.0,
            "exchangeConnection": "CONNECTED",
            "apiKeyStatus": "VERIFIED",
            "permission": "READ_ONLY",
            "accountType": "KUCOIN_FUTURES",
            "exchangeAuthReason": "KUCOIN_CREDENTIALS_VERIFIED",
            "exchangeConnectionReason": "KUCOIN_CLIENT_READY",
            "accountReason": "KUCOIN_READ_ONLY_SYNC_OK",
            "balanceReason": "KUCOIN_BALANCE_SYNC_OK",
            "positionReason": "KUCOIN_POSITION_SYNC_OK",
            "accountSnapshot": {},
        }


class ExchangeLiveStatusTest(unittest.TestCase):

    def test_operation_status_fields_reflect_authoritative_state(self):
        execution_enabled_before = governance_state["execution_enabled"]
        scenarios = [
            {
                "name": "initial_stopped",
                "running": False,
                "lifecycle_state": "STOPPED",
                "execution_enabled": False,
                "loop_enabled": False,
                "auto_trade_enabled": False,
            },
            {
                "name": "loop_on_auto_trade_off",
                "running": True,
                "lifecycle_state": "RUNNING",
                "execution_enabled": False,
                "loop_enabled": True,
                "auto_trade_enabled": False,
            },
            {
                "name": "loop_on_auto_trade_on",
                "running": True,
                "lifecycle_state": "RUNNING",
                "execution_enabled": True,
                "loop_enabled": True,
                "auto_trade_enabled": True,
            },
            {
                "name": "running_flag_without_running_lifecycle",
                "running": True,
                "lifecycle_state": "STARTING",
                "execution_enabled": False,
                "loop_enabled": False,
                "auto_trade_enabled": False,
            },
        ]

        try:
            for scenario in scenarios:
                with self.subTest(scenario=scenario["name"]):
                    governance_state["execution_enabled"] = (
                        scenario["execution_enabled"]
                    )
                    bot = BotManager()
                    bot._running = scenario["running"]
                    bot.lifecycle_state = scenario["lifecycle_state"]

                    status = bot.get_status()
                    response = StatusResponse(**status)

                    self.assertEqual(
                        response.loopEnabled,
                        scenario["loop_enabled"],
                    )
                    self.assertEqual(
                        response.loopState,
                        scenario["lifecycle_state"],
                    )
                    self.assertEqual(
                        response.autoTradeEnabled,
                        scenario["auto_trade_enabled"],
                    )
                    self.assertEqual(
                        response.autoTradeEnabled,
                        response.executionEnabled,
                    )
        finally:
            governance_state["execution_enabled"] = execution_enabled_before

    def test_emergency_lock_status_fields_reflect_governance_state(self):
        state_before = dict(governance_state)
        scenarios = [
            {
                "name": "unlocked",
                "running": False,
                "lifecycle_state": "STOPPED",
                "emergency_stop": False,
                "execution_enabled": False,
                "emergency_locked": False,
                "emergency_state": "UNLOCKED",
                "loop_enabled": False,
                "auto_trade_enabled": False,
            },
            {
                "name": "locked",
                "running": False,
                "lifecycle_state": "STOPPED",
                "emergency_stop": True,
                "execution_enabled": False,
                "emergency_locked": True,
                "emergency_state": "LOCKED",
                "loop_enabled": False,
                "auto_trade_enabled": False,
            },
            {
                "name": "locked_loop_continues_auto_trade_read_only",
                "running": True,
                "lifecycle_state": "RUNNING",
                "emergency_stop": True,
                "execution_enabled": True,
                "emergency_locked": True,
                "emergency_state": "LOCKED",
                "loop_enabled": True,
                "auto_trade_enabled": True,
            },
        ]

        try:
            for scenario in scenarios:
                with self.subTest(scenario=scenario["name"]):
                    governance_state["emergency_stop"] = (
                        scenario["emergency_stop"]
                    )
                    governance_state["execution_enabled"] = (
                        scenario["execution_enabled"]
                    )
                    bot = BotManager()
                    bot._running = scenario["running"]
                    bot.lifecycle_state = scenario["lifecycle_state"]

                    status = bot.get_status()
                    response = StatusResponse(**status)

                    self.assertEqual(
                        response.emergencyLocked,
                        scenario["emergency_locked"],
                    )
                    self.assertEqual(
                        response.emergencyState,
                        scenario["emergency_state"],
                    )
                    self.assertEqual(
                        response.emergencyLocked,
                        response.emergencyStop,
                    )
                    self.assertEqual(
                        response.loopEnabled,
                        scenario["loop_enabled"],
                    )
                    self.assertEqual(
                        response.autoTradeEnabled,
                        scenario["auto_trade_enabled"],
                    )
                    self.assertEqual(
                        governance_state["execution_enabled"],
                        scenario["execution_enabled"],
                    )
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_on_rejected_when_loop_off(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = False
        bot.lifecycle_state = "STOPPED"

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = False

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(set_execution({"enabled": True}))

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "AUTO_TRADE_REQUIRES_LOOP_ON",
            )
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_on_allowed_when_loop_running(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = True
        bot.lifecycle_state = "RUNNING"

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = False

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                result = asyncio.run(set_execution({"enabled": True}))

            self.assertTrue(result["success"])
            self.assertTrue(result["execution_enabled"])
            self.assertTrue(governance_state["execution_enabled"])
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_off_allowed_when_loop_off(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = False
        bot.lifecycle_state = "STOPPED"

        try:
            governance_state["emergency_stop"] = False

            for initial_state in [True, False]:
                with self.subTest(initial_state=initial_state):
                    governance_state["execution_enabled"] = initial_state

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        result = asyncio.run(
                            set_execution({"enabled": False})
                        )

                    self.assertTrue(result["success"])
                    self.assertFalse(result["execution_enabled"])
                    self.assertFalse(governance_state["execution_enabled"])
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_on_rejected_when_emergency_locked(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = True
        bot.lifecycle_state = "RUNNING"

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(set_execution({"enabled": True}))

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
            )
            self.assertFalse(governance_state["execution_enabled"])
            self.assertTrue(governance_state["emergency_stop"])

            status_bot = BotManager()
            status_bot._running = True
            status_bot.lifecycle_state = "RUNNING"
            status = status_bot.get_status()
            response = StatusResponse(**status)

            self.assertTrue(response.emergencyLocked)
            self.assertEqual(response.emergencyState, "LOCKED")
            self.assertFalse(response.autoTradeEnabled)
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_off_allowed_when_emergency_locked(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = False
        bot.lifecycle_state = "STOPPED"

        try:
            governance_state["emergency_stop"] = True

            for initial_state in [True, False]:
                with self.subTest(initial_state=initial_state):
                    governance_state["execution_enabled"] = initial_state

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        result = asyncio.run(
                            set_execution({"enabled": False})
                        )

                    self.assertTrue(result["success"])
                    self.assertFalse(result["execution_enabled"])
                    self.assertFalse(governance_state["execution_enabled"])
                    self.assertTrue(governance_state["emergency_stop"])
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_on_emergency_lock_takes_priority_over_loop_guard(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = False
        bot.lifecycle_state = "STOPPED"

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(set_execution({"enabled": True}))

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
            )
            self.assertFalse(governance_state["execution_enabled"])
            self.assertTrue(governance_state["emergency_stop"])
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_auto_trade_on_rejection_does_not_mutate_governance_state(self):
        state_before = dict(governance_state)
        bot = Mock()
        bot._running = False
        bot.lifecycle_state = "STOPPED"

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = False
            expected_state = dict(governance_state)

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException):
                    asyncio.run(set_execution({"enabled": True}))

            self.assertEqual(governance_state, expected_state)
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_emergency_orchestrate_route_calls_orchestrator_once(self):
        completed_response = {
            "success": True,
            "completed": True,
            "partial": False,
            "state_unknown": False,
            "emergency_locked": True,
            "auto_trade_disabled": True,
            "execution_path": "paper",
            "symbol": "XRPUSDT",
            "cancel": None,
            "flatten": {
                "success": True,
                "skipped": False,
            },
            "position_remaining": False,
            "retryable": False,
            "error_code": None,
        }
        bot = Mock()
        bot.run_emergency_orchestrator.return_value = completed_response
        bot.engine = Mock()
        bot.engine.exchange = Mock()
        bot.engine.flatten_paper_position = Mock()

        with patch(
            "backend.api.governance.get_bot_manager",
            return_value=bot,
        ) as get_bot_manager:
            result = asyncio.run(emergency_orchestrate())

        self.assertIs(result, completed_response)
        self.assertTrue(result["success"])
        self.assertTrue(result["completed"])
        self.assertFalse(result["partial"])
        get_bot_manager.assert_called_once_with()
        bot.run_emergency_orchestrator.assert_called_once_with()
        bot.engine.exchange.cancel_all_orders.assert_not_called()
        bot.engine.exchange.flatten_current_position.assert_not_called()
        bot.engine.flatten_paper_position.assert_not_called()

    def test_emergency_orchestrate_route_preserves_partial_response(self):
        partial_response = {
            "success": False,
            "completed": False,
            "partial": True,
            "state_unknown": True,
            "emergency_locked": True,
            "auto_trade_disabled": True,
            "execution_path": "live",
            "symbol": "XRPUSDTM",
            "cancel": {
                "success": False,
                "error": "OPEN_ORDERS_FAILED",
            },
            "flatten": {
                "success": True,
                "confirmed": True,
            },
            "position_remaining": False,
            "retryable": True,
            "error_code": "CANCEL_FAILED_FLATTEN_COMPLETED",
        }
        bot = Mock()
        bot.run_emergency_orchestrator.return_value = partial_response

        with patch(
            "backend.api.governance.get_bot_manager",
            return_value=bot,
        ):
            result = asyncio.run(emergency_orchestrate())

        self.assertIs(result, partial_response)
        self.assertFalse(result["success"])
        self.assertFalse(result["completed"])
        self.assertTrue(result["partial"])
        self.assertTrue(result["state_unknown"])
        self.assertEqual(
            result["error_code"],
            "CANCEL_FAILED_FLATTEN_COMPLETED",
        )
        self.assertEqual(result["cancel"], partial_response["cancel"])
        self.assertEqual(result["flatten"], partial_response["flatten"])

    def test_emergency_orchestrate_route_preserves_engine_unavailable(self):
        engine_unavailable_response = {
            "success": False,
            "completed": False,
            "partial": False,
            "state_unknown": True,
            "emergency_locked": True,
            "auto_trade_disabled": True,
            "execution_path": None,
            "symbol": None,
            "cancel": None,
            "flatten": None,
            "position_remaining": None,
            "retryable": True,
            "error_code": "ENGINE_UNAVAILABLE",
        }
        bot = Mock()
        bot.run_emergency_orchestrator.return_value = (
            engine_unavailable_response
        )

        with patch(
            "backend.api.governance.get_bot_manager",
            return_value=bot,
        ):
            result = asyncio.run(emergency_orchestrate())

        self.assertIs(result, engine_unavailable_response)
        self.assertFalse(result["success"])
        self.assertTrue(result["state_unknown"])
        self.assertEqual(result["error_code"], "ENGINE_UNAVAILABLE")

    def test_emergency_orchestrate_route_rejects_already_running(self):
        already_running_response = {
            "success": False,
            "completed": False,
            "partial": False,
            "state_unknown": False,
            "emergency_locked": True,
            "auto_trade_disabled": True,
            "execution_path": None,
            "symbol": None,
            "cancel": None,
            "flatten": None,
            "position_remaining": None,
            "retryable": True,
            "error_code": "EMERGENCY_ALREADY_RUNNING",
        }
        bot = Mock()
        bot.run_emergency_orchestrator.return_value = (
            already_running_response
        )

        with patch(
            "backend.api.governance.get_bot_manager",
            return_value=bot,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_orchestrate())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["reason"],
            "PROCESSING",
        )

    def test_emergency_orchestrate_route_is_registered_without_conflict(self):
        routes = {
            (
                route.path,
                tuple(sorted(route.methods or [])),
            )
            for route in governance_router.routes
        }

        self.assertIn(
            (
                "/api/governance/emergency-orchestrate",
                ("POST",),
            ),
            routes,
        )
        self.assertIn(
            (
                "/api/governance/emergency-stop",
                ("POST",),
            ),
            routes,
        )
        self.assertIn(
            (
                "/api/governance/emergency/unlock",
                ("POST",),
            ),
            routes,
        )
        self.assertIn(
            (
                "/api/governance/emergency/retry",
                ("POST",),
            ),
            routes,
        )

    def test_emergency_stop_remains_lock_only_primitive(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False

            result = asyncio.run(emergency_stop())

            self.assertTrue(result["success"])
            self.assertTrue(result["emergency_stop"])
            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
        finally:
            governance_state.clear()
            governance_state.update(state_before)

    def test_stop_forces_execution_disabled_when_enabled(self):
        execution_enabled_before = governance_state["execution_enabled"]

        try:
            governance_state["execution_enabled"] = True
            bot = BotManager()
            bot._running = True
            bot.lifecycle_state = "RUNNING"

            result = bot.stop()

            self.assertEqual(result["status"], "stopped")
            self.assertFalse(governance_state["execution_enabled"])
            status = bot.get_status()
            response = StatusResponse(**status)
            self.assertFalse(response.loopEnabled)
            self.assertEqual(response.loopState, "STOPPED")
            self.assertFalse(response.autoTradeEnabled)
        finally:
            governance_state["execution_enabled"] = execution_enabled_before

    def test_stop_keeps_execution_disabled_when_already_disabled(self):
        execution_enabled_before = governance_state["execution_enabled"]

        try:
            governance_state["execution_enabled"] = False
            bot = BotManager()

            result = bot.stop()

            self.assertEqual(result["status"], "stopped")
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            governance_state["execution_enabled"] = execution_enabled_before

    def test_stop_error_keeps_execution_disabled(self):
        execution_enabled_before = governance_state["execution_enabled"]

        try:
            governance_state["execution_enabled"] = True
            bot = BotManager()
            bot.ws = Mock()
            bot.ws.stop.side_effect = RuntimeError("ws stop failed")

            result = bot.stop()

            self.assertEqual(result["status"], "error")
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            governance_state["execution_enabled"] = execution_enabled_before

    def test_restart_path_still_works_after_stop(self):
        execution_enabled_before = governance_state["execution_enabled"]
        bot = BotManager()
        config = {
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
            "mode": "paper",
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 0.5,
            "tp_percent": 1,
            "timeframe": "5m",
            "trailing_stop": False,
            "leverage": 5,
        }
        ws = Mock()
        ws.connected = False

        try:
            governance_state["execution_enabled"] = True
            stop_result = bot.stop()

            self.assertEqual(stop_result["status"], "stopped")
            self.assertFalse(governance_state["execution_enabled"])

            with patch(
                "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
                return_value=ws,
            ):
                result = bot.start(config)

            self.assertEqual(result["status"], "started")
            self.assertEqual(bot.lifecycle_state, "RUNNING")
        finally:
            with patch(
                "backend.bot_manager.bot_manager.time.sleep",
                return_value=None,
            ):
                bot.stop()
            governance_state["execution_enabled"] = execution_enabled_before

    def test_account_values_remain_available_after_stop(self):
        bot = BotManager()
        bot.engine = FakeEngine()
        bot._running = True

        running = bot.get_status()
        bot.stop()
        stopped = bot.get_status()

        self.assertEqual(stopped["status"], "STOPPED")
        self.assertEqual(stopped["balance"], running["balance"])
        self.assertEqual(stopped["balance"], 4321.25)
        self.assertEqual(stopped["equity"], running["equity"])
        self.assertEqual(stopped["equity"], 4319.0)
        self.assertEqual(stopped["pnl"], running["pnl"])
        self.assertEqual(stopped["pnl"], 10.25)
        self.assertEqual(stopped["position"], running["position"])
        self.assertGreaterEqual(
            stopped["last_update"],
            running["last_update"],
        )
        self.assertFalse(stopped["ws_connected"])

        # FastAPI must retain the fields consumed by CENTER 1.
        response = StatusResponse(**stopped)
        self.assertEqual(response.last_update, stopped["last_update"])

    def test_status_labels_paper_values_and_real_account_safety(self):
        bot = BotManager()
        bot.config = {"mode": "live"}

        status = bot.get_status()
        response = StatusResponse(**status)

        self.assertEqual(response.accountSource, "PAPER_SIMULATION")
        self.assertEqual(response.balanceSource, "PAPER_SIMULATION")
        self.assertEqual(response.positionSource, "PAPER_SIMULATION")
        self.assertEqual(response.selectedMode, "LIVE")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertTrue(response.dryRun)
        self.assertFalse(response.realOrderAllowed)
        self.assertFalse(response.realAccountConnected)
        self.assertEqual(response.exchangeAuth, "NOT_VERIFIED")
        self.assertIsNone(response.realBalance)
        self.assertIsNone(response.realPosition)
        self.assertEqual(
            response.safetyReason,
            "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE",
        )
        self.assertFalse(status["real_order_allowed"])
        self.assertEqual(status["execution_mode"], "SIMULATION")

    def test_live_read_only_account_fields_reach_status_and_runtime_debug(self):
        bot = BotManager()
        bot.engine = FakeReadOnlyEngine()
        bot.config = dict(FakeReadOnlyEngine.config)
        bot.symbol = "XRPUSDT"
        bot.exchange_name = "kucoin"
        bot.orderbook_source = "kucoin_futures"
        bot.orderbook_symbol = "XRPUSDTM"
        bot._running = True
        bot.latest_runtime_result = {"runtimeDebug": {}}

        status = bot.get_status()
        response = StatusResponse(**status)
        runtime_debug = status["latestRuntimeResult"]["runtimeDebug"]

        self.assertEqual(response.selectedMode, "LIVE")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertTrue(response.dryRun)
        self.assertFalse(response.realOrderAllowed)
        self.assertFalse(status["real_order_allowed"])
        self.assertEqual(response.accountSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(response.balanceSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(response.positionSource, "KUCOIN_FUTURES_READ_ONLY")
        self.assertTrue(response.realAccountConnected)
        self.assertEqual(response.exchangeAuth, "VERIFIED")
        self.assertEqual(response.exchangeConnection, "CONNECTED")
        self.assertEqual(response.apiKeyStatus, "VERIFIED")
        self.assertEqual(response.permission, "READ_ONLY")
        self.assertEqual(response.accountType, "KUCOIN_FUTURES")
        self.assertEqual(response.realBalance, 9876.54)
        self.assertEqual(response.realEquity, 9878.04)
        self.assertEqual(response.realAvailableBalance, 9000.12)
        self.assertEqual(response.realPosition, FakeReadOnlyEngine.actual_position)
        self.assertEqual(response.realPositionState, "OPEN")
        self.assertEqual(response.realLastSync, 1234567890.0)
        self.assertEqual(response.balanceReason, "KUCOIN_BALANCE_SYNC_OK")
        self.assertEqual(response.positionReason, "KUCOIN_POSITION_SYNC_OK")
        self.assertEqual(
            response.accountRuntime["realAccount"]["balance"],
            9876.54,
        )
        self.assertEqual(
            response.accountRuntime["paperAccount"]["source"],
            "PAPER_SIMULATION",
        )

        for key in [
            "accountSource",
            "balanceSource",
            "positionSource",
            "realBalance",
            "realEquity",
            "realAvailableBalance",
            "realPosition",
            "exchangeAuth",
            "exchangeConnection",
            "apiKeyStatus",
            "permission",
            "accountType",
            "realOrderAllowed",
            "dryRun",
            "tradeMode",
        ]:
            self.assertEqual(runtime_debug[key], status[key])

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_account_overview_uses_read_only_get(self, request_get):
        request_get.return_value.json.return_value = {
            "code": "200000",
            "data": {
                "currency": "USDT",
                "accountEquity": "123.45",
                "availableBalance": "120.00",
                "marginBalance": "122.00",
                "unrealisedPNL": "1.45",
            },
        }
        client = KucoinTradeClient(
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )

        overview = client.get_account_overview()

        self.assertEqual(overview["source"], "KUCOIN_FUTURES_READ_ONLY")
        self.assertEqual(overview["balance"], 123.45)
        self.assertEqual(overview["equity"], 123.45)
        self.assertEqual(overview["availableBalance"], 120.0)
        self.assertEqual(overview["permission"], "READ_ONLY")
        self.assertEqual(request_get.call_count, 1)
        self.assertIn(
            "/api/v1/account-overview?currency=USDT",
            request_get.call_args.args[0],
        )

    @staticmethod
    def _kucoin_client():
        return KucoinTradeClient(
            api_key="key",
            api_secret="secret",
            passphrase="passphrase",
        )

    @staticmethod
    def _order_page(items, current_page=1, total_page=1):
        return {
            "code": "200000",
            "data": {
                "currentPage": current_page,
                "pageSize": 100,
                "totalPage": total_page,
                "items": items,
            },
        }

    @staticmethod
    def _positions_response(items):
        return {
            "code": "200000",
            "data": items,
        }

    @staticmethod
    def _mock_position_get(request_get, data, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = data
        request_get.return_value = response
        return response

    @staticmethod
    def _mock_order_post(request_post, data, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = data
        request_post.return_value = response
        return response

    @staticmethod
    def _set_governance(
        execution_enabled=True,
        emergency_stop=False,
    ):
        state_before = dict(governance_state)
        governance_state["execution_enabled"] = execution_enabled
        governance_state["emergency_stop"] = emergency_stop
        governance_state["emergency_state"] = (
            EMERGENCY_ACTION_REQUIRED
            if emergency_stop
            else EMERGENCY_READY
        )
        governance_state["last_emergency_result"] = None
        governance_state["current_emergency_operation_id"] = None
        governance_state["emergency_timeline"] = []
        return state_before

    @staticmethod
    def _restore_governance(state_before):
        governance_state.clear()
        governance_state.update(state_before)

    @staticmethod
    def _saved_emergency_result(
        state=EMERGENCY_LOCKED,
        result=EMERGENCY_RESULT_SUCCESS,
        position_remaining=False,
        state_unknown=False,
        success=True,
        completed=True,
        partial=False,
        retryable=False,
        operation_id="emg_20260714T123456Z_unlock",
    ):
        return {
            "operationId": operation_id,
            "state": state,
            "result": result,
            "startedAt": "2026-07-14T12:34:56.000Z",
            "completedAt": "2026-07-14T12:35:01.000Z",
            "path": "paper",
            "success": success,
            "completed": completed,
            "partial": partial,
            "retryable": retryable,
            "positionRemaining": position_remaining,
            "stateUnknown": state_unknown,
            "cancelResult": None,
            "flattenResult": {
                "status": "COMPLETED",
                "success": True,
                "completed": True,
                "reason": None,
                "position_closed": True,
                "position_remaining": position_remaining,
                "state_unknown": state_unknown,
            },
            "message": "Emergency completed.",
        }

    @staticmethod
    def _set_current_emergency_operation(last_result):
        governance_state["current_emergency_operation_id"] = (
            last_result.get("operationId")
            if isinstance(last_result, dict)
            else None
        )

    @staticmethod
    def _pending_order_engine(pending_order=False):
        class Engine:
            actual_position = None

        engine = Engine()

        if pending_order != "missing":
            engine.pending_order = pending_order

        return engine

    @staticmethod
    def _pending_order_raising_engine():
        class Engine:
            actual_position = None

            @property
            def pending_order(self):
                raise RuntimeError("pending order read failed")

        return Engine()

    @classmethod
    def _bot_with_pending_sources(
        cls,
        manager_pending=False,
        engine_pending=False,
    ):
        bot = BotManager()
        bot.pending_order = manager_pending
        bot.engine = cls._pending_order_engine(engine_pending)
        bot._running = False
        bot.lifecycle_state = "STOPPED"
        return bot

    @staticmethod
    def _emergency_timeline_events():
        return [
            event
            for event in governance_state.get("emergency_timeline", [])
            if isinstance(event, dict)
        ]

    @staticmethod
    def _emergency_bot_with_engine(engine):
        if isinstance(engine, Mock):
            engine.stop.return_value = {"status": "stopped"}
        bot = BotManager()
        bot._test_durable_snapshot_dir = tempfile.mkdtemp()
        bot.stopped_paper_durable_snapshot_path = os.path.join(
            bot._test_durable_snapshot_dir,
            "stopped_paper_safety_snapshot.json",
        )
        bot.engine = engine
        bot.symbol = "XRPUSDT"
        bot.orderbook_symbol = "XRPUSDTM"
        bot.config = {
            "symbol": "XRPUSDT",
            "mode": getattr(engine, "mode", "paper"),
        }
        return bot

    def _paper_emergency_bot(self, flatten_result, exchange=None):
        engine = Mock()
        engine.mode = "paper"
        engine.exchange = exchange or Mock()
        engine.symbol = "XRPUSDT"
        engine.actual_position = None
        engine.portfolio.positions = {}
        engine.pending_order = False
        engine.open_orders = []
        engine.flatten_paper_position.return_value = flatten_result
        engine.build_live_readiness.return_value = {
            "realOrderAllowed": False,
        }
        engine.stop.return_value = {"status": "stopped"}
        return self._emergency_bot_with_engine(engine), engine

    @staticmethod
    def _stopped_paper_bot():
        bot = BotManager()
        tempdir = tempfile.mkdtemp()
        bot._test_durable_snapshot_dir = tempdir
        bot.stopped_paper_durable_snapshot_path = os.path.join(
            tempdir,
            "stopped_paper_safety_snapshot.json",
        )
        bot.engine = None
        bot._running = False
        bot.lifecycle_state = "STOPPED"
        bot.symbol = "XRPUSDT"
        bot.orderbook_symbol = "XRPUSDTM"
        bot.config = {
            "symbol": "XRPUSDT",
            "mode": "paper",
            "dry_run": True,
        }
        bot.account_snapshot = {
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "pnl": None,
            "position": None,
            "positions": [],
            "realizedPnl": None,
            "unrealizedPnl": None,
            "last_update": time.time(),
            "available": True,
            "capturedAt": time.time(),
            "timestamp": time.time(),
            "timestampEpoch": time.time(),
            "source": "stopped_paper_engine_snapshot",
            "tradeMode": "paper",
            "mode": "paper",
            "selectedMode": "PAPER",
            "lifecycleState": "STOPPED",
            "positionRemaining": False,
            "pendingOrder": False,
            "pending_order": False,
            "openOrderCount": 0,
            "stateUnknown": False,
            "dataQuality": (
                "AUTHORITATIVE_STOPPED_PAPER_ENGINE_SNAPSHOT"
            ),
            "operationId": None,
            "generation": bot.account_snapshot_generation,
            "runtimeInstanceId": bot.runtime_instance_id,
            "evidenceGeneration": bot.account_snapshot_generation,
            "evidenceRuntimeInstanceId": bot.runtime_instance_id,
            "evidenceSource": "stopped_paper_engine_snapshot",
            "positionStateSource": "execution_engine.actual_position",
            "pendingOrderStateSource": (
                "execution_engine.pending_order_duplicate_lock"
            ),
            "openOrderStateSource": (
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection"
            ),
            "authorityReason": "STOPPED_PAPER_ENGINE_STATE_CAPTURED",
        }
        return bot

    @staticmethod
    def _mark_stopped_paper_snapshot_not_synced(bot):
        bot.account_snapshot.update({
            "available": False,
            "last_update": None,
            "position": None,
            "positions": None,
            "positionRemaining": None,
            "pendingOrder": None,
            "openOrderCount": None,
            "stateUnknown": True,
            "source": None,
            "operationId": None,
            "generation": None,
        })

    @staticmethod
    def _mark_stopped_paper_snapshot_unsynced_with_authority(bot):
        bot.account_snapshot.update({
            "available": False,
            "last_update": time.time(),
            "position": None,
            "positions": [],
            "source": "stopped_paper_engine_snapshot",
            "positionRemaining": False,
            "pendingOrder": False,
            "pending_order": False,
            "openOrderCount": 0,
            "stateUnknown": False,
            "operationId": None,
            "generation": bot.account_snapshot_generation,
            "positionStateSource": "execution_engine.actual_position",
            "pendingOrderStateSource": (
                "execution_engine.pending_order_duplicate_lock"
            ),
            "openOrderStateSource": (
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection"
            ),
            "authorityReason": "STOPPED_PAPER_ENGINE_STATE_CAPTURED",
        })

    @staticmethod
    def _paper_engine_for_stop(
        actual_position=None,
        portfolio_positions=None,
        pending_order=False,
        open_orders_marker="missing",
        use_actual_engine=True,
    ):
        positions = (
            {}
            if portfolio_positions is None
            else deepcopy(portfolio_positions)
        )
        if use_actual_engine:
            portfolio = PortfolioManager(initial_balance=1000)
            portfolio.positions = positions
            engine = ExecutionEngine(
                exchange=None,
                logger=Mock(),
                portfolio=portfolio,
                notifier=None,
                price_manager=None,
            )
            engine.mode = "paper"
            engine.symbol = "XRPUSDT"
            engine.actual_position = deepcopy(actual_position)
            if pending_order == "missing":
                delattr(engine, "pending_order")
            else:
                engine.pending_order = pending_order
            if open_orders_marker != "missing":
                engine.open_orders = open_orders_marker
            return engine

        class Portfolio:
            def __init__(self, positions):
                self.positions = positions
                self.lock = threading.Lock()

        class Engine:
            mode = "paper"
            balance = 1000.0
            pnl = 0.0
            unrealized_pnl = 0.0

            def __init__(
                self,
                position,
                positions,
                pending,
                open_orders,
            ):
                self.actual_position = position
                self.portfolio = Portfolio(positions)
                if pending != "missing":
                    self.pending_order = pending
                if open_orders != "missing":
                    self.open_orders = open_orders

            def stop(self):
                return {"status": "stopped"}

        return Engine(
            actual_position,
            positions,
            pending_order,
            open_orders_marker,
        )

    def _temporary_durable_snapshot_path(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        return os.path.join(
            tempdir.name,
            "stopped_paper_safety_snapshot.json",
        )

    @staticmethod
    def _configure_durable_snapshot_path(bot, path):
        tempdir = getattr(bot, "_test_durable_snapshot_dir", None)
        if hasattr(tempdir, "cleanup"):
            tempdir.cleanup()
            bot._test_durable_snapshot_dir = None
        bot.stopped_paper_durable_snapshot_path = path
        return bot

    def _restart_stopped_paper_bot(self, path):
        bot = BotManager()
        bot.stopped_paper_durable_snapshot_path = path
        bot.engine = None
        bot._running = False
        bot.lifecycle_state = "STOPPED"
        bot.symbol = "XRPUSDT"
        bot.orderbook_symbol = "XRPUSDTM"
        bot.config = {
            "symbol": "XRPUSDT",
            "mode": "paper",
            "dry_run": True,
        }
        return bot

    def _persist_flat_stopped_paper_durable_snapshot(
        self,
        path,
        now=None,
    ):
        bot = self._configure_durable_snapshot_path(
            self._stopped_paper_bot(),
            path,
        )
        bot.engine = self._paper_engine_for_stop(
            actual_position=None,
            portfolio_positions={},
        )
        if now is None:
            bot.stop()
        else:
            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                bot.stop()
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return bot, payload

    def _write_durable_snapshot_payload(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def _retry_stopped_paper_with_durable_path(self, path):
        bot = self._restart_stopped_paper_bot(path)
        self._mark_stopped_paper_snapshot_not_synced(bot)
        with patch(
            "backend.api.governance.get_bot_manager",
            return_value=bot,
        ):
            retry = asyncio.run(emergency_retry())
        return bot, retry

    def _live_emergency_bot(
        self,
        cancel_result=None,
        flatten_result=None,
        real_order_allowed=True,
        exchange=None,
    ):
        exchange = exchange or Mock()
        exchange.cancel_all_orders.return_value = (
            cancel_result
            if cancel_result is not None
            else {
                "success": True,
                "requested": 1,
                "cancelled": 1,
                "failed": 0,
                "skipped": False,
            }
        )
        exchange.flatten_current_position.return_value = (
            flatten_result
            if flatten_result is not None
            else {
                "success": True,
                "skipped": False,
                "accepted": True,
                "confirmed": True,
                "closed": True,
            }
        )
        engine = Mock()
        engine.mode = "live"
        engine.exchange = exchange
        engine.symbol = "XRPUSDT"
        engine.flatten_paper_position = Mock()
        engine.build_live_readiness.return_value = {
            "realOrderAllowed": real_order_allowed,
            "selectedMode": "LIVE",
        }
        return self._emergency_bot_with_engine(engine), engine, exchange

    def test_emergency_state_model_initial_status_ready(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None

            bot = BotManager()
            status = bot.get_status()
            response = StatusResponse(**status)
            emergency = status["emergency"]

            self.assertFalse(emergency["active"])
            self.assertFalse(emergency["locked"])
            self.assertEqual(emergency["state"], EMERGENCY_READY)
            self.assertIsNone(emergency["lastResult"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_state_model_start_sets_processing_and_lock(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None

            operation = begin_emergency_operation()
            last_result = governance_state["last_emergency_result"]

            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_PROCESSING,
            )
            self.assertEqual(
                last_result["operationId"],
                operation["operation_id"],
            )
            self.assertEqual(last_result["state"], EMERGENCY_PROCESSING)
            self.assertEqual(last_result["result"], EMERGENCY_RESULT_NONE)
            self.assertIsNone(last_result["completedAt"])
            self.assertTrue(last_result["retryable"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_state_model_success_status_and_polling_retention(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            def flatten_side_effect(**_kwargs):
                processing = governance_state["last_emergency_result"]

                self.assertTrue(governance_state["emergency_stop"])
                self.assertFalse(governance_state["execution_enabled"])
                self.assertEqual(
                    governance_state["emergency_state"],
                    EMERGENCY_PROCESSING,
                )
                self.assertEqual(
                    processing["result"],
                    EMERGENCY_RESULT_NONE,
                )
                self.assertIsNone(processing["completedAt"])

                return {
                    "success": True,
                    "requested": 1,
                    "flattened": 1,
                    "failed": 0,
                    "skipped": False,
                    "api_key": "SHOULD_NOT_LEAK",
                }

            bot, engine = self._paper_emergency_bot({})
            engine.flatten_paper_position.side_effect = flatten_side_effect

            result = bot.run_emergency_orchestrator()

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            self.assertEqual(result["path"], "paper")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )

            first_status = bot.get_status()["emergency"]
            first_result = first_status["lastResult"]

            self.assertTrue(first_status["active"])
            self.assertTrue(first_status["locked"])
            self.assertEqual(first_status["state"], EMERGENCY_LOCKED)
            self.assertRegex(
                first_result["operationId"],
                r"^emg_\d{8}T\d{6}Z_[0-9a-f]{6}$",
            )
            self.assertTrue(first_result["startedAt"].endswith("Z"))
            self.assertTrue(first_result["completedAt"].endswith("Z"))
            self.assertEqual(first_result["result"], EMERGENCY_RESULT_SUCCESS)
            self.assertEqual(first_result["path"], "paper")
            self.assertTrue(first_result["success"])
            self.assertTrue(first_result["completed"])
            self.assertFalse(first_result["partial"])
            self.assertFalse(first_result["retryable"])
            self.assertFalse(first_result["positionRemaining"])
            self.assertFalse(first_result["stateUnknown"])
            self.assertIsNone(first_result["cancelResult"])
            self.assertEqual(
                first_result["flattenResult"]["status"],
                "COMPLETED",
            )
            self.assertTrue(
                first_result["flattenResult"]["position_closed"]
            )

            second_status = bot.get_status()["emergency"]
            self.assertEqual(
                second_status["lastResult"]["operationId"],
                first_result["operationId"],
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_success_stops_bot_loop_and_keeps_execution_disabled(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            bot, _ = self._paper_emergency_bot({
                "success": True,
                "requested": 0,
                "flattened": 0,
                "failed": 0,
                "skipped": True,
            })
            bot._running = True
            bot.lifecycle_state = "RUNNING"

            result = bot.run_emergency_orchestrator()
            status = bot.get_status()

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            self.assertFalse(bot._running)
            self.assertEqual(bot.lifecycle_state, "STOPPED")
            self.assertFalse(status["loopEnabled"])
            self.assertEqual(status["loopState"], "STOPPED")
            self.assertFalse(status["autoTradeEnabled"])
            self.assertFalse(status["executionEnabled"])
            self.assertTrue(status["emergency"]["locked"])
            self.assertEqual(status["emergency"]["state"], EMERGENCY_LOCKED)
        finally:
            self._restore_governance(state_before)

    def test_emergency_stopped_paper_succeeds_without_engine(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )

        try:
            bot = self._stopped_paper_bot()

            with patch(
                "backend.bot_manager.bot_manager.ExecutionEngine"
            ) as engine_class:
                with patch(
                    "backend.bot_manager.bot_manager.KucoinTradeClient"
                ) as client_class:
                    result = bot.run_emergency_orchestrator()

            status = bot.get_status()
            last_result = status["emergency"]["lastResult"]

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            self.assertFalse(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertFalse(result["position_remaining"])
            self.assertEqual(result["path"], "paper")
            self.assertEqual(result["cancel"]["status"], "NOT_REQUIRED")
            self.assertEqual(result["flatten"]["status"], "NOT_REQUIRED")
            self.assertFalse(result["retryable"])
            self.assertTrue(status["emergency"]["locked"])
            self.assertEqual(status["emergency"]["state"], EMERGENCY_LOCKED)
            self.assertEqual(
                last_result["cancelResult"]["status"],
                "NOT_REQUIRED",
            )
            self.assertEqual(
                last_result["flattenResult"]["status"],
                "NOT_REQUIRED",
            )
            self.assertFalse(status["loopEnabled"])
            self.assertEqual(status["loopState"], "STOPPED")
            self.assertFalse(status["autoTradeEnabled"])
            self.assertFalse(status["executionEnabled"])
            engine_class.assert_not_called()
            client_class.assert_not_called()
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_pending_order_state_is_authoritative_safe(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )

        try:
            bot = self._stopped_paper_bot()

            pending_state = bot.get_authoritative_pending_order_state()
            status = bot.get_status()
            response = StatusResponse(**status)
            emergency_response = bot._stopped_paper_emergency_response(
                "XRPUSDTM"
            )

            self.assertFalse(status["pendingOrder"])
            self.assertFalse(response.pendingOrder)
            self.assertTrue(pending_state["known"])
            self.assertFalse(pending_state["pending"])
            self.assertTrue(pending_state["safe"])
            self.assertEqual(
                pending_state["reason"],
                "STOPPED_PAPER_AUTHORITATIVE_SAFE",
            )
            self.assertEqual(
                pending_state["source"],
                "stopped_paper_authoritative",
            )
            self.assertFalse(pending_state["engine_available"])
            self.assertIsNone(pending_state["engine_pending_order"])
            self.assertFalse(pending_state["mismatch"])

            status_state = status["pendingOrderState"]
            self.assertTrue(status_state["known"])
            self.assertFalse(status_state["pending"])
            self.assertTrue(status_state["safe"])
            self.assertEqual(
                status_state["reason"],
                "STOPPED_PAPER_AUTHORITATIVE_SAFE",
            )
            self.assertEqual(
                status_state["source"],
                "stopped_paper_authoritative",
            )
            self.assertFalse(status_state["engineAvailable"])
            self.assertIsNone(status_state["enginePendingOrder"])
            self.assertFalse(status_state["mismatch"])
            self.assertIsNone(
                emergency_pending_order_block_reason(pending_state)
            )
            self.assertTrue(emergency_response["success"])
            self.assertFalse(emergency_response["state_unknown"])
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_snapshot_freshness_fail_closed(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )
        now = 1_800_000_000.0
        threshold = 90.0

        def set_last_update(bot, value):
            if value == "missing":
                bot.account_snapshot.pop("last_update", None)
            else:
                bot.account_snapshot["last_update"] = value

        def assert_status_consistency(status):
            camel = status["pendingOrderState"]
            snake = status["pending_order_state"]
            self.assertEqual(camel["known"], snake["known"])
            self.assertEqual(camel["pending"], snake["pending"])
            self.assertEqual(camel["safe"], snake["safe"])
            self.assertEqual(camel["reason"], snake["reason"])
            self.assertEqual(camel["source"], snake["source"])
            self.assertEqual(
                camel["managerPendingOrder"],
                snake["manager_pending_order"],
            )
            self.assertEqual(
                camel["engineAvailable"],
                snake["engine_available"],
            )
            self.assertEqual(
                camel["enginePendingOrder"],
                snake["engine_pending_order"],
            )
            self.assertEqual(camel["mismatch"], snake["mismatch"])

        def assert_fresh(bot):
            pending_state = bot.get_authoritative_pending_order_state()
            status = bot.get_status()
            emergency_response = bot._stopped_paper_emergency_response(
                "XRPUSDTM"
            )

            self.assertFalse(status["pendingOrder"])
            self.assertTrue(pending_state["known"])
            self.assertFalse(pending_state["pending"])
            self.assertTrue(pending_state["safe"])
            self.assertEqual(
                pending_state["reason"],
                "STOPPED_PAPER_AUTHORITATIVE_SAFE",
            )
            self.assertTrue(status["pendingOrderState"]["known"])
            self.assertFalse(status["pendingOrderState"]["pending"])
            self.assertTrue(status["pendingOrderState"]["safe"])
            self.assertEqual(
                status["pendingOrderState"]["reason"],
                "STOPPED_PAPER_AUTHORITATIVE_SAFE",
            )
            assert_status_consistency(status)
            self.assertTrue(emergency_response["success"])
            self.assertFalse(emergency_response["state_unknown"])

        def assert_fail_closed(bot, reason):
            pending_state = bot.get_authoritative_pending_order_state()
            status = bot.get_status()
            emergency_response = bot._stopped_paper_emergency_response(
                "XRPUSDTM"
            )

            self.assertTrue(status["pendingOrder"])
            self.assertFalse(pending_state["known"])
            self.assertIsNone(pending_state["pending"])
            self.assertFalse(pending_state["safe"])
            self.assertEqual(pending_state["reason"], reason)
            self.assertEqual(
                pending_state["source"],
                "stopped_paper_authoritative",
            )
            self.assertFalse(pending_state["engine_available"])
            self.assertFalse(status["pendingOrderState"]["known"])
            self.assertIsNone(status["pendingOrderState"]["pending"])
            self.assertFalse(status["pendingOrderState"]["safe"])
            self.assertEqual(
                status["pendingOrderState"]["reason"],
                reason,
            )
            assert_status_consistency(status)
            self.assertFalse(emergency_response["success"])
            self.assertTrue(emergency_response["state_unknown"])
            self.assertEqual(emergency_response["error_code"], reason)

        fresh_cases = [
            ("fresh-now", now),
            ("boundary-age-equals-threshold", now - threshold),
        ]

        fail_cases = [
            (
                "stale",
                now - threshold - 0.001,
                "SNAPSHOT_STALE",
            ),
            (
                "future",
                now + 0.001,
                "SNAPSHOT_TIMESTAMP_FUTURE",
            ),
            ("zero", 0, "SNAPSHOT_TIMESTAMP_INVALID"),
            ("negative", -1, "SNAPSHOT_TIMESTAMP_INVALID"),
            ("string-number", "123", "SNAPSHOT_TIMESTAMP_INVALID"),
            ("string-invalid", "invalid", "SNAPSHOT_TIMESTAMP_INVALID"),
            ("bool-true", True, "SNAPSHOT_TIMESTAMP_INVALID"),
            ("bool-false", False, "SNAPSHOT_TIMESTAMP_INVALID"),
            ("dict", {}, "SNAPSHOT_TIMESTAMP_INVALID"),
            ("list", [], "SNAPSHOT_TIMESTAMP_INVALID"),
            ("none", None, "SNAPSHOT_TIMESTAMP_MISSING"),
            ("missing", "missing", "SNAPSHOT_TIMESTAMP_MISSING"),
            ("nan", float("nan"), "SNAPSHOT_TIMESTAMP_INVALID"),
            ("inf", float("inf"), "SNAPSHOT_TIMESTAMP_INVALID"),
            ("neg-inf", float("-inf"), "SNAPSHOT_TIMESTAMP_INVALID"),
        ]

        invalid_thresholds = [
            ("threshold-none", None),
            ("threshold-zero", 0),
            ("threshold-negative", -1),
            ("threshold-string", "90"),
            ("threshold-nan", float("nan")),
        ]

        with patch(
            "backend.bot_manager.bot_manager.time.time",
            return_value=now,
        ):
            try:
                for name, last_update in fresh_cases:
                    with self.subTest(name=name):
                        bot = self._stopped_paper_bot()
                        bot.account_stale_after = threshold
                        set_last_update(bot, last_update)
                        assert_fresh(bot)

                for name, last_update, reason in fail_cases:
                    with self.subTest(name=name):
                        bot = self._stopped_paper_bot()
                        bot.account_stale_after = threshold
                        set_last_update(bot, last_update)
                        assert_fail_closed(bot, reason)

                for name, stale_after in invalid_thresholds:
                    with self.subTest(name=name):
                        bot = self._stopped_paper_bot()
                        bot.account_stale_after = stale_after
                        set_last_update(bot, now)
                        assert_fail_closed(
                            bot,
                            "SNAPSHOT_STALE_THRESHOLD_INVALID",
                        )
            finally:
                self._restore_governance(state_before)

    def test_emergency_retry_refreshes_stale_stopped_paper_snapshot_and_unlocks(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )
        now = 1_800_000_000.0
        stale_update = now - 600.0

        try:
            bot = self._stopped_paper_bot()
            bot.account_stale_after = 90.0
            bot.account_snapshot["last_update"] = stale_update
            original_snapshot = bot.account_snapshot

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                initial = bot.run_emergency_orchestrator()

                self.assertFalse(initial["success"])
                self.assertTrue(initial["state_unknown"])
                self.assertEqual(initial["error_code"], "SNAPSHOT_STALE")
                self.assertEqual(
                    governance_state["emergency_state"],
                    EMERGENCY_ACTION_REQUIRED,
                )
                self.assertIs(bot.account_snapshot, original_snapshot)
                self.assertEqual(
                    bot.account_snapshot["last_update"],
                    stale_update,
                )

                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    retry = asyncio.run(emergency_retry())

                self.assertTrue(retry["success"])
                self.assertTrue(retry["completed"])
                self.assertFalse(retry["partial"])
                self.assertFalse(retry["state_unknown"])
                self.assertFalse(retry["position_remaining"])
                self.assertFalse(retry["retryable"])
                self.assertEqual(retry["path"], "paper")
                self.assertEqual(
                    governance_state["emergency_state"],
                    EMERGENCY_LOCKED,
                )
                self.assertIsNot(bot.account_snapshot, original_snapshot)
                self.assertEqual(bot.account_snapshot["last_update"], now)
                self.assertEqual(bot.account_snapshot["capturedAt"], now)
                self.assertEqual(bot.account_snapshot["timestamp"], now)
                self.assertEqual(
                    bot.account_snapshot["source"],
                    "stopped_paper_preserved_runtime_state",
                )
                self.assertEqual(
                    bot.account_snapshot["dataQuality"],
                    "AUTHORITATIVE_STOPPED_PAPER_RECHECK",
                )
                self.assertFalse(bot.account_snapshot["positionRemaining"])
                self.assertFalse(bot.account_snapshot["pendingOrder"])
                self.assertEqual(bot.account_snapshot["openOrderCount"], 0)
                self.assertFalse(bot.account_snapshot["stateUnknown"])

                status = bot.get_status()
                response = StatusResponse(**status)
                last_result = status["emergency"]["lastResult"]
                pending_state = bot.get_authoritative_pending_order_state()

                self.assertEqual(status["emergency"]["state"], EMERGENCY_LOCKED)
                self.assertTrue(status["emergency"]["locked"])
                self.assertEqual(
                    last_result["result"],
                    EMERGENCY_RESULT_SUCCESS,
                )
                self.assertFalse(last_result["stateUnknown"])
                self.assertFalse(last_result["positionRemaining"])
                self.assertFalse(response.pendingOrder)
                self.assertFalse(status["pendingOrder"])
                self.assertIsNone(
                    emergency_unlock_block_reason(pending_state)
                )

                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    unlocked = asyncio.run(emergency_unlock())

                self.assertTrue(unlocked["success"])
                self.assertTrue(unlocked["unlocked"])
                self.assertEqual(
                    governance_state["emergency_state"],
                    EMERGENCY_READY,
                )
                self.assertFalse(governance_state["emergency_stop"])
                self.assertFalse(status["loopEnabled"])
                self.assertFalse(status["autoTradeEnabled"])
                self.assertFalse(status["executionEnabled"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_rejects_stale_stopped_paper_unsafe_states(
        self,
    ):
        now = 1_800_000_000.0
        stale_update = now - 600.0
        cases = [
            (
                "position-remaining",
                lambda bot: bot.account_snapshot.update({
                    "positionRemaining": True,
                    "position": {
                        "side": "BUY",
                        "qty": 1,
                    },
                    "positions": [
                        {
                            "side": "BUY",
                            "qty": 1,
                        },
                    ],
                }),
                "POSITION_REMAINING",
                False,
                True,
            ),
            (
                "snapshot-position-remaining",
                lambda bot: bot.account_snapshot.update({
                    "positionRemaining": True,
                    "position": {
                        "side": "BUY",
                        "qty": 1,
                    },
                    "positions": [
                        {
                            "side": "BUY",
                            "qty": 1,
                        },
                    ],
                }),
                "POSITION_REMAINING",
                False,
                True,
            ),
            (
                "open-order-remaining",
                lambda bot: bot.account_snapshot.update({
                    "pendingOrder": False,
                    "openOrderCount": 1,
                    "openOrderStateSource": "execution_engine.open_orders",
                    "source": "stopped_paper_engine_snapshot",
                }),
                "OPEN_ORDER_REMAINING",
                False,
                False,
            ),
            (
                "snapshot-unavailable",
                lambda bot: setattr(bot, "account_snapshot", None),
                "SNAPSHOT_UNAVAILABLE",
                True,
                None,
            ),
        ]

        for (
            name,
            mutate,
            reason,
            state_unknown,
            position_remaining,
        ) in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=False,
                )

                try:
                    bot = self._stopped_paper_bot()
                    bot.account_stale_after = 90.0
                    bot.account_snapshot["last_update"] = stale_update
                    original_snapshot = bot.account_snapshot

                    with patch(
                        "backend.bot_manager.bot_manager.time.time",
                        return_value=now,
                    ):
                        initial = bot.run_emergency_orchestrator()
                        self.assertEqual(
                            initial["error_code"],
                            "SNAPSHOT_STALE",
                        )
                        mutate(bot)

                        with patch(
                            "backend.api.governance.get_bot_manager",
                            return_value=bot,
                        ):
                            retry = asyncio.run(emergency_retry())

                    self.assertFalse(retry["success"])
                    self.assertTrue(retry["partial"])
                    self.assertEqual(retry["error_code"], reason)
                    self.assertEqual(
                        retry["state_unknown"],
                        state_unknown,
                    )
                    self.assertEqual(
                        retry["position_remaining"],
                        position_remaining,
                    )
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                    if isinstance(bot.account_snapshot, dict):
                        self.assertEqual(
                            bot.account_snapshot["last_update"],
                            stale_update,
                        )
                        self.assertIs(bot.account_snapshot, original_snapshot)

                    pending_state = (
                        bot.get_authoritative_pending_order_state()
                    )
                    self.assertIsNotNone(
                        emergency_unlock_block_reason(pending_state)
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_does_not_use_stopped_paper_fallback_for_live_mode(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        governance_state["mode"] = "LIVE"
        now = 1_800_000_000.0
        stale_update = now - 600.0

        try:
            bot = self._stopped_paper_bot()
            bot.config["mode"] = "live"
            bot.account_stale_after = 90.0
            bot.account_snapshot["last_update"] = stale_update

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                result = bot.retry_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(result["error_code"], "ENGINE_UNAVAILABLE")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(
                bot.account_snapshot["last_update"],
                stale_update,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_rejects_processing_state_before_recheck(
        self,
    ):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_PROCESSING
            governance_state["last_emergency_result"] = (
                self._saved_emergency_result(
                    state=EMERGENCY_PROCESSING,
                    result=EMERGENCY_RESULT_NONE,
                    success=False,
                    completed=False,
                    partial=False,
                    retryable=True,
                )
            )
            self._set_current_emergency_operation(
                governance_state["last_emergency_result"]
            )
            bot = self._stopped_paper_bot()

            result = bot.retry_emergency_orchestrator()

            self.assertTrue(result["retry_rejected"])
            self.assertEqual(result["reason"], "PROCESSING")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_PROCESSING,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_resolves_governance_paper_after_mode_unknown_result(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        now = 1_800_000_000.0
        stale_update = now - 600.0

        try:
            governance_state["mode"] = "PAPER"
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = {
                "operationId": "emg_prod_mode_unknown",
                "state": EMERGENCY_ACTION_REQUIRED,
                "result": EMERGENCY_RESULT_PARTIAL,
                "startedAt": "2026-07-16T17:00:00.000Z",
                "completedAt": "2026-07-16T17:00:01.000Z",
                "path": None,
                "success": False,
                "completed": False,
                "partial": True,
                "retryable": True,
                "positionRemaining": None,
                "stateUnknown": True,
                "cancelResult": None,
                "flattenResult": None,
                "message": (
                    "Emergency requires operator action: MODE_UNKNOWN"
                ),
            }
            self._set_current_emergency_operation(
                governance_state["last_emergency_result"]
            )

            bot = self._stopped_paper_bot()
            bot.config.pop("mode", None)
            bot.account_stale_after = 90.0
            bot.account_snapshot["last_update"] = stale_update
            original_snapshot = bot.account_snapshot

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    retry = asyncio.run(emergency_retry())

            self.assertTrue(retry["success"])
            self.assertTrue(retry["completed"])
            self.assertFalse(retry["partial"])
            self.assertFalse(retry["state_unknown"])
            self.assertFalse(retry["position_remaining"])
            self.assertEqual(retry["path"], "paper")
            self.assertNotEqual(retry.get("error_code"), "MODE_UNKNOWN")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertIsNot(bot.account_snapshot, original_snapshot)
            self.assertEqual(bot.account_snapshot["last_update"], now)
            self.assertEqual(
                bot.account_snapshot["source"],
                "stopped_paper_preserved_runtime_state",
            )

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                pending_state = bot.get_authoritative_pending_order_state()
                self.assertIsNone(emergency_unlock_block_reason(pending_state))

                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    unlocked = asyncio.run(emergency_unlock())

            self.assertTrue(unlocked["success"])
            self.assertTrue(unlocked["unlocked"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_rebuilds_unsynced_stopped_paper_snapshot(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        now = 1_800_000_000.0

        try:
            governance_state["mode"] = "PAPER"
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
                state_unknown=True,
                position_remaining=None,
                operation_id="emg_prod_snapshot_not_synced",
            )
            previous["path"] = "paper"
            previous["message"] = (
                "Emergency requires operator action: SNAPSHOT_NOT_SYNCED"
            )
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)

            bot = self._stopped_paper_bot()
            original_snapshot = bot.account_snapshot
            original_generation = bot.account_snapshot_generation
            self._mark_stopped_paper_snapshot_unsynced_with_authority(bot)

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    retry = asyncio.run(emergency_retry())
                    status = bot.get_status()
                    sync_state = (
                        bot._stopped_paper_authoritative_safety_state()
                    )
                    pending_state = (
                        bot.get_authoritative_pending_order_state()
                    )
                    unlock_block_reason = (
                        emergency_unlock_block_reason(pending_state)
                    )
                    retry_operation_id = (
                        governance_state["last_emergency_result"][
                            "operationId"
                        ]
                    )
                    unlocked = asyncio.run(emergency_unlock())

            fresh_snapshot = bot.account_snapshot

            self.assertTrue(retry["success"])
            self.assertTrue(retry["completed"])
            self.assertFalse(retry["partial"])
            self.assertFalse(retry["state_unknown"])
            self.assertFalse(retry["position_remaining"])
            self.assertEqual(retry["path"], "paper")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
            self.assertIsNot(fresh_snapshot, original_snapshot)
            self.assertTrue(fresh_snapshot["available"])
            self.assertEqual(fresh_snapshot["last_update"], now)
            self.assertEqual(fresh_snapshot["capturedAt"], now)
            self.assertEqual(fresh_snapshot["timestamp"], now)
            self.assertEqual(fresh_snapshot["timestampEpoch"], now)
            self.assertEqual(
                fresh_snapshot["source"],
                "stopped_paper_preserved_runtime_state",
            )
            self.assertEqual(
                fresh_snapshot["sourceSnapshotSource"],
                "stopped_paper_engine_snapshot",
            )
            self.assertEqual(
                fresh_snapshot["dataQuality"],
                "AUTHORITATIVE_STOPPED_PAPER_RECHECK",
            )
            self.assertEqual(
                fresh_snapshot["operationId"],
                retry_operation_id,
            )
            self.assertNotEqual(
                fresh_snapshot["operationId"],
                previous["operationId"],
            )
            self.assertEqual(
                fresh_snapshot["generation"],
                original_generation + 1,
            )
            self.assertEqual(
                bot.account_snapshot_generation,
                original_generation + 1,
            )
            self.assertEqual(fresh_snapshot["tradeMode"], "paper")
            self.assertEqual(fresh_snapshot["selectedMode"], "PAPER")
            self.assertEqual(fresh_snapshot["lifecycleState"], "STOPPED")
            self.assertFalse(fresh_snapshot["positionRemaining"])
            self.assertFalse(fresh_snapshot["pendingOrder"])
            self.assertEqual(fresh_snapshot["openOrderCount"], 0)
            self.assertFalse(fresh_snapshot["stateUnknown"])
            self.assertEqual(
                fresh_snapshot["positionStateSource"],
                "execution_engine.actual_position",
            )
            self.assertEqual(
                fresh_snapshot["pendingOrderStateSource"],
                "execution_engine.pending_order_duplicate_lock",
            )
            self.assertEqual(
                fresh_snapshot["openOrderStateSource"],
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection",
            )

            self.assertTrue(sync_state["safe"])
            self.assertIs(sync_state["snapshot"], fresh_snapshot)
            self.assertEqual(sync_state["open_order_count"], 0)
            self.assertEqual(sync_state["open_order_state"], "flat")
            self.assertTrue(sync_state["snapshot_operation_state"]["valid"])
            self.assertEqual(
                sync_state["snapshot_operation_state"]["operationId"],
                retry_operation_id,
            )
            self.assertFalse(status["pendingOrder"])
            self.assertFalse(StatusResponse(**status).pendingOrder)
            self.assertTrue(pending_state["safe"])
            self.assertIsNone(unlock_block_reason)
            self.assertTrue(unlocked["success"])
            self.assertTrue(unlocked["unlocked"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_stop_preserves_actual_position_authority(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )

        try:
            governance_state["mode"] = "PAPER"
            bot = self._stopped_paper_bot()
            bot.engine = self._paper_engine_for_stop(
                actual_position={
                    "symbol": "XRPUSDT",
                    "side": "BUY",
                    "qty": 1,
                },
                portfolio_positions={
                    "XRPUSDT": {
                        "symbol": "XRPUSDT",
                        "side": "BUY",
                        "size": 1,
                        "entry": 1.0,
                    },
                },
            )

            bot.stop()

            self.assertIsNone(bot.engine)
            self.assertEqual(bot.position, "NONE")
            self.assertTrue(bot.account_snapshot["positionRemaining"])
            self.assertEqual(
                bot.account_snapshot["positionStateSource"],
                "execution_engine.actual_position+portfolio.positions",
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                retry = asyncio.run(emergency_retry())

            pending_state = bot.get_authoritative_pending_order_state()

            self.assertFalse(retry["success"])
            self.assertEqual(retry["error_code"], "POSITION_REMAINING")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(
                emergency_unlock_block_reason(pending_state),
                "ACTION_REQUIRED",
            )
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_stop_preserves_flat_engine_and_portfolio_state(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        now = 1_800_000_000.0

        try:
            governance_state["mode"] = "PAPER"
            bot = self._stopped_paper_bot()
            bot.engine = self._paper_engine_for_stop(
                actual_position=None,
                portfolio_positions={},
            )

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                bot.stop()

            self.assertIsNone(bot.engine)
            self.assertFalse(bot.account_snapshot["positionRemaining"])
            self.assertFalse(bot.account_snapshot["pendingOrder"])
            self.assertEqual(bot.account_snapshot["openOrderCount"], 0)
            self.assertEqual(
                bot.account_snapshot["openOrderStateSource"],
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection",
            )
            self.assertFalse(bot.account_snapshot["stateUnknown"])

            bot.account_snapshot["available"] = False

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now + 10,
            ):
                with patch(
                    "backend.api.governance.get_bot_manager",
                    return_value=bot,
                ):
                    retry = asyncio.run(emergency_retry())

            self.assertTrue(retry["success"])
            self.assertEqual(
                bot.account_snapshot["source"],
                "stopped_paper_preserved_runtime_state",
            )
            self.assertEqual(
                bot.account_snapshot["sourceSnapshotSource"],
                "stopped_paper_engine_portfolio_snapshot",
            )
            self.assertEqual(
                bot.account_snapshot["operationId"],
                governance_state["last_emergency_result"]["operationId"],
            )
            self.assertEqual(
                bot.account_snapshot["generation"],
                bot.account_snapshot_generation,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_engine_none_without_authoritative_snapshot_fails(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )

        try:
            governance_state["mode"] = "PAPER"
            bot = self._stopped_paper_bot()
            self._mark_stopped_paper_snapshot_not_synced(bot)

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                retry = asyncio.run(emergency_retry())

            self.assertFalse(retry["success"])
            self.assertTrue(retry["state_unknown"])
            self.assertEqual(retry["error_code"], "SNAPSHOT_SOURCE_UNKNOWN")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
        finally:
            self._restore_governance(state_before)

    def test_manager_pending_false_does_not_prove_open_orders_flat(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )

        try:
            governance_state["mode"] = "PAPER"
            bot = self._stopped_paper_bot()
            bot.pending_order = False
            self._mark_stopped_paper_snapshot_not_synced(bot)

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                retry = asyncio.run(emergency_retry())

            self.assertFalse(retry["success"])
            self.assertEqual(retry["error_code"], "SNAPSHOT_SOURCE_UNKNOWN")
            self.assertIsNone(bot.account_snapshot["openOrderCount"])
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_open_order_unknown_or_remaining_blocks_success(
        self,
    ):
        cases = [
            (
                "unknown-source",
                {"use_actual_engine": False},
                "OPEN_ORDER_UNKNOWN",
            ),
            (
                "remaining-open-orders",
                {"open_orders_marker": [{"id": "paper-open"}]},
                "OPEN_ORDER_REMAINING",
            ),
        ]

        for name, engine_kwargs, error_code in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=True,
                )

                try:
                    governance_state["mode"] = "PAPER"
                    bot = self._stopped_paper_bot()
                    kwargs = {
                        "actual_position": None,
                        "portfolio_positions": {},
                    }
                    kwargs.update(engine_kwargs)
                    bot.engine = self._paper_engine_for_stop(**kwargs)

                    stop_result = bot.stop()

                    if name == "unknown-source":
                        self.assertEqual(stop_result["status"], "error")
                        self.assertIsNotNone(bot.engine)
                        self.assertTrue(bot.account_snapshot["stateUnknown"])
                        self.assertEqual(
                            bot.account_snapshot["authorityReason"],
                            "OPEN_ORDER_UNKNOWN",
                        )
                        continue

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        retry = asyncio.run(emergency_retry())

                    self.assertFalse(retry["success"])
                    self.assertTrue(retry["state_unknown"] or retry["partial"])
                    self.assertEqual(retry["error_code"], error_code)
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_unsynced_stopped_paper_requires_current_authority(
        self,
    ):
        cases = [
            (
                "position-unknown",
                lambda bot: bot.account_snapshot.update({
                    "positionRemaining": None,
                }),
                "POSITION_STATE_UNKNOWN",
                True,
                None,
            ),
            (
                "pending-unknown",
                lambda bot: bot.account_snapshot.update({
                    "pendingOrder": None,
                }),
                "PENDING_ORDER_UNKNOWN",
                True,
                None,
            ),
            (
                "position-remaining",
                lambda bot: bot.account_snapshot.update({
                    "positionRemaining": True,
                    "position": {
                        "symbol": "XRPUSDT",
                        "side": "BUY",
                    },
                    "positions": [
                        {
                            "symbol": "XRPUSDT",
                            "side": "BUY",
                        },
                    ],
                }),
                "POSITION_REMAINING",
                False,
                True,
            ),
            (
                "pending-remaining",
                lambda bot: bot.account_snapshot.update({
                    "pendingOrder": True,
                }),
                "PENDING_ORDER_REMAINING",
                False,
                False,
            ),
            (
                "open-order-remaining",
                lambda bot: bot.account_snapshot.update({
                    "openOrderCount": 2,
                    "openOrderStateSource": "execution_engine.open_orders",
                }),
                "OPEN_ORDER_REMAINING",
                False,
                False,
            ),
            (
                "open-order-malformed",
                lambda bot: bot.account_snapshot.update({
                    "openOrderCount": None,
                }),
                "OPEN_ORDER_UNKNOWN",
                True,
                None,
            ),
        ]

        for (
            name,
            mutate,
            error_code,
            state_unknown,
            position_remaining,
        ) in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=True,
                )

                try:
                    governance_state["mode"] = "PAPER"
                    previous = self._saved_emergency_result(
                        state=EMERGENCY_ACTION_REQUIRED,
                        result=EMERGENCY_RESULT_PARTIAL,
                        success=False,
                        completed=False,
                        partial=True,
                        retryable=True,
                        state_unknown=True,
                        position_remaining=None,
                        operation_id=f"emg_{name}_snapshot_not_synced",
                    )
                    previous["path"] = "paper"
                    governance_state["last_emergency_result"] = previous
                    self._set_current_emergency_operation(previous)

                    bot = self._stopped_paper_bot()
                    original_snapshot = bot.account_snapshot
                    self._mark_stopped_paper_snapshot_unsynced_with_authority(
                        bot
                    )
                    mutate(bot)

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        retry = asyncio.run(emergency_retry())

                    self.assertFalse(retry["success"])
                    self.assertTrue(retry["partial"])
                    self.assertEqual(retry["error_code"], error_code)
                    self.assertEqual(
                        retry["state_unknown"],
                        state_unknown,
                    )
                    self.assertEqual(
                        retry["position_remaining"],
                        position_remaining,
                    )
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                    self.assertIs(bot.account_snapshot, original_snapshot)
                    self.assertFalse(bot.account_snapshot["available"])
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_unsynced_stopped_paper_snapshot_save_failure(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )

        try:
            governance_state["mode"] = "PAPER"
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
                state_unknown=True,
                position_remaining=None,
                operation_id="emg_snapshot_save_failed",
            )
            previous["path"] = "paper"
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)

            bot = self._stopped_paper_bot()
            original_snapshot = bot.account_snapshot
            original_generation = bot.account_snapshot_generation
            self._mark_stopped_paper_snapshot_unsynced_with_authority(bot)
            bot._save_stopped_paper_safety_snapshot = Mock(
                return_value=False
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                retry = asyncio.run(emergency_retry())

            self.assertFalse(retry["success"])
            self.assertTrue(retry["state_unknown"])
            self.assertEqual(retry["error_code"], "SNAPSHOT_SAVE_FAILED")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertIs(bot.account_snapshot, original_snapshot)
            self.assertEqual(
                bot.account_snapshot_generation,
                original_generation,
            )
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_snapshot_operation_mismatch_blocks_unlock_authority(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        now = 1_800_000_000.0

        try:
            current = self._saved_emergency_result(
                state=EMERGENCY_LOCKED,
                result=EMERGENCY_RESULT_SUCCESS,
                success=True,
                completed=True,
                partial=False,
                retryable=False,
                state_unknown=False,
                position_remaining=False,
                operation_id="emg_current_locked",
            )
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = current
            self._set_current_emergency_operation(current)

            bot = self._stopped_paper_bot()
            bot.account_snapshot.update({
                "available": True,
                "last_update": now,
                "capturedAt": now,
                "timestamp": now,
                "timestampEpoch": now,
                "source": "stopped_paper_preserved_runtime_state",
                "sourceSnapshotSource": "stopped_paper_engine_snapshot",
                "tradeMode": "paper",
                "mode": "paper",
                "selectedMode": "PAPER",
                "operationId": "emg_old_recheck",
                "positionRemaining": False,
                "pendingOrder": False,
                "openOrderCount": 0,
                "stateUnknown": False,
                "generation": bot.account_snapshot_generation,
                "positionStateSource": "execution_engine.actual_position",
                "pendingOrderStateSource": (
                    "execution_engine.pending_order_duplicate_lock"
                ),
                "openOrderStateSource": (
                    "execution_engine."
                    "paper_immediate_fill_no_open_order_collection"
                ),
            })

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                stopped_state = (
                    bot._stopped_paper_authoritative_safety_state()
                )
                pending_state = (
                    bot.get_authoritative_pending_order_state()
                )

            self.assertFalse(stopped_state["safe"])
            self.assertEqual(
                stopped_state["reason"],
                "SNAPSHOT_OPERATION_ID_MISMATCH",
            )
            self.assertFalse(
                stopped_state["snapshot_operation_state"]["valid"]
            )
            self.assertEqual(
                pending_state["reason"],
                "SNAPSHOT_OPERATION_ID_MISMATCH",
            )
            self.assertEqual(
                emergency_unlock_block_reason(pending_state),
                "SNAPSHOT_OPERATION_ID_MISMATCH",
            )
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_stop_persists_durable_authoritative_snapshot(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        path = self._temporary_durable_snapshot_path()
        now = 1_800_000_000.0

        try:
            governance_state["mode"] = "PAPER"
            bot = self._configure_durable_snapshot_path(
                self._stopped_paper_bot(),
                path,
            )
            bot.engine = self._paper_engine_for_stop(
                actual_position=None,
                portfolio_positions={},
            )

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                bot.stop()

            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(
                payload["snapshotType"],
                "stopped_paper_authoritative_safety",
            )
            self.assertEqual(
                payload["source"],
                "stopped_paper_engine_portfolio_snapshot",
            )
            self.assertEqual(payload["generation"], 1)
            self.assertEqual(payload["evidenceGeneration"], 1)
            self.assertEqual(payload["runtimeInstanceId"], (
                bot.runtime_instance_id
            ))
            self.assertEqual(payload["capturedAt"], now)
            self.assertEqual(payload["timestampEpoch"], now)
            self.assertEqual(payload["writtenAt"], now)
            self.assertFalse(payload["positionRemaining"])
            self.assertFalse(payload["pendingOrder"])
            self.assertEqual(payload["openOrderCount"], 0)
            self.assertFalse(payload["stateUnknown"])
            self.assertEqual(
                payload["positionStateSource"],
                "execution_engine.actual_position+portfolio.positions",
            )
            self.assertEqual(
                payload["pendingStateSource"],
                "execution_engine.pending_order_duplicate_lock",
            )
            self.assertEqual(
                payload["openOrderStateSource"],
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection",
            )
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_durable_atomic_save_failure_fails_closed(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        path = self._temporary_durable_snapshot_path()

        try:
            governance_state["mode"] = "PAPER"
            bot = self._configure_durable_snapshot_path(
                self._stopped_paper_bot(),
                path,
            )
            bot.engine = self._paper_engine_for_stop(
                actual_position=None,
                portfolio_positions={},
            )

            with patch(
                "backend.bot_manager.bot_manager.os.replace",
                side_effect=OSError("replace failed"),
            ):
                bot.stop()

            self.assertFalse(os.path.exists(path))
            self.assertTrue(bot.account_snapshot["stateUnknown"])
            self.assertEqual(
                bot.account_snapshot["authorityReason"],
                "SNAPSHOT_PERSIST_FAILED",
            )

            restarted = self._restart_stopped_paper_bot(path)
            restarted.account_snapshot = deepcopy(bot.account_snapshot)
            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=restarted,
            ):
                retry = asyncio.run(emergency_retry())

            self.assertFalse(retry["success"])
            self.assertTrue(retry["state_unknown"])
            self.assertEqual(
                retry["error_code"],
                "SNAPSHOT_PERSIST_FAILED",
            )
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
        finally:
            self._restore_governance(state_before)

    def test_fastapi_shutdown_hook_uses_existing_singleton_without_creation(
        self,
    ):
        import backend.main as main

        bot = Mock()
        with patch(
            "backend.main.get_existing_bot_manager",
            return_value=bot,
        ) as existing:
            asyncio.run(main.shutdown_event())

        existing.assert_called_once_with()
        bot.shutdown.assert_called_once_with()

        with patch(
            "backend.main.get_existing_bot_manager",
            return_value=None,
        ), patch(
            "backend.bot_manager.bot_manager.BotManager",
        ) as constructor:
            asyncio.run(main.shutdown_event())
        constructor.assert_not_called()
        self.assertIn(main.shutdown_event, main.app.router.on_shutdown)

    def test_shutdown_persists_paper_engine_before_destroy_and_is_idempotent(
        self,
    ):
        path = self._temporary_durable_snapshot_path()
        bot = self._configure_durable_snapshot_path(
            self._stopped_paper_bot(),
            path,
        )
        bot.engine = self._paper_engine_for_stop(
            actual_position=None,
            portfolio_positions={},
        )
        engine = bot.engine
        engine.stop = Mock(return_value={"status": "stopped"})
        events = []
        original_persist = bot._persist_stopped_paper_durable_snapshot

        def persist(snapshot):
            self.assertIsNotNone(bot.engine)
            events.append("persist")
            return original_persist(snapshot)

        def engine_stop():
            events.append("engine_stop")
            return {"status": "stopped"}

        engine.stop.side_effect = engine_stop

        with patch.object(
            bot,
            "_persist_stopped_paper_durable_snapshot",
            side_effect=persist,
        ):
            bot.shutdown()
        events.append("destroyed" if bot.engine is None else "retained")
        second = bot.shutdown()

        self.assertEqual(events, ["persist", "engine_stop", "destroyed"])
        engine.stop.assert_called_once_with()
        self.assertTrue(second["persisted"])
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["generation"], 1)

    def test_engine_stop_failure_retains_engine_and_fails_closed(self):
        path = self._temporary_durable_snapshot_path()
        bot = self._configure_durable_snapshot_path(
            self._stopped_paper_bot(),
            path,
        )
        engine = self._paper_engine_for_stop(None, {})
        engine.stop = Mock(side_effect=RuntimeError("stop failed"))
        bot.engine = engine

        result = bot.stop()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "ENGINE_STOP_FAILED")
        self.assertIs(bot.engine, engine)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(bot.account_snapshot["stateUnknown"])
        self.assertEqual(
            bot.account_snapshot["authorityReason"],
            "ENGINE_STOP_FAILED",
        )

    def test_emergency_engine_stop_failure_is_action_required_and_locked(self):
        from backend.routers import positions as positions_router

        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        bot, engine = self._paper_emergency_bot({
            "success": True,
            "requested": 0,
            "flattened": 0,
            "failed": 0,
            "skipped": True,
        })
        engine.stop.side_effect = RuntimeError("stop failed")
        positions_router.set_engine(engine)

        try:
            result = bot.run_emergency_orchestrator()
            last_result = governance_state["last_emergency_result"]

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(result["error_code"], "ENGINE_STOP_FAILED")
            self.assertTrue(result["emergency_locked"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertIs(bot.engine, engine)
            self.assertIs(positions_router.engine, engine)
            self.assertFalse(os.path.exists(
                bot.stopped_paper_durable_snapshot_path
            ))
            self.assertFalse(last_result["success"])
            self.assertFalse(last_result["completed"])
            self.assertTrue(last_result["stateUnknown"])

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException):
                    asyncio.run(emergency_unlock())
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            positions_router.set_engine(None)
            self._restore_governance(state_before)

    def test_emergency_rejects_invalid_engine_stop_results(self):
        invalid_results = (None, False, {}, {"status": "error"})

        for invalid_result in invalid_results:
            with self.subTest(stop_result=invalid_result):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                bot, engine = self._paper_emergency_bot({
                    "success": True,
                    "skipped": True,
                })
                engine.stop.return_value = invalid_result

                try:
                    result = bot.run_emergency_orchestrator()
                    self.assertFalse(result["success"])
                    self.assertFalse(result["completed"])
                    self.assertTrue(result["state_unknown"])
                    self.assertEqual(
                        result["error_code"],
                        "ENGINE_STOP_FAILED",
                    )
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                    self.assertIs(bot.engine, engine)
                finally:
                    self._restore_governance(state_before)

    def test_emergency_success_rejects_remaining_registry_engine(self):
        from backend.routers import positions as positions_router

        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        bot, engine = self._paper_emergency_bot({
            "success": True,
            "skipped": True,
        })
        positions_router.set_engine(engine)

        try:
            with patch(
                "backend.routers.positions.set_engine",
                side_effect=lambda value: None,
            ):
                result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(
                result["error_code"],
                "ENGINE_REGISTRY_STILL_ATTACHED",
            )
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
        finally:
            positions_router.set_engine(None)
            self._restore_governance(state_before)

    def test_stop_and_shutdown_are_serialized_without_double_engine_stop(self):
        path = self._temporary_durable_snapshot_path()
        bot = self._configure_durable_snapshot_path(
            self._stopped_paper_bot(),
            path,
        )
        engine = self._paper_engine_for_stop(None, {})
        engine.stop = Mock(return_value={"status": "stopped"})
        bot.engine = engine
        persist_entered = threading.Event()
        release_persist = threading.Event()
        shutdown_attempted = threading.Event()
        shutdown_done = threading.Event()
        original_persist = bot._persist_stopped_paper_durable_snapshot

        def blocking_persist(snapshot):
            persist_entered.set()
            self.assertTrue(release_persist.wait(timeout=2))
            return original_persist(snapshot)

        def run_shutdown():
            shutdown_attempted.set()
            bot.shutdown()
            shutdown_done.set()

        with patch.object(
            bot,
            "_persist_stopped_paper_durable_snapshot",
            side_effect=blocking_persist,
        ):
            stop_thread = threading.Thread(target=bot.stop)
            stop_thread.start()
            self.assertTrue(persist_entered.wait(timeout=2))
            shutdown_thread = threading.Thread(target=run_shutdown)
            shutdown_thread.start()
            self.assertTrue(shutdown_attempted.wait(timeout=2))
            self.assertFalse(shutdown_done.wait(timeout=0.05))
            release_persist.set()
            stop_thread.join(timeout=2)
            shutdown_thread.join(timeout=2)

        self.assertFalse(stop_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        engine.stop.assert_called_once_with()
        self.assertIsNone(bot.engine)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["generation"], 1)

    def test_shutdown_without_engine_requires_valid_paper_authority(self):
        path = self._temporary_durable_snapshot_path()
        bot, payload = self._persist_flat_stopped_paper_durable_snapshot(path)
        os.remove(path)

        result = bot.shutdown()
        self.assertTrue(result["persisted"])
        self.assertTrue(os.path.exists(path))

        for mutation in (
            {"source": "guessed_snapshot"},
            {"stateUnknown": True},
            {"mode": "live"},
        ):
            if os.path.exists(path):
                os.remove(path)
            candidate = deepcopy(bot.account_snapshot)
            candidate.update(mutation)
            bot.account_snapshot = candidate
            result = bot.shutdown()
            self.assertFalse(result["persisted"])
            self.assertFalse(os.path.exists(path))

        self.assertEqual(payload["generation"], 1)

    def test_shutdown_invalid_identity_marks_in_memory_state_unknown(self):
        path = self._temporary_durable_snapshot_path()
        bot, _ = self._persist_flat_stopped_paper_durable_snapshot(path)
        os.remove(path)
        bot.account_snapshot["evidenceRuntimeInstanceId"] = ""

        result = bot.shutdown()

        self.assertTrue(result["success"])
        self.assertFalse(result["persisted"])
        self.assertEqual(
            result["reason"],
            "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
        )
        self.assertTrue(bot.account_snapshot["stateUnknown"])
        self.assertEqual(
            bot.account_snapshot["authorityReason"],
            "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
        )
        self.assertFalse(os.path.exists(path))

    def test_shutdown_generation_guard_rejects_older_snapshot(self):
        path = self._temporary_durable_snapshot_path()
        bot, newer = self._persist_flat_stopped_paper_durable_snapshot(path)
        newer["generation"] = 4
        newer["evidenceGeneration"] = 4
        self._write_durable_snapshot_payload(path, newer)

        bot.account_snapshot["generation"] = 3
        bot.account_snapshot["evidenceGeneration"] = 3
        bot.account_snapshot_generation = 3
        result = bot.shutdown()

        self.assertFalse(result["persisted"])
        self.assertEqual(result["reason"], "SNAPSHOT_GENERATION_OLDER")
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["generation"], 4)

    def test_shutdown_timestamp_overwrite_boundaries(self):
        path = self._temporary_durable_snapshot_path()
        bot, payload = self._persist_flat_stopped_paper_durable_snapshot(path)
        snapshot = deepcopy(bot.account_snapshot)
        base_timestamp = payload["timestampEpoch"]

        for delta, expected, reason in (
            (-1, False, "SNAPSHOT_TIMESTAMP_OLDER"),
            (0, True, None),
            (1, True, None),
        ):
            candidate = deepcopy(snapshot)
            candidate["capturedAt"] = base_timestamp + delta
            candidate["timestampEpoch"] = base_timestamp + delta
            candidate["evidenceCapturedAt"] = base_timestamp + delta
            persisted, actual_reason = (
                bot._persist_stopped_paper_durable_snapshot(candidate)
            )
            self.assertIs(persisted, expected)
            self.assertEqual(actual_reason, reason)

    def test_durable_evidence_identity_fields_are_strictly_validated(self):
        path = self._temporary_durable_snapshot_path()
        bot, payload = self._persist_flat_stopped_paper_durable_snapshot(path)
        cases = (
            ("missing-generation", "evidenceGeneration", None, True),
            ("bool-generation", "evidenceGeneration", True, False),
            ("mismatch-generation", "evidenceGeneration", 9, False),
            (
                "missing-runtime",
                "evidenceRuntimeInstanceId",
                None,
                True,
            ),
            ("empty-runtime", "evidenceRuntimeInstanceId", "", False),
            (
                "mismatch-runtime",
                "evidenceRuntimeInstanceId",
                "different-runtime",
                False,
            ),
        )

        for name, field, value, remove in cases:
            with self.subTest(name=name):
                candidate = deepcopy(payload)
                if remove:
                    candidate.pop(field, None)
                else:
                    candidate[field] = value
                validation = bot._validate_stopped_paper_durable_snapshot(
                    candidate,
                    allow_current_runtime=True,
                )
                self.assertFalse(validation["valid"])

    def test_live_shutdown_stops_engine_without_paper_durable_file(self):
        path = self._temporary_durable_snapshot_path()
        bot = self._configure_durable_snapshot_path(
            self._stopped_paper_bot(),
            path,
        )
        engine = Mock()
        engine.mode = "live"
        engine.stop.return_value = {"status": "stopped"}
        bot.engine = engine

        result = bot.shutdown()

        self.assertEqual(result["status"], "stopped")
        engine.stop.assert_called_once_with()
        self.assertIsNone(bot.engine)
        self.assertFalse(os.path.exists(path))

    def test_shutdown_atomic_failure_is_logged_and_fails_closed(self):
        path = self._temporary_durable_snapshot_path()
        bot, _ = self._persist_flat_stopped_paper_durable_snapshot(path)
        os.remove(path)

        with patch.object(
            bot,
            "_write_json_atomic",
            side_effect=OSError("disk unavailable"),
        ), patch(
            "backend.bot_manager.bot_manager.logger.error",
        ) as log_error:
            result = bot.shutdown()

        self.assertFalse(result["persisted"])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(bot.account_snapshot["stateUnknown"])
        log_error.assert_called_once()
        self.assertIn("SNAPSHOT_PERSIST_FAILED", log_error.call_args.args[0])

    def test_stopped_paper_restart_rebinds_durable_snapshot_and_unlocks(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )
        path = self._temporary_durable_snapshot_path()

        try:
            governance_state["mode"] = "PAPER"
            old_bot, payload = (
                self._persist_flat_stopped_paper_durable_snapshot(path)
            )
            new_bot = self._restart_stopped_paper_bot(path)

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=new_bot,
            ):
                first = asyncio.run(emergency_orchestrate())

            self.assertFalse(first["success"])
            self.assertTrue(first["state_unknown"])
            self.assertEqual(first["error_code"], "SNAPSHOT_NOT_SYNCED")
            first_operation_id = (
                governance_state["last_emergency_result"]["operationId"]
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=new_bot,
            ):
                retry = asyncio.run(emergency_retry())

            retry_operation_id = (
                governance_state["last_emergency_result"]["operationId"]
            )
            fresh_snapshot = new_bot.account_snapshot

            self.assertTrue(retry["success"])
            self.assertTrue(retry["completed"])
            self.assertFalse(retry["state_unknown"])
            self.assertFalse(retry["position_remaining"])
            self.assertEqual(retry["path"], "paper")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertNotEqual(first_operation_id, retry_operation_id)
            self.assertEqual(
                fresh_snapshot["operationId"],
                retry_operation_id,
            )
            self.assertEqual(
                fresh_snapshot["source"],
                "stopped_paper_preserved_runtime_state",
            )
            self.assertEqual(
                fresh_snapshot["sourceSnapshotSource"],
                payload["source"],
            )
            self.assertEqual(
                fresh_snapshot["evidenceGeneration"],
                payload["generation"],
            )
            self.assertEqual(
                fresh_snapshot["evidenceRuntimeInstanceId"],
                old_bot.runtime_instance_id,
            )
            self.assertEqual(
                fresh_snapshot["currentEmergencyOperationId"],
                retry_operation_id,
            )
            self.assertNotEqual(
                fresh_snapshot["evidenceRuntimeInstanceId"],
                new_bot.runtime_instance_id,
            )
            self.assertFalse(fresh_snapshot["positionRemaining"])
            self.assertFalse(fresh_snapshot["pendingOrder"])
            self.assertEqual(fresh_snapshot["openOrderCount"], 0)
            self.assertFalse(fresh_snapshot["stateUnknown"])

            shutdown_result = new_bot.shutdown()
            self.assertTrue(shutdown_result["persisted"])
            self.assertFalse(new_bot.account_snapshot["stateUnknown"])
            with open(path, "r", encoding="utf-8") as handle:
                shutdown_payload = json.load(handle)
            self.assertEqual(
                shutdown_payload["generation"],
                payload["generation"],
            )
            self.assertEqual(
                shutdown_payload["runtimeInstanceId"],
                old_bot.runtime_instance_id,
            )
            self.assertEqual(
                shutdown_payload["evidenceRuntimeInstanceId"],
                old_bot.runtime_instance_id,
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=new_bot,
            ):
                unlocked = asyncio.run(emergency_unlock())

            self.assertTrue(unlocked["success"])
            self.assertTrue(unlocked["unlocked"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
            self.assertFalse(governance_state["emergency_stop"])
        finally:
            self._restore_governance(state_before)

    def test_stopped_paper_durable_snapshot_invalid_inputs_fail_closed(
        self,
    ):
        cases = [
            (
                "corrupt-json",
                None,
                "DURABLE_SNAPSHOT_CORRUPT",
            ),
            (
                "bad-schema",
                lambda payload: payload.update({"schemaVersion": 999}),
                "DURABLE_SNAPSHOT_SCHEMA_UNSUPPORTED",
            ),
            (
                "bad-type",
                lambda payload: payload.update({"snapshotType": "other"}),
                "DURABLE_SNAPSHOT_TYPE_INVALID",
            ),
            (
                "bad-source",
                lambda payload: payload.update({"source": "unknown"}),
                "SNAPSHOT_SOURCE_UNKNOWN",
            ),
            (
                "bad-position-source",
                lambda payload: payload.update({
                    "positionStateSource": "manager.position",
                }),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "bad-open-order-source",
                lambda payload: payload.update({
                    "openOrderStateSource": "manager.pending_order",
                }),
                "OPEN_ORDER_UNKNOWN",
            ),
            (
                "state-unknown",
                lambda payload: payload.update({
                    "stateUnknown": True,
                    "authorityReason": "STATE_UNKNOWN",
                }),
                "STATE_UNKNOWN",
            ),
            (
                "position-remaining",
                lambda payload: payload.update({
                    "positionRemaining": True,
                    "position": {
                        "symbol": "XRPUSDT",
                        "side": "BUY",
                    },
                    "positions": [{
                        "symbol": "XRPUSDT",
                        "side": "BUY",
                    }],
                }),
                "POSITION_REMAINING",
            ),
            (
                "pending-remaining",
                lambda payload: payload.update({"pendingOrder": True}),
                "PENDING_ORDER_REMAINING",
            ),
            (
                "open-order-remaining",
                lambda payload: payload.update({
                    "openOrderCount": 1,
                    "openOrderStateSource": "execution_engine.open_orders",
                }),
                "OPEN_ORDER_REMAINING",
            ),
            (
                "malformed-bool",
                lambda payload: payload.update({
                    "positionRemaining": None,
                }),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "malformed-open-order-count",
                lambda payload: payload.update({"openOrderCount": None}),
                "OPEN_ORDER_UNKNOWN",
            ),
            (
                "malformed-timestamp",
                lambda payload: payload.update({"capturedAt": "bad"}),
                "SNAPSHOT_TIMESTAMP_INVALID",
            ),
            (
                "live-mode",
                lambda payload: payload.update({
                    "mode": "live",
                    "tradeMode": "live",
                    "selectedMode": "LIVE",
                }),
                "MODE_UNKNOWN",
            ),
        ]

        for name, mutate, error_code in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=True,
                )
                path = self._temporary_durable_snapshot_path()

                try:
                    governance_state["mode"] = "PAPER"
                    _, payload = (
                        self._persist_flat_stopped_paper_durable_snapshot(
                            path
                        )
                    )
                    if name == "corrupt-json":
                        with open(path, "w", encoding="utf-8") as handle:
                            handle.write("{bad json")
                    else:
                        mutate(payload)
                        self._write_durable_snapshot_payload(path, payload)

                    _, retry = self._retry_stopped_paper_with_durable_path(
                        path
                    )

                    self.assertFalse(retry["success"])
                    self.assertTrue(retry["partial"])
                    self.assertEqual(retry["error_code"], error_code)
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_stopped_paper_durable_snapshot_invalidated_on_paper_start(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )
        path = self._temporary_durable_snapshot_path()
        config = {
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
            "mode": "paper",
            "risk_percent": 1,
            "position_size": 100,
            "max_drawdown_pct": 5,
            "sl_percent": 0.5,
            "tp_percent": 1,
            "timeframe": "5m",
            "trailing_stop": False,
            "leverage": 5,
        }

        try:
            governance_state["mode"] = "PAPER"
            self._persist_flat_stopped_paper_durable_snapshot(path)
            self.assertTrue(os.path.exists(path))

            bot = None
            bot = self._restart_stopped_paper_bot(path)
            ws = Mock()
            ws.connected = False

            with patch(
                "backend.bot_manager.bot_manager.ExchangeFactory"
                ".create_market_ws",
                return_value=ws,
            ):
                result = bot.start(config)

            self.assertEqual(result["status"], "started")
            self.assertFalse(os.path.exists(path))
        finally:
            with patch(
                "backend.bot_manager.bot_manager.time.sleep",
                return_value=None,
            ):
                try:
                    if bot is not None:
                        bot.stop()
                except Exception:
                    pass
            self._restore_governance(state_before)

    def test_emergency_retry_normalizes_governance_paper_mode(self):
        now = 1_800_000_000.0
        stale_update = now - 600.0

        for mode in ("paper", "PAPER", " paper "):
            with self.subTest(mode=mode):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=True,
                )

                try:
                    governance_state["mode"] = mode
                    bot = self._stopped_paper_bot()
                    bot.config.pop("mode", None)
                    bot.account_stale_after = 90.0
                    bot.account_snapshot["last_update"] = stale_update

                    with patch(
                        "backend.bot_manager.bot_manager.time.time",
                        return_value=now,
                    ):
                        result = bot.retry_emergency_orchestrator()

                    self.assertTrue(result["success"])
                    self.assertEqual(result["path"], "paper")
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_LOCKED,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_rejects_malformed_modes(self):
        malformed_modes = [
            True,
            False,
            1,
            0,
            {},
            [],
            "demo",
            "unknown",
            None,
        ]

        for mode in malformed_modes:
            with self.subTest(mode=repr(mode)):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=True,
                )

                try:
                    governance_state["mode"] = "PAPER"
                    bot = self._stopped_paper_bot()
                    bot.config["mode"] = mode

                    result = bot.retry_emergency_orchestrator()

                    self.assertFalse(result["success"])
                    self.assertTrue(result["state_unknown"])
                    self.assertEqual(result["error_code"], "MODE_UNKNOWN")
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_rejects_mode_conflict(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        now = 1_800_000_000.0
        stale_update = now - 600.0

        try:
            governance_state["mode"] = "PAPER"
            bot = self._stopped_paper_bot()
            bot.config["mode"] = "live"
            bot.account_stale_after = 90.0
            bot.account_snapshot["last_update"] = stale_update
            original_snapshot = bot.account_snapshot

            with patch(
                "backend.bot_manager.bot_manager.time.time",
                return_value=now,
            ):
                result = bot.retry_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(result["error_code"], "MODE_CONFLICT")
            self.assertIsNone(result["path"])
            self.assertIs(bot.account_snapshot, original_snapshot)
            self.assertEqual(
                bot.account_snapshot["last_update"],
                stale_update,
            )
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_stopped_paper_requires_authoritative_safety(self):
        cases = [
            (
                "mode-missing",
                lambda bot: (
                    bot.config.pop("mode", None),
                    governance_state.pop("mode", None),
                ),
                "MODE_UNKNOWN",
            ),
            (
                "mode-unknown",
                lambda bot: bot.config.update({"mode": "unknown"}),
                "MODE_UNKNOWN",
            ),
            (
                "snapshot-unsynced",
                lambda bot: bot.account_snapshot.update({
                    "available": False,
                }),
                "SNAPSHOT_NOT_SYNCED",
            ),
            (
                "snapshot-last-update-missing",
                lambda bot: bot.account_snapshot.update({
                    "last_update": None,
                }),
                "SNAPSHOT_TIMESTAMP_MISSING",
            ),
            (
                "snapshot-none",
                lambda bot: setattr(bot, "account_snapshot", None),
                "SNAPSHOT_UNAVAILABLE",
            ),
            (
                "position-none-without-authoritative-positions",
                lambda bot: bot.account_snapshot.update({
                    "position": None,
                    "positions": None,
                    "positionRemaining": None,
                }),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "position-empty-dict",
                lambda bot: bot.account_snapshot.update({
                    "position": {},
                }),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "positions-empty-dict",
                lambda bot: bot.account_snapshot.update({
                    "position": None,
                    "positions": [{}],
                }),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "position-key-missing",
                lambda bot: bot.account_snapshot.pop("position"),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "positions-key-missing",
                lambda bot: bot.account_snapshot.pop("positions"),
                "POSITION_STATE_UNKNOWN",
            ),
            (
                "pending-order-missing",
                lambda bot: bot.account_snapshot.pop("pendingOrder"),
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "pending-order-none",
                lambda bot: bot.account_snapshot.update({
                    "pendingOrder": None,
                }),
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "pending-order-non-bool",
                lambda bot: bot.account_snapshot.update({
                    "pendingOrder": {},
                }),
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "authoritative-state-exception",
                lambda bot: setattr(
                    bot,
                    "_capture_account_snapshot",
                    Mock(side_effect=RuntimeError("snapshot failed")),
                ),
                "SNAPSHOT_UNAVAILABLE",
            ),
        ]

        for name, mutate, error_code in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=False,
                    emergency_stop=False,
                )

                try:
                    bot = self._stopped_paper_bot()
                    mutate(bot)

                    result = bot.run_emergency_orchestrator()
                    last_result = (
                        governance_state["last_emergency_result"]
                    )

                    self.assertFalse(result["success"])
                    self.assertFalse(result["completed"])
                    self.assertTrue(result["partial"])
                    self.assertTrue(result["state_unknown"])
                    self.assertIsNone(result["position_remaining"])
                    self.assertTrue(result["retryable"])
                    self.assertEqual(result["error_code"], error_code)
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                    self.assertEqual(
                        last_result["state"],
                        EMERGENCY_ACTION_REQUIRED,
                    )
                    self.assertEqual(
                        last_result["result"],
                        EMERGENCY_RESULT_PARTIAL,
                    )
                    self.assertTrue(last_result["stateUnknown"])
                    self.assertNotEqual(
                        last_result["result"],
                        EMERGENCY_RESULT_SUCCESS,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_stopped_paper_action_required_on_position(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )

        try:
            bot = self._stopped_paper_bot()
            bot.account_snapshot["positionRemaining"] = True
            bot.account_snapshot["position"] = {
                "symbol": "XRPUSDT",
                "side": "BUY",
            }
            bot.account_snapshot["positions"] = [
                bot.account_snapshot["position"],
            ]

            result = bot.run_emergency_orchestrator()
            emergency = bot.get_status()["emergency"]

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertTrue(result["position_remaining"])
            self.assertTrue(result["retryable"])
            self.assertEqual(result["error_code"], "POSITION_REMAINING")
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(emergency["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertTrue(emergency["lastResult"]["positionRemaining"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_stopped_paper_action_required_on_pending_order(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )

        try:
            bot = self._stopped_paper_bot()
            bot.account_snapshot["pendingOrder"] = True
            bot.account_snapshot["pending_order"] = True

            result = bot.run_emergency_orchestrator()
            emergency = bot.get_status()["emergency"]

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertFalse(result["position_remaining"])
            self.assertTrue(result["retryable"])
            self.assertEqual(
                result["error_code"],
                "PENDING_ORDER_REMAINING",
            )
            self.assertEqual(emergency["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertEqual(
                emergency["lastResult"]["result"],
                EMERGENCY_RESULT_PARTIAL,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_state_model_partial_is_action_required(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            flatten_result = {
                "success": False,
                "error": "INVALID_FLATTEN_PRICE",
                "position_after": {
                    "side": "BUY",
                },
            }
            bot, _ = self._paper_emergency_bot(flatten_result)

            result = bot.run_emergency_orchestrator()
            emergency = bot.get_status()["emergency"]
            last_result = emergency["lastResult"]

            self.assertFalse(result["success"])
            self.assertTrue(result["partial"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertTrue(emergency["locked"])
            self.assertEqual(emergency["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertEqual(last_result["result"], EMERGENCY_RESULT_PARTIAL)
            self.assertEqual(last_result["path"], "paper")
            self.assertTrue(last_result["positionRemaining"])
            self.assertFalse(last_result["stateUnknown"])
            self.assertTrue(last_result["retryable"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_state_model_failed_is_action_required(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None

            operation = begin_emergency_operation()
            saved = complete_emergency_operation(
                {
                    "success": False,
                    "completed": False,
                    "partial": False,
                    "state_unknown": False,
                    "execution_path": "paper",
                    "position_remaining": False,
                    "retryable": True,
                    "error_code": "FAILED_FOR_TEST",
                    "cancel": {
                        "success": False,
                        "api_key": "SHOULD_NOT_LEAK",
                    },
                    "flatten": {
                        "success": False,
                        "secret": "SHOULD_NOT_LEAK",
                    },
                },
                operation,
            )

            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(saved["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertEqual(saved["result"], EMERGENCY_RESULT_FAILED)
            self.assertTrue(saved["retryable"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_state_model_does_not_expose_secrets(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            bot, _, _ = self._live_emergency_bot(
                cancel_result={
                    "success": True,
                    "requested": 1,
                    "cancelled": 1,
                    "failed": 0,
                    "api_key": "SHOULD_NOT_LEAK",
                    "headers": {
                        "KC-API-KEY": "SHOULD_NOT_LEAK",
                    },
                },
                flatten_result={
                    "success": True,
                    "skipped": False,
                    "accepted": True,
                    "confirmed": True,
                    "closed": True,
                    "api_secret": "SHOULD_NOT_LEAK",
                    "raw_order": {
                        "secret": "SHOULD_NOT_LEAK",
                    },
                },
            )

            bot.run_emergency_orchestrator()
            emergency = bot.get_status()["emergency"]
            serialized = json.dumps(
                emergency["lastResult"],
                sort_keys=True,
            )

            self.assertNotIn("SHOULD_NOT_LEAK", serialized)
            self.assertNotIn("api_key", serialized)
            self.assertNotIn("api_secret", serialized)
            self.assertNotIn("headers", serialized)
            self.assertNotIn("KC-API-KEY", serialized)
            self.assertNotIn("raw_order", serialized)
            self.assertEqual(
                emergency["lastResult"]["cancelResult"]["orders_cancelled"],
                1,
            )
            self.assertTrue(
                emergency["lastResult"]["flattenResult"][
                    "position_closed"
                ]
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_succeeds_only_from_locked_safe_state(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result()
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)
            bot = self._bot_with_pending_sources(
                manager_pending=False,
                engine_pending=False,
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                result = asyncio.run(emergency_unlock())

            self.assertTrue(result["success"])
            self.assertTrue(result["unlocked"])
            self.assertFalse(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
            self.assertFalse(bot._running)
            self.assertEqual(bot.lifecycle_state, "STOPPED")

            status = bot.get_status()
            response = StatusResponse(**status)
            emergency = status["emergency"]

            self.assertFalse(response.loopEnabled)
            self.assertEqual(response.loopState, "STOPPED")
            self.assertFalse(response.autoTradeEnabled)
            self.assertFalse(response.executionEnabled)
            self.assertFalse(response.pendingOrder)
            self.assertFalse(emergency["active"])
            self.assertFalse(emergency["locked"])
            self.assertEqual(emergency["state"], EMERGENCY_READY)
            self.assertIs(emergency["lastResult"], last_result)
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_ready_state(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "NOT_LOCKED",
            )
            self.assertFalse(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_READY,
            )
            self.assertIsNone(governance_state["last_emergency_result"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_processing_state(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result(
                state=EMERGENCY_PROCESSING,
                result=EMERGENCY_RESULT_NONE,
                success=False,
                completed=False,
                partial=False,
                retryable=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_PROCESSING
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "PROCESSING",
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_PROCESSING,
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_action_required_state(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "ACTION_REQUIRED",
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_position_remaining(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result(
                position_remaining=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "POSITION_REMAINING",
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_state_unknown(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result(
                state_unknown=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "STATE_UNKNOWN",
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_execution_enabled_without_changing_it(
        self,
    ):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result()
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)

            with self.assertRaises(HTTPException) as raised:
                asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "EXECUTION_ENABLED",
            )
            self.assertTrue(governance_state["execution_enabled"])
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_unlock_rejects_incomplete_or_inconsistent_result(
        self,
    ):
        def missing_operation_id(last_result):
            last_result.pop("operationId")

        cases = [
            (
                "last-result-missing",
                None,
                None,
                "LAST_RESULT_MISSING",
            ),
            (
                "last-result-invalid",
                "malformed",
                None,
                "LAST_RESULT_INVALID",
            ),
            (
                "result-missing",
                lambda last_result: last_result.pop("result"),
                None,
                "RESULT_MISSING",
            ),
            (
                "result-partial",
                lambda last_result: last_result.update({
                    "result": EMERGENCY_RESULT_PARTIAL,
                    "success": False,
                }),
                None,
                "RESULT_NOT_SUCCESS",
            ),
            (
                "result-failed",
                lambda last_result: last_result.update({
                    "result": EMERGENCY_RESULT_FAILED,
                    "success": False,
                }),
                None,
                "RESULT_NOT_SUCCESS",
            ),
            (
                "success-false",
                lambda last_result: last_result.update({
                    "success": False,
                }),
                None,
                "SUCCESS_NOT_TRUE",
            ),
            (
                "success-missing",
                lambda last_result: last_result.pop("success"),
                None,
                "SUCCESS_MISSING",
            ),
            (
                "completed-false",
                lambda last_result: last_result.update({
                    "completed": False,
                }),
                None,
                "COMPLETED_NOT_TRUE",
            ),
            (
                "completed-missing",
                lambda last_result: last_result.pop("completed"),
                None,
                "COMPLETED_MISSING",
            ),
            (
                "state-unknown-true",
                lambda last_result: last_result.update({
                    "stateUnknown": True,
                }),
                None,
                "STATE_UNKNOWN",
            ),
            (
                "state-unknown-missing",
                lambda last_result: last_result.pop("stateUnknown"),
                None,
                "STATE_UNKNOWN_MISSING",
            ),
            (
                "position-remaining-true",
                lambda last_result: last_result.update({
                    "positionRemaining": True,
                }),
                None,
                "POSITION_REMAINING",
            ),
            (
                "position-remaining-missing",
                lambda last_result: last_result.pop("positionRemaining"),
                None,
                "POSITION_REMAINING_MISSING",
            ),
            (
                "current-operation-id-missing",
                lambda _last_result: None,
                None,
                "CURRENT_OPERATION_ID_MISSING",
            ),
            (
                "result-operation-id-missing",
                missing_operation_id,
                "emg_20260714T123456Z_unlock",
                "RESULT_OPERATION_ID_MISSING",
            ),
            (
                "operation-id-mismatch",
                lambda _last_result: None,
                "emg_20260714T999999Z_current",
                "OPERATION_ID_MISMATCH",
            ),
            (
                "old-operation-success",
                lambda _last_result: None,
                "emg_20260714T999999Z_retry",
                "OPERATION_ID_MISMATCH",
            ),
        ]

        for name, mutation, current_operation_id, reason in cases:
            with self.subTest(name=name):
                state_before = dict(governance_state)

                try:
                    last_result = (
                        self._saved_emergency_result()
                        if callable(mutation) or current_operation_id
                        else mutation
                    )

                    if callable(mutation):
                        mutation(last_result)

                    governance_state["execution_enabled"] = False
                    governance_state["emergency_stop"] = True
                    governance_state["emergency_state"] = EMERGENCY_LOCKED
                    governance_state["last_emergency_result"] = last_result

                    if current_operation_id is None:
                        governance_state[
                            "current_emergency_operation_id"
                        ] = None
                    else:
                        governance_state[
                            "current_emergency_operation_id"
                        ] = current_operation_id

                    if (
                        current_operation_id is None
                        and isinstance(last_result, dict)
                        and name != "current-operation-id-missing"
                    ):
                        self._set_current_emergency_operation(last_result)

                    bot = BotManager()

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(emergency_unlock())

                    self.assertEqual(raised.exception.status_code, 409)
                    self.assertEqual(
                        raised.exception.detail["reason"],
                        reason,
                    )
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_LOCKED,
                    )
                    self.assertFalse(
                        governance_state["execution_enabled"]
                    )
                    self.assertIs(
                        governance_state["last_emergency_result"],
                        last_result,
                    )
                finally:
                    self._restore_governance(state_before)

    def test_pending_order_state_normalizes_manager_and_engine(
        self,
    ):
        cases = [
            {
                "name": "manager-false-engine-false",
                "manager_pending": False,
                "engine_pending": False,
                "known": True,
                "pending": False,
                "safe": True,
                "reason": "NO_PENDING_ORDER",
                "source": "manager_and_engine",
                "mismatch": False,
                "legacy": False,
            },
            {
                "name": "manager-true-engine-true",
                "manager_pending": True,
                "engine_pending": True,
                "known": True,
                "pending": True,
                "safe": False,
                "reason": "PENDING_ORDER_REMAINING",
                "source": "manager_and_engine",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "manager-true-engine-false",
                "manager_pending": True,
                "engine_pending": False,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MISMATCH",
                "source": "manager_and_engine",
                "mismatch": True,
                "legacy": True,
            },
            {
                "name": "manager-false-engine-true",
                "manager_pending": False,
                "engine_pending": True,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MISMATCH",
                "source": "manager_and_engine",
                "mismatch": True,
                "legacy": True,
            },
            {
                "name": "engine-unavailable",
                "manager_pending": False,
                "engine_pending": "engine-none",
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "SNAPSHOT_NOT_SYNCED",
                "source": "stopped_paper_authoritative",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "manager-malformed-string",
                "manager_pending": "false",
                "engine_pending": False,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MANAGER_UNKNOWN",
                "source": "unknown",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "manager-malformed-int",
                "manager_pending": 1,
                "engine_pending": False,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MANAGER_UNKNOWN",
                "source": "unknown",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "manager-malformed-dict",
                "manager_pending": {},
                "engine_pending": False,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MANAGER_UNKNOWN",
                "source": "unknown",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "manager-malformed-list",
                "manager_pending": [],
                "engine_pending": False,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_MANAGER_UNKNOWN",
                "source": "unknown",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "engine-malformed-string",
                "manager_pending": False,
                "engine_pending": "false",
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": "engine",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "engine-malformed-int",
                "manager_pending": False,
                "engine_pending": 1,
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": "engine",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "engine-malformed-dict",
                "manager_pending": False,
                "engine_pending": {},
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": "engine",
                "mismatch": False,
                "legacy": True,
            },
            {
                "name": "engine-malformed-list",
                "manager_pending": False,
                "engine_pending": [],
                "known": False,
                "pending": None,
                "safe": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": "engine",
                "mismatch": False,
                "legacy": True,
            },
        ]

        for case in cases:
            with self.subTest(name=case["name"]):
                bot = BotManager()
                bot.pending_order = case["manager_pending"]
                bot.engine = (
                    None
                    if case["engine_pending"] == "engine-none"
                    else self._pending_order_engine(
                        case["engine_pending"]
                    )
                )

                state = bot.get_authoritative_pending_order_state()
                status = bot.get_status()
                response = StatusResponse(**status)
                status_state = status["pendingOrderState"]

                self.assertEqual(state["known"], case["known"])
                self.assertEqual(state["pending"], case["pending"])
                self.assertEqual(state["safe"], case["safe"])
                self.assertEqual(state["reason"], case["reason"])
                self.assertEqual(state["source"], case["source"])
                self.assertEqual(state["mismatch"], case["mismatch"])
                self.assertEqual(
                    state["pending_order"],
                    case["legacy"],
                )
                self.assertEqual(
                    status["pendingOrder"],
                    case["legacy"],
                )
                self.assertEqual(
                    response.pendingOrder,
                    case["legacy"],
                )
                self.assertEqual(
                    status_state["known"],
                    case["known"],
                )
                self.assertEqual(
                    status_state["pending"],
                    case["pending"],
                )
                self.assertEqual(
                    status_state["safe"],
                    case["safe"],
                )
                self.assertEqual(
                    status_state["reason"],
                    case["reason"],
                )
                self.assertEqual(
                    status_state["source"],
                    case["source"],
                )
                self.assertEqual(
                    status_state["mismatch"],
                    case["mismatch"],
                )
                self.assertIn("pending_order_state", status)

    def test_emergency_unlock_rejects_pending_order_not_authoritative(
        self,
    ):
        cases = [
            (
                "manager-false-engine-true",
                False,
                True,
                "PENDING_ORDER_MISMATCH",
            ),
            (
                "manager-false-engine-none",
                False,
                "engine-none",
                "SNAPSHOT_NOT_SYNCED",
            ),
            (
                "manager-false-engine-pending-none",
                False,
                None,
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "manager-false-engine-pending-missing",
                False,
                "missing",
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "manager-false-engine-pending-non-bool",
                False,
                {},
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "manager-true-engine-false",
                True,
                False,
                "PENDING_ORDER_MISMATCH",
            ),
            (
                "manager-true-engine-true",
                True,
                True,
                "PENDING_ORDER_REMAINING",
            ),
            (
                "manager-pending-missing",
                "missing",
                False,
                "PENDING_ORDER_MANAGER_UNKNOWN",
            ),
            (
                "manager-pending-non-bool",
                {},
                False,
                "PENDING_ORDER_MANAGER_UNKNOWN",
            ),
            (
                "engine-pending-read-exception",
                False,
                "raises",
                "PENDING_ORDER_READ_FAILED",
            ),
        ]

        for name, manager_pending, engine_pending, reason in cases:
            with self.subTest(name=name):
                state_before = dict(governance_state)

                try:
                    last_result = self._saved_emergency_result()
                    governance_state["execution_enabled"] = False
                    governance_state["emergency_stop"] = True
                    governance_state["emergency_state"] = EMERGENCY_LOCKED
                    governance_state["last_emergency_result"] = last_result
                    self._set_current_emergency_operation(last_result)

                    bot = BotManager()
                    if manager_pending == "missing":
                        delattr(bot, "pending_order")
                    else:
                        bot.pending_order = manager_pending

                    if engine_pending == "engine-none":
                        bot.engine = None
                    elif engine_pending == "raises":
                        bot.engine = self._pending_order_raising_engine()
                    else:
                        bot.engine = self._pending_order_engine(
                            engine_pending
                        )

                    pending_state = (
                        bot.get_authoritative_pending_order_state()
                    )
                    status = bot.get_status()

                    self.assertTrue(status["pendingOrder"])
                    self.assertEqual(pending_state["reason"], reason)

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(emergency_unlock())

                    self.assertEqual(raised.exception.status_code, 409)
                    self.assertEqual(
                        raised.exception.detail["reason"],
                        reason,
                    )
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertEqual(
                        governance_state["emergency_state"],
                        EMERGENCY_LOCKED,
                    )
                    self.assertFalse(
                        governance_state["execution_enabled"]
                    )
                    self.assertIs(
                        governance_state["last_emergency_result"],
                        last_result,
                    )
                    self.assertFalse(bot._running)
                    self.assertEqual(bot.lifecycle_state, "STOPPED")
                    self.assertFalse(status["loopEnabled"])
                    self.assertFalse(status["autoTradeEnabled"])
                finally:
                    self._restore_governance(state_before)

    def test_status_and_unlock_guard_share_pending_order_authority(self):
        cases = [
            (
                "safe",
                False,
                False,
                False,
                None,
            ),
            (
                "engine-pending",
                False,
                True,
                True,
                "PENDING_ORDER_MISMATCH",
            ),
            (
                "engine-unknown",
                False,
                None,
                True,
                "PENDING_ORDER_UNKNOWN",
            ),
            (
                "engine-none",
                False,
                "engine-none",
                True,
                "SNAPSHOT_NOT_SYNCED",
            ),
        ]

        for (
            name,
            manager_pending,
            engine_pending,
            expected_status_pending,
            expected_reason,
        ) in cases:
            with self.subTest(name=name):
                state_before = dict(governance_state)

                try:
                    last_result = self._saved_emergency_result()
                    governance_state["execution_enabled"] = False
                    governance_state["emergency_stop"] = True
                    governance_state["emergency_state"] = EMERGENCY_LOCKED
                    governance_state["last_emergency_result"] = last_result
                    self._set_current_emergency_operation(last_result)

                    bot = BotManager()
                    bot.pending_order = manager_pending
                    bot.engine = (
                        None
                        if engine_pending == "engine-none"
                        else self._pending_order_engine(engine_pending)
                    )

                    pending_state = (
                        bot.get_authoritative_pending_order_state()
                    )
                    status = bot.get_status()
                    reason = emergency_unlock_block_reason(
                        pending_state
                    )

                    self.assertEqual(
                        status["pendingOrder"],
                        expected_status_pending,
                    )
                    self.assertEqual(reason, expected_reason)
                finally:
                    self._restore_governance(state_before)

    def test_emergency_unlock_rejects_unlock_processing_exception(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result()
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)
            bot = self._bot_with_pending_sources(
                manager_pending=False,
                engine_pending=False,
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with patch(
                    "backend.runtime.governance_runtime."
                    "record_emergency_timeline_event",
                    side_effect=RuntimeError("timeline failed"),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        asyncio.run(emergency_unlock())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "UNLOCK_FAILED",
            )
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertFalse(governance_state["execution_enabled"])
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_succeeds_only_from_action_required(self):
        state_before = dict(governance_state)

        try:
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
                state_unknown=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)
            governance_state["emergency_timeline"] = []
            bot = self._stopped_paper_bot()

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                result = asyncio.run(emergency_retry())

            emergency = bot.get_status()["emergency"]
            last_result = governance_state["last_emergency_result"]
            new_operation_id = last_result["operationId"]
            events = self._emergency_timeline_events()
            operation_events = [
                event
                for event in events
                if event.get("operationId") == new_operation_id
            ]

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            self.assertFalse(result["state_unknown"])
            self.assertFalse(result["position_remaining"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertTrue(emergency["locked"])
            self.assertEqual(emergency["state"], EMERGENCY_LOCKED)
            self.assertNotEqual(
                emergency["lastResult"]["operationId"],
                previous["operationId"],
            )
            self.assertEqual(
                governance_state["current_emergency_operation_id"],
                new_operation_id,
            )
            self.assertEqual(
                [event["event"] for event in operation_events],
                ["EMERGENCY_STARTED", "EMERGENCY_COMPLETED"],
            )
            self.assertEqual(len(operation_events), 2)
            self.assertFalse(bot._running)
            self.assertEqual(bot.lifecycle_state, "STOPPED")
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_failure_keeps_action_required(self):
        state_before = dict(governance_state)

        try:
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
                state_unknown=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)
            governance_state["emergency_timeline"] = []
            bot = self._stopped_paper_bot()
            bot.account_snapshot["positionRemaining"] = True
            bot.account_snapshot["position"] = {
                "symbol": "XRPUSDT",
                "side": "BUY",
            }

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                result = asyncio.run(emergency_retry())

            emergency = bot.get_status()["emergency"]
            last_result = governance_state["last_emergency_result"]
            new_operation_id = last_result["operationId"]
            events = self._emergency_timeline_events()
            operation_events = [
                event
                for event in events
                if event.get("operationId") == new_operation_id
            ]

            self.assertFalse(result["success"])
            self.assertTrue(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertTrue(result["position_remaining"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(emergency["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertTrue(emergency["lastResult"]["positionRemaining"])
            self.assertNotEqual(new_operation_id, previous["operationId"])
            self.assertEqual(
                governance_state["current_emergency_operation_id"],
                new_operation_id,
            )
            self.assertEqual(
                [event["event"] for event in operation_events],
                ["EMERGENCY_STARTED", "EMERGENCY_ACTION_REQUIRED"],
            )
            self.assertEqual(len(operation_events), 2)
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_rejects_non_action_required_states(self):
        cases = [
            (EMERGENCY_READY, False, "NOT_ACTION_REQUIRED"),
            (EMERGENCY_PROCESSING, True, "PROCESSING"),
            (EMERGENCY_LOCKED, True, "ALREADY_LOCKED"),
            (None, True, "STATE_MISSING"),
            ("BROKEN_STATE", True, "INVALID_STATE"),
        ]

        for state, emergency_stop, reason in cases:
            with self.subTest(state=state):
                state_before = dict(governance_state)
                bot = BotManager()

                try:
                    governance_state["execution_enabled"] = False
                    governance_state["emergency_stop"] = emergency_stop
                    if state is None:
                        governance_state.pop("emergency_state", None)
                    else:
                        governance_state["emergency_state"] = state
                    governance_state["last_emergency_result"] = (
                        self._saved_emergency_result(state=state)
                        if state not in {EMERGENCY_READY, None}
                        else None
                    )
                    if isinstance(
                        governance_state["last_emergency_result"],
                        dict,
                    ):
                        self._set_current_emergency_operation(
                            governance_state["last_emergency_result"]
                        )
                    governance_state["emergency_timeline"] = []
                    expected_last_result = governance_state[
                        "last_emergency_result"
                    ]
                    expected_current_operation_id = governance_state.get(
                        "current_emergency_operation_id"
                    )

                    with patch(
                        "backend.api.governance.get_bot_manager",
                        return_value=bot,
                    ):
                        with self.assertRaises(HTTPException) as raised:
                            asyncio.run(emergency_retry())

                    self.assertEqual(raised.exception.status_code, 409)
                    self.assertEqual(
                        raised.exception.detail["reason"],
                        reason,
                    )
                    self.assertIs(
                        governance_state["last_emergency_result"],
                        expected_last_result,
                    )
                    self.assertEqual(
                        governance_state.get(
                            "current_emergency_operation_id"
                        ),
                        expected_current_operation_id,
                    )
                    self.assertEqual(
                        self._emergency_timeline_events(),
                        [],
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_retry_timeline_uses_new_operation(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=False,
        )

        try:
            bot = self._stopped_paper_bot()
            bot.account_snapshot["positionRemaining"] = True
            bot.account_snapshot["position"] = {
                "symbol": "XRPUSDT",
                "side": "BUY",
            }

            first = bot.run_emergency_orchestrator()
            first_operation_id = (
                governance_state["last_emergency_result"]["operationId"]
            )
            bot.account_snapshot["position"] = None
            bot.account_snapshot["positions"] = []
            bot.account_snapshot["positionRemaining"] = False

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                second = asyncio.run(emergency_retry())

            second_operation_id = (
                governance_state["last_emergency_result"]["operationId"]
            )
            events = self._emergency_timeline_events()
            events_by_operation = {
                operation_id: [
                    event["event"]
                    for event in events
                    if event.get("operationId") == operation_id
                ]
                for operation_id in {
                    first_operation_id,
                    second_operation_id,
                }
            }

            self.assertFalse(first["success"])
            self.assertTrue(second["success"])
            self.assertNotEqual(
                first_operation_id,
                second_operation_id,
            )
            self.assertEqual(
                events_by_operation[first_operation_id],
                ["EMERGENCY_STARTED", "EMERGENCY_ACTION_REQUIRED"],
            )
            self.assertEqual(
                events_by_operation[second_operation_id],
                ["EMERGENCY_STARTED", "EMERGENCY_COMPLETED"],
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_retry_rejects_when_mutex_busy(self):
        state_before = dict(governance_state)
        bot = self._stopped_paper_bot()
        acquired = False

        try:
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)
            governance_state["emergency_timeline"] = []
            expected_operation_id = governance_state[
                "current_emergency_operation_id"
            ]

            acquired = bot.emergency_orchestrator_lock.acquire(
                blocking=False
            )
            self.assertTrue(acquired)

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(emergency_retry())

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(
                raised.exception.detail["reason"],
                "PROCESSING",
            )
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                previous,
            )
            self.assertEqual(
                governance_state["current_emergency_operation_id"],
                expected_operation_id,
            )
            self.assertEqual(self._emergency_timeline_events(), [])
        finally:
            if acquired:
                bot.emergency_orchestrator_lock.release()
            self._restore_governance(state_before)

    def test_emergency_retry_concurrent_requests_do_not_queue(self):
        state_before = dict(governance_state)
        entered_cancel = threading.Event()
        release_cancel = threading.Event()
        outcomes = []

        def call_retry(label):
            try:
                outcomes.append((
                    label,
                    "success",
                    asyncio.run(emergency_retry()),
                ))
            except HTTPException as exc:
                outcomes.append((label, "error", exc))

        try:
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)
            governance_state["emergency_timeline"] = []
            bot, _, exchange = self._live_emergency_bot(
                cancel_result={
                    "success": True,
                    "requested": 1,
                    "cancelled": 1,
                    "failed": 0,
                    "skipped": False,
                },
                flatten_result={
                    "success": True,
                    "skipped": False,
                    "accepted": True,
                    "confirmed": True,
                    "closed": True,
                },
                real_order_allowed=True,
            )

            def blocking_cancel(_symbol):
                entered_cancel.set()
                release_cancel.wait(5)
                return {
                    "success": True,
                    "requested": 1,
                    "cancelled": 1,
                    "failed": 0,
                    "skipped": False,
                }

            exchange.cancel_all_orders.side_effect = blocking_cancel

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                first = threading.Thread(
                    target=call_retry,
                    args=("first",),
                )
                first.start()
                self.assertTrue(entered_cancel.wait(5))

                second = threading.Thread(
                    target=call_retry,
                    args=("second",),
                )
                second.start()
                second.join(5)
                self.assertFalse(second.is_alive())

                with self.assertRaises(HTTPException) as emergency_busy:
                    asyncio.run(emergency_orchestrate())

                with self.assertRaises(HTTPException) as unlock_busy:
                    asyncio.run(emergency_unlock())

                release_cancel.set()
                first.join(5)
                self.assertFalse(first.is_alive())

            success_results = [
                value
                for _label, status, value in outcomes
                if status == "success"
            ]
            retry_errors = [
                value
                for _label, status, value in outcomes
                if status == "error"
            ]
            events = self._emergency_timeline_events()
            started_events = [
                event
                for event in events
                if event.get("event") == "EMERGENCY_STARTED"
            ]
            completion_events = [
                event
                for event in events
                if event.get("event") == "EMERGENCY_COMPLETED"
            ]
            operation_ids = {
                event.get("operationId")
                for event in events
                if event.get("operationId")
            }

            self.assertEqual(len(success_results), 1)
            self.assertEqual(len(retry_errors), 1)
            self.assertTrue(success_results[0]["success"])
            self.assertEqual(retry_errors[0].status_code, 409)
            self.assertEqual(
                retry_errors[0].detail["reason"],
                "PROCESSING",
            )
            self.assertEqual(emergency_busy.exception.status_code, 409)
            self.assertEqual(
                emergency_busy.exception.detail["reason"],
                "PROCESSING",
            )
            self.assertEqual(unlock_busy.exception.status_code, 409)
            self.assertEqual(
                unlock_busy.exception.detail["reason"],
                "PROCESSING",
            )
            self.assertEqual(exchange.cancel_all_orders.call_count, 1)
            self.assertEqual(
                exchange.flatten_current_position.call_count,
                1,
            )
            self.assertEqual(len(started_events), 1)
            self.assertEqual(len(completion_events), 1)
            self.assertEqual(len(operation_ids), 1)
            self.assertNotIn(previous["operationId"], operation_ids)
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertEqual(
                governance_state["current_emergency_operation_id"],
                next(iter(operation_ids)),
            )
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            release_cancel.set()
            self._restore_governance(state_before)

    def test_emergency_retry_exception_completes_and_releases_mutex(self):
        state_before = dict(governance_state)

        try:
            previous = self._saved_emergency_result(
                state=EMERGENCY_ACTION_REQUIRED,
                result=EMERGENCY_RESULT_PARTIAL,
                success=False,
                completed=False,
                partial=True,
                retryable=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED
            governance_state["last_emergency_result"] = previous
            self._set_current_emergency_operation(previous)
            governance_state["emergency_timeline"] = []
            bot = self._stopped_paper_bot()
            bot._emergency_symbol = Mock(
                side_effect=RuntimeError("symbol failed")
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                first = asyncio.run(emergency_retry())

            failed_result = governance_state["last_emergency_result"]
            failed_operation_id = failed_result["operationId"]
            failed_events = [
                event
                for event in self._emergency_timeline_events()
                if event.get("operationId") == failed_operation_id
            ]

            self.assertFalse(first["success"])
            self.assertTrue(first["state_unknown"])
            self.assertEqual(
                first["error_code"],
                "ORCHESTRATOR_EXCEPTION",
            )
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_ACTION_REQUIRED,
            )
            self.assertEqual(
                [event["event"] for event in failed_events],
                ["EMERGENCY_STARTED", "EMERGENCY_ACTION_REQUIRED"],
            )
            self.assertEqual(len(failed_events), 2)

            delattr(bot, "_emergency_symbol")

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                second = asyncio.run(emergency_retry())

            self.assertTrue(second["success"])
            self.assertTrue(second["completed"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
            self.assertNotEqual(
                governance_state["last_emergency_result"]["operationId"],
                failed_operation_id,
            )
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_records_started_once(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None
            governance_state["emergency_timeline"] = []

            operation = begin_emergency_operation()
            events = self._emergency_timeline_events()

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["type"], "EMERGENCY")
            self.assertEqual(events[0]["event"], "EMERGENCY_STARTED")
            self.assertEqual(events[0]["state"], EMERGENCY_PROCESSING)
            self.assertEqual(
                events[0]["operationId"],
                operation["operation_id"],
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_records_success_and_status_timeline(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            bot, _ = self._paper_emergency_bot({
                "success": True,
                "requested": 1,
                "flattened": 1,
                "failed": 0,
                "skipped": False,
            })

            result = bot.run_emergency_orchestrator()
            events = self._emergency_timeline_events()
            status_events = bot.get_status()["runtime_health"]["timeline"]

            self.assertTrue(result["completed"])
            self.assertEqual(
                [event["event"] for event in events],
                ["EMERGENCY_STARTED", "EMERGENCY_COMPLETED"],
            )
            self.assertEqual(events[-1]["state"], EMERGENCY_LOCKED)
            self.assertEqual(events[-1]["result"], EMERGENCY_RESULT_SUCCESS)
            self.assertEqual(events[-1]["path"], "paper")
            self.assertEqual(
                status_events[-1]["event"],
                "EMERGENCY_COMPLETED",
            )
            self.assertEqual(
                status_events[-1]["label"],
                "EMERGENCY STOPPED SAFELY",
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_records_partial_action_required(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            bot, _ = self._paper_emergency_bot({
                "success": False,
                "error": "INVALID_FLATTEN_PRICE",
                "position_after": {
                    "side": "BUY",
                },
            })

            result = bot.run_emergency_orchestrator()
            events = self._emergency_timeline_events()

            self.assertTrue(result["partial"])
            self.assertEqual(events[-1]["event"], "EMERGENCY_ACTION_REQUIRED")
            self.assertEqual(events[-1]["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertEqual(events[-1]["result"], EMERGENCY_RESULT_PARTIAL)
            self.assertTrue(
                events[-1]["details"]["positionRemaining"]
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_records_failed_action_required(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None
            governance_state["emergency_timeline"] = []

            operation = begin_emergency_operation()
            saved = complete_emergency_operation(
                {
                    "success": False,
                    "completed": False,
                    "partial": False,
                    "state_unknown": False,
                    "execution_path": "paper",
                    "position_remaining": False,
                    "retryable": True,
                    "error_code": "FAILED_FOR_TIMELINE_TEST",
                },
                operation,
            )
            events = self._emergency_timeline_events()

            self.assertEqual(saved["result"], EMERGENCY_RESULT_FAILED)
            self.assertEqual(events[-1]["event"], "EMERGENCY_ACTION_REQUIRED")
            self.assertEqual(events[-1]["state"], EMERGENCY_ACTION_REQUIRED)
            self.assertEqual(events[-1]["result"], EMERGENCY_RESULT_FAILED)
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_records_unlock_success(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result()
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)
            governance_state["emergency_timeline"] = []

            bot = self._bot_with_pending_sources(
                manager_pending=False,
                engine_pending=False,
            )

            with patch(
                "backend.api.governance.get_bot_manager",
                return_value=bot,
            ):
                result = asyncio.run(emergency_unlock())
            events = self._emergency_timeline_events()

            self.assertTrue(result["unlocked"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event"], "EMERGENCY_UNLOCKED")
            self.assertEqual(events[0]["state"], EMERGENCY_READY)
            self.assertEqual(
                events[0]["operationId"],
                last_result["operationId"],
            )
            self.assertIs(
                governance_state["last_emergency_result"],
                last_result,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_does_not_record_unlock_rejection(self):
        state_before = dict(governance_state)

        try:
            last_result = self._saved_emergency_result(
                position_remaining=True,
            )
            governance_state["execution_enabled"] = False
            governance_state["emergency_stop"] = True
            governance_state["emergency_state"] = EMERGENCY_LOCKED
            governance_state["last_emergency_result"] = last_result
            self._set_current_emergency_operation(last_result)
            governance_state["emergency_timeline"] = []

            with self.assertRaises(HTTPException):
                asyncio.run(emergency_unlock())

            self.assertEqual(self._emergency_timeline_events(), [])
            self.assertTrue(governance_state["emergency_stop"])
            self.assertEqual(
                governance_state["emergency_state"],
                EMERGENCY_LOCKED,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_deduplicates_completion_event(self):
        state_before = dict(governance_state)

        try:
            governance_state["execution_enabled"] = True
            governance_state["emergency_stop"] = False
            governance_state["emergency_state"] = EMERGENCY_READY
            governance_state["last_emergency_result"] = None
            governance_state["emergency_timeline"] = []
            operation = begin_emergency_operation()
            response = {
                "success": True,
                "completed": True,
                "partial": False,
                "state_unknown": False,
                "execution_path": "paper",
                "position_remaining": False,
                "retryable": False,
                "flatten": {
                    "success": True,
                    "skipped": True,
                },
            }

            complete_emergency_operation(response, operation)
            complete_emergency_operation(response, operation)
            completion_events = [
                event
                for event in self._emergency_timeline_events()
                if event["event"] == "EMERGENCY_COMPLETED"
            ]

            self.assertEqual(len(completion_events), 1)
        finally:
            self._restore_governance(state_before)

    def test_emergency_timeline_preserves_emergency_events_after_stop(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )

        try:
            bot, _ = self._paper_emergency_bot({
                "success": True,
                "skipped": True,
            })
            bot._running = True
            bot.lifecycle_state = "RUNNING"
            bot.latest_runtime_result = {
                "runtimeStageTrace": {
                    "trading-runtime": {
                        "reached": True,
                        "status": "ACTIVE",
                        "timestamp": 1_700_000_000.0,
                    },
                },
            }

            bot.run_emergency_orchestrator()
            timeline = bot.get_status()["runtime_health"]["timeline"]

            emergency_events = [
                event
                for event in timeline
                if event.get("type") == "EMERGENCY"
            ]

            self.assertFalse(bot._running)
            self.assertEqual(bot.lifecycle_state, "STOPPED")
            self.assertEqual(
                [event.get("event") for event in emergency_events],
                ["EMERGENCY_STARTED", "EMERGENCY_COMPLETED"],
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_paper_completed_and_skip(self):
        cases = [
            (
                "position-flattened",
                {
                    "success": True,
                    "requested": 1,
                    "flattened": 1,
                    "failed": 0,
                    "skipped": False,
                },
            ),
            (
                "position-absent-skip",
                {
                    "success": True,
                    "requested": 0,
                    "flattened": 0,
                    "failed": 0,
                    "skipped": True,
                },
            ),
        ]

        for name, flatten_result in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                try:
                    bot, engine = self._paper_emergency_bot(flatten_result)

                    result = bot.run_emergency_orchestrator()

                    self.assertTrue(result["success"])
                    self.assertTrue(result["completed"])
                    self.assertFalse(result["partial"])
                    self.assertFalse(result["state_unknown"])
                    self.assertEqual(result["execution_path"], "paper")
                    self.assertFalse(result["retryable"])
                    self.assertTrue(result["emergency_locked"])
                    self.assertTrue(result["auto_trade_disabled"])
                    self.assertIs(result["flatten"], flatten_result)
                    self.assertFalse(result["position_remaining"])
                    engine.flatten_paper_position.assert_called_once_with(
                        reason="EMERGENCY_FLATTEN"
                    )
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertFalse(governance_state["execution_enabled"])
                finally:
                    self._restore_governance(state_before)

    def test_emergency_orchestrator_paper_flatten_failure(self):
        cases = [
            (
                "position-remaining",
                {
                    "success": False,
                    "error": "INVALID_FLATTEN_PRICE",
                    "position_after": {
                        "side": "BUY",
                    },
                },
                True,
                False,
                "INVALID_FLATTEN_PRICE",
            ),
            (
                "position-closed",
                {
                    "success": False,
                    "error": "PORTFOLIO_SYNC_FAILED",
                    "position_remaining": False,
                },
                False,
                False,
                "PORTFOLIO_SYNC_FAILED",
            ),
            (
                "position-unknown",
                {
                    "success": False,
                    "error": "FLATTEN_EXCEPTION",
                },
                None,
                True,
                "FLATTEN_EXCEPTION",
            ),
        ]

        for (
            name,
            flatten_result,
            position_remaining,
            state_unknown,
            error_code,
        ) in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                try:
                    bot, engine = self._paper_emergency_bot(flatten_result)

                    result = bot.run_emergency_orchestrator()

                    self.assertFalse(result["success"])
                    self.assertFalse(result["completed"])
                    self.assertTrue(result["partial"])
                    self.assertEqual(
                        result["state_unknown"],
                        state_unknown,
                    )
                    self.assertEqual(result["execution_path"], "paper")
                    self.assertIs(
                        result["position_remaining"],
                        position_remaining,
                    )
                    self.assertTrue(result["retryable"])
                    self.assertEqual(result["error_code"], error_code)
                    engine.flatten_paper_position.assert_called_once_with(
                        reason="EMERGENCY_FLATTEN"
                    )
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertFalse(governance_state["execution_enabled"])
                finally:
                    self._restore_governance(state_before)

    def test_emergency_orchestrator_live_completed_and_skip(self):
        cases = [
            (
                "all-success",
                {
                    "success": True,
                    "requested": 1,
                    "cancelled": 1,
                    "failed": 0,
                    "skipped": False,
                },
                {
                    "success": True,
                    "skipped": False,
                    "accepted": True,
                    "confirmed": True,
                    "closed": True,
                },
            ),
            (
                "all-skip",
                {
                    "success": True,
                    "requested": 0,
                    "cancelled": 0,
                    "failed": 0,
                    "skipped": True,
                },
                {
                    "success": True,
                    "skipped": True,
                    "accepted": False,
                    "confirmed": True,
                    "closed": False,
                },
            ),
        ]

        for name, cancel_result, flatten_result in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                try:
                    bot, engine, exchange = self._live_emergency_bot(
                        cancel_result=cancel_result,
                        flatten_result=flatten_result,
                    )

                    result = bot.run_emergency_orchestrator()

                    self.assertTrue(result["success"])
                    self.assertTrue(result["completed"])
                    self.assertFalse(result["partial"])
                    self.assertFalse(result["state_unknown"])
                    self.assertEqual(result["execution_path"], "live")
                    self.assertEqual(result["symbol"], "XRPUSDTM")
                    self.assertFalse(result["retryable"])
                    self.assertFalse(result["position_remaining"])
                    exchange.cancel_all_orders.assert_called_once_with(
                        "XRPUSDTM"
                    )
                    exchange.flatten_current_position.assert_called_once_with(
                        "XRPUSDTM"
                    )
                    engine.flatten_paper_position.assert_not_called()
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertFalse(governance_state["execution_enabled"])
                finally:
                    self._restore_governance(state_before)

    def test_emergency_orchestrator_live_requires_bool_true_readiness(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, _, exchange = self._live_emergency_bot(
                real_order_allowed=True,
            )

            result = bot.run_emergency_orchestrator()

            self.assertTrue(result["success"])
            self.assertTrue(result["completed"])
            exchange.cancel_all_orders.assert_called_once_with("XRPUSDTM")
            exchange.flatten_current_position.assert_called_once_with(
                "XRPUSDTM"
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_blocks_non_bool_live_readiness(self):
        cases = [
            ("false", {"realOrderAllowed": False}),
            ("none", {"realOrderAllowed": None}),
            ("string-false", {"realOrderAllowed": "false"}),
            ("string-true", {"realOrderAllowed": "true"}),
            ("string-upper-true", {"realOrderAllowed": "TRUE"}),
            ("zero", {"realOrderAllowed": 0}),
            ("one", {"realOrderAllowed": 1}),
            ("empty-dict", {"realOrderAllowed": {}}),
            ("truthy-dict", {"realOrderAllowed": {"allowed": True}}),
            ("empty-list", {"realOrderAllowed": []}),
            ("truthy-list", {"realOrderAllowed": [True]}),
            ("empty-string", {"realOrderAllowed": ""}),
            ("missing-key", {}),
            ("none-response", None),
            ("list-response", []),
            ("readiness-exception", RuntimeError("readiness failed")),
        ]

        for name, readiness in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                try:
                    bot, engine, exchange = self._live_emergency_bot(
                        real_order_allowed=True,
                    )

                    if isinstance(readiness, Exception):
                        engine.build_live_readiness.side_effect = readiness
                    else:
                        engine.build_live_readiness.return_value = readiness

                    result = bot.run_emergency_orchestrator()

                    self.assertFalse(result["success"])
                    self.assertFalse(result["completed"])
                    self.assertFalse(result["partial"])
                    self.assertTrue(result["state_unknown"])
                    self.assertEqual(
                        result["error_code"],
                        "EXECUTION_PATH_UNAVAILABLE",
                    )
                    self.assertTrue(result["emergency_locked"])
                    self.assertTrue(result["auto_trade_disabled"])
                    self.assertTrue(governance_state["emergency_stop"])
                    self.assertFalse(governance_state["execution_enabled"])
                    exchange.cancel_all_orders.assert_not_called()
                    exchange.flatten_current_position.assert_not_called()
                    engine.flatten_paper_position.assert_not_called()
                finally:
                    self._restore_governance(state_before)

    def test_emergency_orchestrator_live_cancel_failure_flatten_success_partial(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, _, exchange = self._live_emergency_bot(
                cancel_result={
                    "success": False,
                    "error": "OPEN_ORDERS_FAILED",
                },
                flatten_result={
                    "success": True,
                    "accepted": True,
                    "confirmed": True,
                    "closed": True,
                },
            )

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertFalse(result["position_remaining"])
            self.assertEqual(
                result["error_code"],
                "CANCEL_FAILED_FLATTEN_COMPLETED",
            )
            self.assertTrue(result["retryable"])
            exchange.flatten_current_position.assert_called_once_with(
                "XRPUSDTM"
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_live_position_remaining_partial(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, _, _ = self._live_emergency_bot(
                cancel_result={
                    "success": True,
                    "requested": 1,
                    "cancelled": 1,
                    "failed": 0,
                },
                flatten_result={
                    "success": False,
                    "accepted": True,
                    "confirmed": False,
                    "closed": False,
                    "error_code": "POSITION_REMAINS",
                    "final_position": {
                        "found": True,
                    },
                },
            )

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertTrue(result["position_remaining"])
            self.assertEqual(result["error_code"], "POSITION_REMAINS")
            self.assertTrue(result["retryable"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_live_flatten_unknown_state_is_partial(
        self,
    ):
        cases = [
            (
                "pre-check-timeout",
                {
                    "success": False,
                    "accepted": False,
                    "confirmed": False,
                    "error_code": "TIMEOUT",
                    "initial_position": {
                        "success": False,
                        "found": False,
                        "error_code": "TIMEOUT",
                    },
                },
                "TIMEOUT",
            ),
            (
                "position-api-error",
                {
                    "success": False,
                    "accepted": False,
                    "confirmed": False,
                    "error_code": "API_ERROR",
                    "initial_position": {
                        "success": False,
                        "found": False,
                        "error_code": "API_ERROR",
                    },
                },
                "API_ERROR",
            ),
            (
                "post-check-timeout",
                {
                    "success": False,
                    "accepted": True,
                    "confirmed": False,
                    "error_code": "POST_CHECK_TIMEOUT",
                    "final_position": {
                        "success": False,
                        "found": False,
                        "error_code": "TIMEOUT",
                    },
                },
                "POST_CHECK_TIMEOUT",
            ),
            (
                "post-check-malformed",
                {
                    "success": False,
                    "accepted": True,
                    "confirmed": False,
                    "error_code": "POST_CHECK_MALFORMED_RESPONSE",
                    "final_position": {
                        "success": False,
                        "found": False,
                        "error_code": "MALFORMED_RESPONSE",
                    },
                },
                "POST_CHECK_MALFORMED_RESPONSE",
            ),
            (
                "malformed-final-position",
                {
                    "success": False,
                    "accepted": True,
                    "confirmed": False,
                    "error_code": "POST_CHECK_MALFORMED_RESPONSE",
                    "final_position": {
                        "success": True,
                        "found": "false",
                    },
                },
                "POST_CHECK_MALFORMED_RESPONSE",
            ),
            (
                "non-dict-response",
                ["not", "a", "dict"],
                "FLATTEN_FAILED",
            ),
        ]

        for name, flatten_result, error_code in cases:
            with self.subTest(name=name):
                state_before = self._set_governance(
                    execution_enabled=True,
                    emergency_stop=False,
                )
                try:
                    bot, _, exchange = self._live_emergency_bot(
                        cancel_result={
                            "success": True,
                            "requested": 0,
                            "cancelled": 0,
                            "failed": 0,
                            "skipped": True,
                        },
                        flatten_result=flatten_result,
                    )

                    result = bot.run_emergency_orchestrator()

                    self.assertFalse(result["success"])
                    self.assertFalse(result["completed"])
                    self.assertTrue(result["partial"])
                    self.assertTrue(result["state_unknown"])
                    self.assertIsNone(result["position_remaining"])
                    self.assertTrue(result["retryable"])
                    self.assertEqual(result["error_code"], error_code)
                    exchange.cancel_all_orders.assert_called_once_with(
                        "XRPUSDTM"
                    )
                    exchange.flatten_current_position.assert_called_once_with(
                        "XRPUSDTM"
                    )
                finally:
                    self._restore_governance(state_before)

    def test_emergency_orchestrator_live_cancel_and_flatten_failure(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, _, exchange = self._live_emergency_bot(
                cancel_result={
                    "success": False,
                    "error": "OPEN_ORDERS_FAILED",
                },
                flatten_result={
                    "success": False,
                    "accepted": False,
                    "confirmed": False,
                    "error_code": "API_ERROR",
                },
            )

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertTrue(result["partial"])
            self.assertTrue(result["state_unknown"])
            self.assertIsNone(result["position_remaining"])
            self.assertEqual(
                result["error_code"],
                "CANCEL_AND_FLATTEN_FAILED",
            )
            self.assertTrue(result["retryable"])
            exchange.cancel_all_orders.assert_called_once_with("XRPUSDTM")
            exchange.flatten_current_position.assert_called_once_with(
                "XRPUSDTM"
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_live_engine_unavailable(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            governance_state["mode"] = "LIVE"
            bot = BotManager()
            bot.engine = None
            bot.lifecycle_state = "STOPPED"
            bot._running = False
            bot.symbol = "XRPUSDT"
            bot.orderbook_symbol = "XRPUSDTM"
            bot.config = {
                "symbol": "XRPUSDT",
                "mode": "live",
                "dry_run": False,
            }

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertFalse(result["partial"])
            self.assertTrue(result["state_unknown"])
            self.assertIsNone(result["execution_path"])
            self.assertIsNone(result["cancel"])
            self.assertIsNone(result["flatten"])
            self.assertIsNone(result["position_remaining"])
            self.assertTrue(result["retryable"])
            self.assertEqual(result["error_code"], "ENGINE_UNAVAILABLE")
            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_rejects_live_without_exchange(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            engine = Mock()
            engine.mode = "live"
            engine.exchange = None
            engine.symbol = "XRPUSDT"
            engine.build_live_readiness.return_value = {
                "realOrderAllowed": True,
            }
            engine.flatten_paper_position = Mock()
            bot = self._emergency_bot_with_engine(engine)

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertFalse(result["partial"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(
                result["error_code"],
                "EXECUTION_PATH_UNAVAILABLE",
            )
            engine.flatten_paper_position.assert_not_called()
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_selected_mode_live_is_not_enough(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            exchange = Mock()
            bot, _, exchange = self._live_emergency_bot(
                real_order_allowed=False,
                exchange=exchange,
            )

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertFalse(result["partial"])
            self.assertTrue(result["state_unknown"])
            self.assertEqual(
                result["error_code"],
                "EXECUTION_PATH_UNAVAILABLE",
            )
            exchange.cancel_all_orders.assert_not_called()
            exchange.flatten_current_position.assert_not_called()
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_paper_does_not_call_kucoin_primitives(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            exchange = Mock()
            bot, _ = self._paper_emergency_bot(
                {
                    "success": True,
                    "requested": 1,
                    "flattened": 1,
                    "failed": 0,
                    "skipped": False,
                },
                exchange=exchange,
            )

            result = bot.run_emergency_orchestrator()

            self.assertTrue(result["completed"])
            exchange.cancel_all_orders.assert_not_called()
            exchange.flatten_current_position.assert_not_called()
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_mutex_already_running(self):
        state_before = self._set_governance(
            execution_enabled=False,
            emergency_stop=True,
        )
        bot, _ = self._paper_emergency_bot({
            "success": True,
            "skipped": True,
        })
        acquired = False

        try:
            acquired = bot.emergency_orchestrator_lock.acquire(
                blocking=False
            )
            self.assertTrue(acquired)

            result = bot.run_emergency_orchestrator()

            self.assertFalse(result["success"])
            self.assertFalse(result["completed"])
            self.assertFalse(result["partial"])
            self.assertFalse(result["state_unknown"])
            self.assertTrue(result["retryable"])
            self.assertEqual(
                result["error_code"],
                "EMERGENCY_ALREADY_RUNNING",
            )
            self.assertTrue(result["emergency_locked"])
            self.assertTrue(result["auto_trade_disabled"])
        finally:
            if acquired:
                bot.emergency_orchestrator_lock.release()
            self._restore_governance(state_before)

    def test_emergency_orchestrator_mutex_released_after_flatten_exception(
        self,
    ):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, engine = self._paper_emergency_bot({
                "success": True,
                "skipped": True,
            })
            engine.flatten_paper_position.side_effect = RuntimeError(
                "boom"
            )

            first = bot.run_emergency_orchestrator()

            self.assertFalse(first["success"])
            self.assertTrue(first["retryable"])

            engine.flatten_paper_position.side_effect = None
            engine.flatten_paper_position.return_value = {
                "success": True,
                "skipped": True,
            }
            bot.engine = engine

            second = bot.run_emergency_orchestrator()

            self.assertTrue(second["success"])
            self.assertTrue(second["completed"])
            self.assertEqual(
                engine.flatten_paper_position.call_count,
                2,
            )
        finally:
            self._restore_governance(state_before)

    def test_emergency_orchestrator_does_not_create_engine_or_client(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot, _ = self._paper_emergency_bot({
                "success": True,
                "skipped": True,
            })

            with patch(
                "backend.bot_manager.bot_manager.ExecutionEngine"
            ) as engine_class:
                with patch(
                    "backend.bot_manager.bot_manager.KucoinTradeClient"
                ) as client_class:
                    result = bot.run_emergency_orchestrator()

            self.assertTrue(result["completed"])
            engine_class.assert_not_called()
            client_class.assert_not_called()
            self.assertTrue(governance_state["emergency_stop"])
            self.assertFalse(governance_state["execution_enabled"])
        finally:
            self._restore_governance(state_before)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_normalizes_symbol_and_orders(
        self,
        request_get,
    ):
        request_get.return_value.json.return_value = self._order_page([
            {
                "id": "order-1",
                "symbol": "XRPUSDTM",
                "side": "buy",
                "type": "limit",
                "price": "0.52",
                "size": "10",
                "status": "active",
            }
        ])
        client = self._kucoin_client()

        result = client.get_open_orders("XRPUSDT")

        self.assertTrue(result["success"])
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["orders"][0]["order_id"], "order-1")
        self.assertEqual(result["orders"][0]["symbol"], "XRPUSDTM")
        self.assertEqual(result["orders"][0]["side"], "BUY")
        self.assertEqual(result["orders"][0]["type"], "limit")
        self.assertEqual(result["orders"][0]["price"], 0.52)
        self.assertEqual(result["orders"][0]["size"], 10.0)
        self.assertEqual(result["orders"][0]["status"], "active")

        parsed_url = urlparse(request_get.call_args.args[0])
        query = parse_qs(parsed_url.query)

        self.assertEqual(parsed_url.path, "/api/v1/orders")
        self.assertEqual(query["status"], ["active"])
        self.assertEqual(query["symbol"], ["XRPUSDTM"])
        self.assertEqual(query["currentPage"], ["1"])
        self.assertEqual(query["pageSize"], ["100"])
        self.assertEqual(request_get.call_args.kwargs["timeout"], 10)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_allows_empty_result(self, request_get):
        request_get.return_value.json.return_value = self._order_page([])
        client = self._kucoin_client()

        result = client.get_open_orders("XRPUSDTM")

        self.assertTrue(result["success"])
        self.assertEqual(result["orders"], [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["symbol"], "XRPUSDTM")

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_normalizes_multiple_orders(
        self,
        request_get,
    ):
        first_page = self._order_page(
            [
                {
                    "id": "order-1",
                    "symbol": "XRPUSDTM",
                    "side": "buy",
                }
            ],
            current_page=1,
            total_page=2,
        )
        second_page = self._order_page(
            [
                {
                    "orderId": "order-2",
                    "symbol": "XRPUSDTM",
                    "side": "sell",
                }
            ],
            current_page=2,
            total_page=2,
        )
        request_get.side_effect = [
            Mock(json=Mock(return_value=first_page)),
            Mock(json=Mock(return_value=second_page)),
        ]
        client = self._kucoin_client()

        result = client.get_open_orders("XRPUSDT")

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["orders"][0]["order_id"], "order-1")
        self.assertEqual(result["orders"][0]["side"], "BUY")
        self.assertEqual(result["orders"][1]["order_id"], "order-2")
        self.assertEqual(result["orders"][1]["side"], "SELL")
        self.assertEqual(result["pagination"]["pagesFetched"], 2)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_returns_failure_on_api_error(
        self,
        request_get,
    ):
        raw_error = {
            "code": "400100",
            "msg": "bad request",
        }
        request_get.return_value.json.return_value = raw_error
        client = self._kucoin_client()

        result = client.get_open_orders("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["orders"], [])
        self.assertEqual(result["count"], 0)
        self.assertIn("bad request", result["error"])
        self.assertEqual(result["raw"], raw_error)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_returns_failure_on_http_exception(
        self,
        request_get,
    ):
        request_get.side_effect = RuntimeError("network down")
        client = self._kucoin_client()

        result = client.get_open_orders("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["orders"], [])
        self.assertEqual(result["count"], 0)
        self.assertIn("network down", result["error"])

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_open_orders_allows_symbol_none(self, request_get):
        request_get.return_value.json.return_value = self._order_page([
            {
                "id": "order-1",
                "symbol": "XRPUSDTM",
                "side": "buy",
            }
        ])
        client = self._kucoin_client()

        result = client.get_open_orders()

        parsed_url = urlparse(request_get.call_args.args[0])
        query = parse_qs(parsed_url.query)

        self.assertTrue(result["success"])
        self.assertIsNone(result["symbol"])
        self.assertNotIn("symbol", query)
        self.assertEqual(query["status"], ["active"])

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_normalizes_symbol_and_uses_delete(
        self,
        request_delete,
    ):
        raw_response = {
            "code": "200000",
            "data": {
                "orderId": "order-123",
            },
        }
        request_delete.return_value.json.return_value = raw_response
        client = self._kucoin_client()

        with patch.object(
            client,
            "_headers",
            wraps=client._headers,
        ) as headers:
            result = client.cancel_order("order-123", "XRPUSDT")

        self.assertTrue(result["success"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["order_id"], "order-123")
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertEqual(result["raw"], raw_response)

        parsed_url = urlparse(request_delete.call_args.args[0])

        self.assertEqual(parsed_url.path, "/api/v1/orders/order-123")
        self.assertEqual(parsed_url.query, "")
        self.assertEqual(request_delete.call_args.kwargs["timeout"], 10)
        self.assertEqual(
            headers.call_args.args,
            ("DELETE", "/api/v1/orders/order-123"),
        )

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_allows_symbol_none(self, request_delete):
        request_delete.return_value.json.return_value = {
            "code": "200000",
            "data": {},
        }
        client = self._kucoin_client()

        result = client.cancel_order("order-123")

        self.assertTrue(result["success"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["order_id"], "order-123")
        self.assertIsNone(result["symbol"])

        parsed_url = urlparse(request_delete.call_args.args[0])

        self.assertEqual(parsed_url.path, "/api/v1/orders/order-123")

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_rejects_invalid_order_id(
        self,
        request_delete,
    ):
        client = self._kucoin_client()

        for order_id in [None, "", "   "]:
            with self.subTest(order_id=order_id):
                result = client.cancel_order(order_id, "XRPUSDT")

                self.assertFalse(result["success"])
                self.assertFalse(result["cancelled"])
                self.assertIsNone(result["order_id"])
                self.assertEqual(result["symbol"], "XRPUSDTM")
                self.assertEqual(result["error"], "INVALID_ORDER_ID")

        request_delete.assert_not_called()

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_returns_failure_on_api_error(
        self,
        request_delete,
    ):
        raw_error = {
            "code": "400100",
            "msg": "order not found",
        }
        request_delete.return_value.json.return_value = raw_error
        client = self._kucoin_client()

        result = client.cancel_order("order-123", "XRPUSDT")

        self.assertFalse(result["success"])
        self.assertFalse(result["cancelled"])
        self.assertEqual(result["order_id"], "order-123")
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertIn("order not found", result["error"])
        self.assertEqual(result["raw"], raw_error)

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_returns_failure_on_http_exception(
        self,
        request_delete,
    ):
        request_delete.side_effect = RuntimeError("network down")
        client = self._kucoin_client()

        result = client.cancel_order("order-123", "XRPUSDT")

        self.assertFalse(result["success"])
        self.assertFalse(result["cancelled"])
        self.assertEqual(result["order_id"], "order-123")
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertIn("network down", result["error"])
        self.assertIsNone(result["raw"])

    @patch("backend.execution.kucoin_trade.requests.delete")
    def test_kucoin_cancel_order_returns_failure_on_json_parse_error(
        self,
        request_delete,
    ):
        request_delete.return_value.json.side_effect = ValueError("bad json")
        client = self._kucoin_client()

        result = client.cancel_order("order-123", "XRPUSDT")

        self.assertFalse(result["success"])
        self.assertFalse(result["cancelled"])
        self.assertEqual(result["order_id"], "order-123")
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertIn("bad json", result["error"])
        self.assertIsNone(result["raw"])

    def test_kucoin_cancel_all_orders_cancels_multiple_orders(self):
        client = self._kucoin_client()
        open_result = {
            "success": True,
            "symbol": "XRPUSDTM",
            "orders": [
                {"order_id": "order-1"},
                {"order_id": "order-2"},
                {"order_id": "order-3"},
            ],
            "raw": {"source": "open-orders"},
        }
        cancel_results = [
            {
                "success": True,
                "order_id": "order-1",
                "cancelled": True,
                "raw": {"order": "order-1"},
            },
            {
                "success": True,
                "order_id": "order-2",
                "cancelled": True,
                "raw": {"order": "order-2"},
            },
            {
                "success": True,
                "order_id": "order-3",
                "cancelled": True,
                "raw": {"order": "order-3"},
            },
        ]

        with patch.object(
            client,
            "get_open_orders",
            return_value=open_result,
        ) as open_orders:
            with patch.object(
                client,
                "cancel_order",
                side_effect=cancel_results,
            ) as cancel_order:
                result = client.cancel_all_orders("XRPUSDT")

        self.assertTrue(result["success"])
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["cancelled"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertFalse(result["skipped"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["open_orders_raw"], {"source": "open-orders"})
        open_orders.assert_called_once_with("XRPUSDTM")
        cancel_order.assert_has_calls([
            call("order-1", "XRPUSDTM"),
            call("order-2", "XRPUSDTM"),
            call("order-3", "XRPUSDTM"),
        ])

    def test_kucoin_cancel_all_orders_skips_when_no_orders(self):
        client = self._kucoin_client()

        with patch.object(
            client,
            "get_open_orders",
            return_value={
                "success": True,
                "symbol": "XRPUSDTM",
                "orders": [],
                "raw": {"source": "open-orders"},
            },
        ) as open_orders:
            with patch.object(client, "cancel_order") as cancel_order:
                result = client.cancel_all_orders("XRPUSDT")

        self.assertTrue(result["success"])
        self.assertEqual(result["requested"], 0)
        self.assertEqual(result["cancelled"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["results"], [])
        open_orders.assert_called_once_with("XRPUSDTM")
        cancel_order.assert_not_called()

    def test_kucoin_cancel_all_orders_keeps_processing_after_failure(self):
        client = self._kucoin_client()

        with patch.object(
            client,
            "get_open_orders",
            return_value={
                "success": True,
                "symbol": "XRPUSDTM",
                "orders": [
                    {"order_id": "order-1"},
                    {"order_id": "order-2"},
                    {"order_id": "order-3"},
                ],
                "raw": {"source": "open-orders"},
            },
        ):
            with patch.object(
                client,
                "cancel_order",
                side_effect=[
                    {
                        "success": True,
                        "order_id": "order-1",
                        "cancelled": True,
                        "raw": {},
                    },
                    {
                        "success": False,
                        "order_id": "order-2",
                        "cancelled": False,
                        "error": "order not found",
                        "raw": {"msg": "order not found"},
                    },
                    {
                        "success": True,
                        "order_id": "order-3",
                        "cancelled": True,
                        "raw": {},
                    },
                ],
            ) as cancel_order:
                result = client.cancel_all_orders("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["cancelled"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["error"], "CANCEL_ALL_PARTIAL_FAILURE")
        self.assertEqual(cancel_order.call_count, 3)
        self.assertEqual(result["results"][1]["error"], "order not found")

    def test_kucoin_cancel_all_orders_does_not_cancel_when_open_orders_fails(
        self,
    ):
        client = self._kucoin_client()

        with patch.object(
            client,
            "get_open_orders",
            return_value={
                "success": False,
                "symbol": "XRPUSDTM",
                "orders": [],
                "error": "open failed",
                "raw": {"msg": "open failed"},
            },
        ) as open_orders:
            with patch.object(client, "cancel_order") as cancel_order:
                result = client.cancel_all_orders("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["requested"], 0)
        self.assertEqual(result["cancelled"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["error"], "open failed")
        self.assertEqual(result["open_orders_raw"], {"msg": "open failed"})
        open_orders.assert_called_once_with("XRPUSDTM")
        cancel_order.assert_not_called()

    def test_kucoin_cancel_all_orders_records_missing_order_id(self):
        client = self._kucoin_client()

        with patch.object(
            client,
            "get_open_orders",
            return_value={
                "success": True,
                "symbol": "XRPUSDTM",
                "orders": [
                    {"order_id": "order-1"},
                    {"symbol": "XRPUSDTM"},
                    {"orderId": "order-3"},
                ],
                "raw": {"source": "open-orders"},
            },
        ):
            with patch.object(
                client,
                "cancel_order",
                side_effect=[
                    {
                        "success": True,
                        "order_id": "order-1",
                        "cancelled": True,
                        "raw": {},
                    },
                    {
                        "success": True,
                        "order_id": "order-3",
                        "cancelled": True,
                        "raw": {},
                    },
                ],
            ) as cancel_order:
                result = client.cancel_all_orders("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["cancelled"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][1]["error"], "MISSING_ORDER_ID")
        cancel_order.assert_has_calls([
            call("order-1", "XRPUSDTM"),
            call("order-3", "XRPUSDTM"),
        ])
        self.assertEqual(cancel_order.call_count, 2)

    def test_kucoin_cancel_all_orders_rejects_invalid_symbol(self):
        client = self._kucoin_client()

        with patch.object(client, "get_open_orders") as open_orders:
            with patch.object(client, "cancel_order") as cancel_order:
                for symbol in [None, "", "   "]:
                    with self.subTest(symbol=symbol):
                        result = client.cancel_all_orders(symbol)

                        self.assertFalse(result["success"])
                        self.assertEqual(result["symbol"], None)
                        self.assertEqual(result["requested"], 0)
                        self.assertEqual(result["cancelled"], 0)
                        self.assertEqual(result["failed"], 0)
                        self.assertEqual(result["error"], "INVALID_SYMBOL")

        open_orders.assert_not_called()
        cancel_order.assert_not_called()

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_create_order_live_gate_still_blocks_without_request(
        self,
        request_post,
    ):
        client = self._kucoin_client()

        result = client.create_order(
            symbol="XRPUSDT",
            side="BUY",
            qty=1,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "LIVE_NOT_READY")
        request_post.assert_not_called()

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_get_positions_still_uses_positions_endpoint(
        self,
        request_get,
    ):
        request_get.return_value.json.return_value = {
            "code": "200000",
            "data": [
                {
                    "symbol": "XRPUSDTM",
                    "currentQty": "2",
                    "avgEntryPrice": "0.5",
                }
            ],
        }
        client = self._kucoin_client()

        result = client.get_positions("XRPUSDT")

        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertEqual(result["qty"], 2.0)
        self.assertEqual(result["side"], "BUY")
        self.assertEqual(result["entry_price"], 0.5)
        self.assertEqual(
            urlparse(request_get.call_args.args[0]).path,
            "/api/v1/positions",
        )

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_found_false_cases(
        self,
        request_get,
    ):
        scenarios = [
            self._positions_response([]),
            self._positions_response([
                {
                    "symbol": "ETHUSDTM",
                    "currentQty": "3",
                }
            ]),
            self._positions_response([
                {
                    "symbol": "XRPUSDTM",
                    "currentQty": "0",
                }
            ]),
        ]
        client = self._kucoin_client()

        for data in scenarios:
            with self.subTest(data=data):
                self._mock_position_get(request_get, data)

                result = client.get_current_position("xrpUSDT")

                self.assertTrue(result["success"])
                self.assertFalse(result["found"])
                self.assertEqual(result["symbol"], "XRPUSDTM")
                self.assertEqual(result["exchange_symbol"], "XRPUSDTM")
                self.assertIsNone(result["side"])
                self.assertEqual(result["quantity"], 0.0)
                self.assertEqual(result["signed_quantity"], 0.0)
                self.assertIsNone(result["error_code"])
                self.assertIsNone(result["error"])
                self.assertEqual(
                    urlparse(request_get.call_args.args[0]).path,
                    "/api/v1/positions",
                )
                self.assertEqual(request_get.call_args.kwargs["timeout"], 10)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_normalizes_quantities(
        self,
        request_get,
    ):
        cases = [
            (2, "long", 2.0, 2.0),
            (2.5, "long", 2.5, 2.5),
            ("3.5", "long", 3.5, 3.5),
            (-2, "short", 2.0, -2.0),
            ("-3", "short", 3.0, -3.0),
        ]
        client = self._kucoin_client()

        for raw_qty, side, quantity, signed_quantity in cases:
            with self.subTest(raw_qty=raw_qty):
                self._mock_position_get(
                    request_get,
                    self._positions_response([
                        {
                            "symbol": "XRPUSDTM",
                            "currentQty": raw_qty,
                            "avgEntryPrice": "0.5",
                        }
                    ]),
                )

                result = client.get_current_position("XRPUSDT")

                self.assertTrue(result["success"])
                self.assertTrue(result["found"])
                self.assertEqual(result["side"], side)
                self.assertEqual(result["quantity"], quantity)
                self.assertEqual(result["signed_quantity"], signed_quantity)
                self.assertEqual(result["raw_quantity"], raw_qty)
                self.assertEqual(result["entry_price"], 0.5)

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_rejects_malformed_wrappers(
        self,
        request_get,
    ):
        cases = [
            {"code": "200000", "data": None},
            {"code": "200000", "data": {}},
            {"code": "200000"},
            {"data": []},
            [],
            {"code": "200000", "data": ["bad-item"]},
            {"code": "200000", "data": [{"currentQty": "1"}]},
            {"code": "200000", "data": [{"symbol": None, "currentQty": "1"}]},
            {"code": "200000", "data": [{"symbol": "   ", "currentQty": "1"}]},
            {"code": "200000", "data": [{"symbol": "XRPUSDTM"}]},
        ]
        client = self._kucoin_client()

        for data in cases:
            with self.subTest(data=data):
                self._mock_position_get(request_get, data)

                result = client.get_current_position("XRPUSDT")

                self.assertFalse(result["success"])
                self.assertFalse(result["found"])
                self.assertEqual(result["error_code"], "MALFORMED_RESPONSE")

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_rejects_invalid_quantities(
        self,
        request_get,
    ):
        cases = [
            None,
            "",
            "not-a-number",
            True,
            "nan",
            "inf",
            "-inf",
            float("nan"),
            float("inf"),
        ]
        client = self._kucoin_client()

        for raw_qty in cases:
            with self.subTest(raw_qty=raw_qty):
                self._mock_position_get(
                    request_get,
                    self._positions_response([
                        {
                            "symbol": "XRPUSDTM",
                            "currentQty": raw_qty,
                        }
                    ]),
                )

                result = client.get_current_position("XRPUSDT")

                self.assertFalse(result["success"])
                self.assertFalse(result["found"])
                self.assertEqual(result["error_code"], "INVALID_QUANTITY")

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_rejects_duplicate_symbol_matches(
        self,
        request_get,
    ):
        cases = [
            ["0", "0"],
            ["0", "1"],
            ["1", "-2"],
        ]
        client = self._kucoin_client()

        for quantities in cases:
            with self.subTest(quantities=quantities):
                self._mock_position_get(
                    request_get,
                    self._positions_response([
                        {
                            "symbol": "XRPUSDTM",
                            "currentQty": quantities[0],
                        },
                        {
                            "symbol": "XRPUSDTM",
                            "currentQty": quantities[1],
                        },
                    ]),
                )

                result = client.get_current_position("XRPUSDT")

                self.assertFalse(result["success"])
                self.assertFalse(result["found"])
                self.assertEqual(result["error_code"], "MALFORMED_RESPONSE")

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_classifies_transport_errors(
        self,
        request_get,
    ):
        client = self._kucoin_client()

        request_get.side_effect = requests.exceptions.Timeout("timed out")
        result = client.get_current_position("XRPUSDT")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "TIMEOUT")

        request_get.side_effect = None

        for status_code in [401, 403]:
            with self.subTest(status_code=status_code):
                self._mock_position_get(
                    request_get,
                    {"code": "200000", "data": []},
                    status_code=status_code,
                )
                result = client.get_current_position("XRPUSDT")
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "AUTH_ERROR")

        self._mock_position_get(
            request_get,
            {"code": "200000", "data": []},
            status_code=500,
        )
        result = client.get_current_position("XRPUSDT")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "API_ERROR")

        request_get.side_effect = requests.exceptions.ConnectionError(
            "network down"
        )
        result = client.get_current_position("XRPUSDT")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "API_ERROR")

        request_get.side_effect = None
        response = self._mock_position_get(
            request_get,
            {"code": "200000", "data": []},
        )
        response.json.side_effect = ValueError("bad json")
        result = client.get_current_position("XRPUSDT")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "MALFORMED_RESPONSE")

        self._mock_position_get(
            request_get,
            {"code": "400100", "msg": "bad request"},
        )
        result = client.get_current_position("XRPUSDT")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "API_ERROR")

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_ignores_side_isopen_and_active(
        self,
        request_get,
    ):
        cases = [
            {
                "symbol": "XRPUSDTM",
                "currentQty": "2",
            },
            {
                "symbol": "XRPUSDTM",
                "currentQty": "-2",
                "side": "BUY",
                "positionSide": "LONG",
                "isOpen": False,
                "active": False,
            },
        ]
        client = self._kucoin_client()

        for item in cases:
            with self.subTest(item=item):
                self._mock_position_get(
                    request_get,
                    self._positions_response([item]),
                )

                result = client.get_current_position("XRPUSDT")

                self.assertTrue(result["success"])
                self.assertTrue(result["found"])
                self.assertEqual(
                    result["side"],
                    "long"
                    if float(item["currentQty"]) > 0
                    else "short",
                )

    @patch("backend.execution.kucoin_trade.requests.get")
    def test_kucoin_current_position_does_not_create_state(
        self,
        request_get,
    ):
        self._mock_position_get(
            request_get,
            self._positions_response([
                {
                    "symbol": "XRPUSDTM",
                    "currentQty": "1",
                }
            ]),
        )
        client = self._kucoin_client()

        result = client.get_current_position("XRPUSDT")

        self.assertTrue(result["success"])
        self.assertFalse(hasattr(client, "current_live_position"))
        self.assertFalse(hasattr(client, "cached_position"))
        self.assertFalse(hasattr(client, "kucoin_position_state"))

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_skips_when_no_position(
        self,
        request_post,
    ):
        client = self._kucoin_client()
        no_position = {
            "success": True,
            "found": False,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "error_code": None,
            "error": None,
        }

        with patch.object(
            client,
            "get_current_position",
            return_value=no_position,
        ) as get_current_position:
            result = client.flatten_current_position("XRPUSDT", timeout=7)

        self.assertTrue(result["success"])
        self.assertTrue(result["skipped"])
        self.assertTrue(result["confirmed"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["closed"])
        self.assertEqual(result["symbol"], "XRPUSDTM")
        self.assertIsNone(result["error_code"])
        request_post.assert_not_called()
        get_current_position.assert_called_once_with("XRPUSDT", timeout=7)

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_sends_reduce_only_market_close(
        self,
        request_post,
    ):
        cases = [
            ("long", "sell", 3.0, 3.0, "3"),
            ("short", "buy", 4.0, -4.0, "4"),
        ]

        for position_side, close_side, quantity, signed_quantity, size in cases:
            with self.subTest(position_side=position_side):
                client = self._kucoin_client()
                raw_order = {
                    "code": "200000",
                    "data": {
                        "orderId": "order-123",
                    },
                }
                self._mock_order_post(request_post, raw_order)
                initial_position = {
                    "success": True,
                    "found": True,
                    "symbol": "XRPUSDTM",
                    "exchange_symbol": "XRPUSDTM",
                    "side": position_side,
                    "quantity": quantity,
                    "signed_quantity": signed_quantity,
                    "raw_quantity": signed_quantity,
                    "error_code": None,
                    "error": None,
                }
                final_position = {
                    "success": True,
                    "found": False,
                    "symbol": "XRPUSDTM",
                    "exchange_symbol": "XRPUSDTM",
                    "error_code": None,
                    "error": None,
                }

                with patch.object(
                    client,
                    "get_current_position",
                    side_effect=[
                        initial_position,
                        final_position,
                    ],
                ) as get_current_position:
                    with patch.object(
                        client,
                        "_headers",
                        wraps=client._headers,
                    ) as headers:
                        result = client.flatten_current_position(
                            "XRPUSDT",
                            timeout=3,
                        )

                self.assertTrue(result["success"])
                self.assertFalse(result["skipped"])
                self.assertTrue(result["accepted"])
                self.assertTrue(result["confirmed"])
                self.assertTrue(result["closed"])
                self.assertEqual(result["side"], close_side)
                self.assertEqual(result["size"], int(size))
                self.assertEqual(result["order_id"], "order-123")
                self.assertEqual(result["raw_order"], raw_order)

                parsed_url = urlparse(request_post.call_args.args[0])
                body = json.loads(request_post.call_args.kwargs["data"])

                self.assertEqual(parsed_url.path, "/api/v1/orders")
                self.assertEqual(request_post.call_args.kwargs["timeout"], 3)
                self.assertEqual(body["symbol"], "XRPUSDTM")
                self.assertEqual(body["side"], close_side)
                self.assertEqual(body["type"], "market")
                self.assertEqual(body["size"], size)
                self.assertIs(body["reduceOnly"], True)
                self.assertEqual(body["leverage"], "10")
                self.assertEqual(body["marginMode"], "ISOLATED")
                self.assertEqual(
                    headers.call_args.args,
                    ("POST", "/api/v1/orders", request_post.call_args.kwargs["data"]),
                )
                get_current_position.assert_has_calls([
                    call("XRPUSDT", timeout=3),
                    call("XRPUSDTM", timeout=3),
                ])

                request_post.reset_mock()

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_rejects_invalid_contract_size(
        self,
        request_post,
    ):
        client = self._kucoin_client()
        initial_position = {
            "success": True,
            "found": True,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "side": "long",
            "quantity": 2.5,
            "signed_quantity": 2.5,
            "error_code": None,
            "error": None,
        }

        with patch.object(
            client,
            "get_current_position",
            return_value=initial_position,
        ):
            result = client.flatten_current_position("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["error_code"], "INVALID_QUANTITY")
        request_post.assert_not_called()

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_does_not_post_on_precheck_failure(
        self,
        request_post,
    ):
        client = self._kucoin_client()
        failed_position = {
            "success": False,
            "found": False,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "error_code": "API_ERROR",
            "error": "position unavailable",
        }

        with patch.object(
            client,
            "get_current_position",
            return_value=failed_position,
        ):
            result = client.flatten_current_position("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["error_code"], "API_ERROR")
        request_post.assert_not_called()

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_classifies_order_failures(
        self,
        request_post,
    ):
        initial_position = {
            "success": True,
            "found": True,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "side": "long",
            "quantity": 2.0,
            "signed_quantity": 2.0,
            "error_code": None,
            "error": None,
        }

        cases = [
            ("timeout", requests.exceptions.Timeout("timed out"), None, "TIMEOUT"),
            (
                "request-error",
                requests.exceptions.ConnectionError("network down"),
                None,
                "API_ERROR",
            ),
            ("401", None, ({"code": "200000", "data": {}}, 401), "AUTH_ERROR"),
            ("403", None, ({"code": "200000", "data": {}}, 403), "AUTH_ERROR"),
            ("500", None, ({"code": "200000", "data": {}}, 500), "API_ERROR"),
            ("api-code", None, ({"code": "400100", "msg": "bad"}, 200), "API_ERROR"),
            ("not-dict", None, ([], 200), "MALFORMED_RESPONSE"),
            ("missing-data", None, ({"code": "200000"}, 200), "MALFORMED_RESPONSE"),
            (
                "missing-order-id",
                None,
                ({"code": "200000", "data": {}}, 200),
                "MALFORMED_RESPONSE",
            ),
        ]

        for name, side_effect, response_data, error_code in cases:
            with self.subTest(name=name):
                client = self._kucoin_client()
                request_post.reset_mock()
                request_post.side_effect = side_effect

                if response_data:
                    data, status_code = response_data
                    self._mock_order_post(request_post, data, status_code)

                with patch.object(
                    client,
                    "get_current_position",
                    return_value=initial_position,
                ):
                    result = client.flatten_current_position("XRPUSDT")

                self.assertFalse(result["success"])
                self.assertFalse(result["accepted"])
                self.assertFalse(result["confirmed"])
                self.assertEqual(result["error_code"], error_code)

        client = self._kucoin_client()
        request_post.reset_mock()
        request_post.side_effect = None
        response = self._mock_order_post(
            request_post,
            {
                "code": "200000",
                "data": {
                    "orderId": "order-123",
                },
            },
        )
        response.json.side_effect = ValueError("bad json")

        with patch.object(
            client,
            "get_current_position",
            return_value=initial_position,
        ):
            result = client.flatten_current_position("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "MALFORMED_RESPONSE")

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_reports_post_check_failure(
        self,
        request_post,
    ):
        client = self._kucoin_client()
        self._mock_order_post(
            request_post,
            {
                "code": "200000",
                "data": {
                    "orderId": "order-123",
                },
            },
        )
        initial_position = {
            "success": True,
            "found": True,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "side": "long",
            "quantity": 2.0,
            "signed_quantity": 2.0,
            "error_code": None,
            "error": None,
        }
        failed_post_check = {
            "success": False,
            "found": False,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "error_code": "TIMEOUT",
            "error": "timed out",
        }

        with patch.object(
            client,
            "get_current_position",
            side_effect=[
                initial_position,
                failed_post_check,
            ],
        ):
            result = client.flatten_current_position("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertTrue(result["accepted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["error_code"], "POST_CHECK_TIMEOUT")

    @patch("backend.execution.kucoin_trade.requests.post")
    def test_kucoin_flatten_current_position_reports_position_remains(
        self,
        request_post,
    ):
        client = self._kucoin_client()
        self._mock_order_post(
            request_post,
            {
                "code": "200000",
                "data": {
                    "orderId": "order-123",
                },
            },
        )
        initial_position = {
            "success": True,
            "found": True,
            "symbol": "XRPUSDTM",
            "exchange_symbol": "XRPUSDTM",
            "side": "short",
            "quantity": 2.0,
            "signed_quantity": -2.0,
            "error_code": None,
            "error": None,
        }
        remaining_position = dict(initial_position)

        with patch.object(
            client,
            "get_current_position",
            side_effect=[
                initial_position,
                remaining_position,
            ],
        ):
            result = client.flatten_current_position("XRPUSDT")

        self.assertFalse(result["success"])
        self.assertTrue(result["accepted"])
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["closed"])
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["error_code"], "POSITION_REMAINS")

    def test_paper_mode_fetches_kucoin_real_account_read_only(self):
        bot = BotManager()
        bot.engine = FakeEngine()
        bot.config = {
            "mode": "paper",
            "dry_run": True,
            "symbol": "XRPUSDT",
            "exchange": "kucoin",
        }
        bot.symbol = "XRPUSDT"
        bot.exchange_name = "kucoin"
        bot.orderbook_symbol = "XRPUSDTM"
        bot._running = True

        with patch(
            "backend.bot_manager.bot_manager.KucoinTradeClient"
        ) as client_class:
            client_class.credentials_present.return_value = True
            client = client_class.return_value
            client.get_account_overview.return_value = {
                "source": "KUCOIN_FUTURES_READ_ONLY",
                "accountType": "KUCOIN_FUTURES",
                "balance": 222.0,
                "equity": 225.5,
                "availableBalance": 200.25,
                "permission": "READ_ONLY",
            }
            client.get_positions.return_value = None

            status = bot.get_status()
            cached = bot.get_status()

        response = StatusResponse(**status)
        account_runtime = response.accountRuntime

        self.assertEqual(response.selectedMode, "PAPER")
        self.assertEqual(response.executionMode, "SIMULATION")
        self.assertFalse(response.realOrderAllowed)
        self.assertTrue(response.dryRun)
        self.assertEqual(response.balance, 4321.25)
        self.assertEqual(
            account_runtime["paperAccount"]["balance"],
            4321.25,
        )
        self.assertEqual(
            account_runtime["paperAccount"]["source"],
            "PAPER_SIMULATION",
        )
        self.assertEqual(
            account_runtime["realAccount"]["exchange"],
            "kucoin",
        )
        self.assertEqual(
            account_runtime["realAccount"]["balance"],
            222.0,
        )
        self.assertEqual(
            account_runtime["realAccount"]["availableBalance"],
            200.25,
        )
        self.assertEqual(
            account_runtime["realAccount"]["positions"],
            [],
        )
        self.assertEqual(
            account_runtime["realAccount"]["positionSummary"],
            "NO_OPEN_POSITION",
        )
        self.assertEqual(
            response.balanceSource,
            "KUCOIN_FUTURES_READ_ONLY",
        )
        self.assertEqual(
            response.realPosition,
            [],
        )
        self.assertEqual(
            client.get_account_overview.call_count,
            1,
        )
        self.assertEqual(
            client.get_positions.call_count,
            1,
        )
        self.assertEqual(
            cached["accountRuntime"]["realAccount"]["generation"],
            status["accountRuntime"]["realAccount"]["generation"],
        )


if __name__ == "__main__":
    unittest.main()
