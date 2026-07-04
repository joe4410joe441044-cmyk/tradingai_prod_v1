import unittest

from backend.runtime.runtime_health_snapshot import (
    build_runtime_health_snapshot,
)


class RuntimeHealthSnapshotTest(unittest.TestCase):

    @staticmethod
    def _active_snapshot(**overrides):
        runtime_result = {
            "valid": False,
            "runtimeAdapterReached": True,
            "runtimeStateReached": True,
            "strategyRuntimeReached": True,
            "strategyOutput": {
                "strategy": {
                    "direction": "SHORT",
                    "executionAllowed": False,
                },
            },
            "aiRuntimeReached": True,
            "aiDecision": "HOLD",
            "governanceRuntimeReached": True,
            "governanceDecision": "BLOCK",
            "governanceAllowed": False,
            "governanceBlockedReason": "AI_HOLD",
            "executionRuntimeReached": True,
            "executionGovernanceReached": False,
            "signalAdapterReached": False,
            "handoffAttempted": False,
            "handoffExecuted": False,
            "runtime": {
                "executionAllowed": False,
                "reason": "AI_HOLD",
            },
            "runtimeStageTrace": {
                "trading-runtime": {
                    "reached": True,
                    "status": "ACTIVE",
                    "timestamp": 1_700_000_000.0,
                },
                "strategy-plugin": {
                    "reached": True,
                    "status": "OK",
                    "timestamp": 1_700_000_000.1,
                },
                "execution-runtime": {
                    "reached": True,
                    "status": "OK",
                    "reason": "AI_HOLD",
                    "timestamp": 1_700_000_000.2,
                },
            },
        }
        runtime_result.update(overrides.pop("runtime_result", {}))
        values = {
            "running": True,
            "market_stale": False,
            "exchange_ws_connected": True,
            "browser_ws_connected": True,
            "browser_ws_clients": 1,
            "engine_available": True,
            "runtime_healthy": True,
            "runtime_result": runtime_result,
            "runtime_trace": {
                "ws_receive": {"ok": True},
                "callback_fire": {"ok": True},
                "bot_update": {"ok": True},
                "status_api": {"ok": True},
            },
            "runtime_metrics": {
                "last_ws_message": 1_700_000_000.0,
                "last_callback": 1_700_000_000.0,
                "last_bot_update": 1_700_000_000.2,
            },
            "governance_state": {
                "execution_enabled": True,
                "emergency_stop": False,
            },
            "snapshot_timestamp": 1_700_000_001.0,
        }
        values.update(overrides)
        return build_runtime_health_snapshot(**values)

    def test_hold_cycle_is_healthy_and_reached_stages_are_explicit(self):
        snapshot = self._active_snapshot()

        self.assertEqual(snapshot["health"], "HEALTHY")
        self.assertEqual(snapshot["pipelineStatus"], "OK")
        self.assertTrue(snapshot["engineAvailable"])
        self.assertTrue(snapshot["executionEnabled"])
        self.assertFalse(snapshot["executionAllowed"])
        self.assertEqual(snapshot["executionReason"], "AI_HOLD")
        self.assertEqual(snapshot["schemaVersion"], 2)
        self.assertEqual(snapshot["bot"]["status"], "RUNNING")
        self.assertEqual(snapshot["executionAuthority"]["status"], "ENABLED")
        self.assertTrue(snapshot["executionAuthority"]["enabled"])
        self.assertEqual(snapshot["browserWebSocket"]["status"], "LIVE")
        self.assertEqual(snapshot["exchangeWebSocket"]["status"], "LIVE")
        self.assertEqual(snapshot["runtimeEngine"]["status"], "ACTIVE")
        self.assertEqual(snapshot["tradingAction"]["status"], "IDLE_BY_AI_HOLD")
        self.assertEqual(
            snapshot["executionEngine"]["status"],
            "ENABLED_IDLE_BY_AI_HOLD",
        )
        self.assertIsNone(snapshot["blockingReason"])
        self.assertEqual(snapshot["loops"]["strategy-loop"], "REACHED")
        self.assertEqual(snapshot["loops"]["ai-loop"], "EVALUATED")
        self.assertEqual(snapshot["loops"]["governance-loop"], "EVALUATED")
        self.assertEqual(snapshot["loops"]["execution-queue"], "REACHED")
        self.assertEqual(snapshot["stages"]["execution-runtime"]["status"], "IDLE")
        self.assertEqual(
            snapshot["stages"]["execution-governance"]["status"],
            "IDLE",
        )
        self.assertEqual(snapshot["stages"]["execution-engine"]["status"], "IDLE")
        self.assertEqual(len(snapshot["timeline"]), 3)
        self.assertEqual(snapshot["timeline"][-1]["source"], "Execution Runtime")
        self.assertEqual(snapshot["timeline"][-1]["state"], "IDLE")
        self.assertEqual(snapshot["timeline"][-1]["reason"], "AI_HOLD")

    def test_runtime_exception_is_critical(self):
        snapshot = self._active_snapshot(runtime_healthy=False)

        self.assertEqual(snapshot["health"], "CRITICAL")
        self.assertFalse(snapshot["runtimeHealthy"])
        self.assertEqual(snapshot["blockingReason"], "RUNTIME_EXCEPTION")

    def test_browser_and_exchange_websockets_are_not_mixed(self):
        browser_down = self._active_snapshot(browser_ws_connected=False)
        exchange_down = self._active_snapshot(exchange_ws_connected=False)

        self.assertEqual(
            browser_down["blockingReason"],
            "BROWSER_WS_DISCONNECTED",
        )
        self.assertEqual(browser_down["exchangeWebSocket"]["status"], "LIVE")
        self.assertEqual(exchange_down["browserWebSocket"]["status"], "LIVE")
        self.assertEqual(
            exchange_down["blockingReason"],
            "EXCHANGE_WS_DISCONNECTED",
        )

    def test_stage_inspector_metadata_is_backend_owned(self):
        snapshot = self._active_snapshot()
        stage = snapshot["stages"]["trading-runtime"]

        self.assertEqual(stage["name"], "TradingRuntime")
        self.assertEqual(stage["backendFile"], "backend/main.py")
        self.assertEqual(
            stage["functionName"],
            "TradingRuntime.process_runtime",
        )
        self.assertIn("output", stage)

    def test_stopped_runtime_does_not_reuse_previous_cycle_as_running(self):
        snapshot = self._active_snapshot(
            running=False,
            market_stale=True,
            exchange_ws_connected=False,
            browser_ws_connected=False,
            # STOPPING can briefly overlap engine teardown; lifecycle state
            # must still make current execution availability false.
            engine_available=True,
        )

        self.assertEqual(snapshot["health"], "HEALTHY")
        self.assertIsNone(snapshot["blockingReason"])
        self.assertEqual(snapshot["pipelineStatus"], "SUSPENDED_BY_BOT_STOP")
        self.assertEqual(
            snapshot["loops"]["strategy-loop"],
            "SUSPENDED_BY_BOT_STOP",
        )
        self.assertEqual(
            snapshot["stages"]["strategy-plugin"]["status"],
            "SUSPENDED_BY_BOT_STOP",
        )
        self.assertEqual(
            snapshot["exchangeWebSocket"]["status"],
            "DISCONNECTED_BY_BOT_STOP",
        )
        self.assertEqual(
            snapshot["executionEngine"]["status"],
            "UNAVAILABLE_BY_BOT_STOP",
        )
        self.assertEqual(snapshot["executionAuthority"]["status"], "ENABLED")
        self.assertTrue(snapshot["executionAuthority"]["enabled"])
        self.assertFalse(snapshot["executionEngine"]["available"])
        self.assertEqual(
            snapshot["tradingAction"]["status"],
            "NONE_BY_BOT_STOP",
        )
        self.assertEqual(snapshot["tradingAction"]["decision"], "N/A")
        self.assertEqual(snapshot["executionReason"], "BOT_STOPPED")
        self.assertEqual(snapshot["ai"]["decision"], "N/A")
        self.assertEqual(snapshot["ai"]["reason"], "BOT_STOPPED")
        self.assertEqual(
            snapshot["lastCompletedDecision"]["decision"],
            "HOLD",
        )
        self.assertEqual(snapshot["timeline"], [])

    def test_disabled_authority_is_not_reported_as_enabled_idle(self):
        snapshot = self._active_snapshot(
            governance_state={"execution_enabled": False},
        )

        self.assertFalse(snapshot["executionEngine"]["enabled"])
        self.assertEqual(
            snapshot["executionAuthority"]["status"],
            "DISABLED_BY_OPERATOR",
        )
        self.assertEqual(
            snapshot["executionEngine"]["status"],
            "DISABLED_BY_OPERATOR",
        )

    def test_execution_engine_status_matches_available_enabled_allowed(self):
        cases = (
            (
                "unavailable",
                {"engine_available": False},
                "UNAVAILABLE",
            ),
            (
                "ready",
                {"runtime_result": {
                    "aiDecision": "BUY",
                    "governanceAllowed": True,
                    "governanceBlockedReason": None,
                    "runtime": {"executionAllowed": True, "reason": None},
                }},
                "READY",
            ),
            (
                "blocked",
                {"runtime_result": {
                    "aiDecision": "BUY",
                    "governanceAllowed": False,
                    "governanceBlockedReason": "RISK_BLOCK",
                    "runtime": {
                        "executionAllowed": False,
                        "reason": "RISK_BLOCK",
                    },
                }},
                "ENABLED_IDLE_BLOCKED",
            ),
        )

        for name, overrides, expected in cases:
            with self.subTest(name=name):
                snapshot = self._active_snapshot(**overrides)
                self.assertEqual(snapshot["executionEngine"]["status"], expected)

    def test_lifecycle_revision_changes_status_fingerprint(self):
        first = self._active_snapshot(
            lifecycle_revision=10,
            lifecycle_state="RUNNING",
            cycle_id="1:5",
        )
        second = self._active_snapshot(
            lifecycle_revision=11,
            lifecycle_state="STOPPING",
            cycle_id="1:5",
        )

        self.assertNotEqual(
            first["statusFingerprint"],
            second["statusFingerprint"],
        )
        self.assertEqual(second["lifecycleRevision"], 11)
        self.assertEqual(second["lifecycle"]["state"], "STOPPING")
        self.assertEqual(second["cycleId"], "1:5")


if __name__ == "__main__":
    unittest.main()
