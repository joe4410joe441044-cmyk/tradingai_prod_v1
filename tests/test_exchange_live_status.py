import asyncio
import json
import unittest
from unittest.mock import Mock, call, patch
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import HTTPException

from backend.api.governance import (
    emergency_orchestrate,
    emergency_stop,
    emergency_unlock,
    router as governance_router,
    set_execution,
)
from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import BotManager
from backend.execution.kucoin_trade import KucoinTradeClient
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
    governance_state,
)


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

    def test_emergency_orchestrate_route_preserves_already_running(self):
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
            result = asyncio.run(emergency_orchestrate())

        self.assertIs(result, already_running_response)
        self.assertEqual(
            result["error_code"],
            "EMERGENCY_ALREADY_RUNNING",
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
    ):
        return {
            "operationId": "emg_20260714T123456Z_unlock",
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
    def _emergency_timeline_events():
        return [
            event
            for event in governance_state.get("emergency_timeline", [])
            if isinstance(event, dict)
        ]

    @staticmethod
    def _emergency_bot_with_engine(engine):
        bot = BotManager()
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
        engine.flatten_paper_position.return_value = flatten_result
        engine.build_live_readiness.return_value = {
            "realOrderAllowed": False,
        }
        return self._emergency_bot_with_engine(engine), engine

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
            bot = BotManager()
            bot._running = False
            bot.lifecycle_state = "STOPPED"

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
            governance_state["emergency_timeline"] = []

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

    def test_emergency_orchestrator_engine_unavailable(self):
        state_before = self._set_governance(
            execution_enabled=True,
            emergency_stop=False,
        )
        try:
            bot = BotManager()
            bot.engine = None

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
