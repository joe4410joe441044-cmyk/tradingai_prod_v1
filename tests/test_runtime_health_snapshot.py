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
            "ws_connected": True,
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

    def test_hold_cycle_is_healthy_and_reached_loops_are_running(self):
        snapshot = self._active_snapshot()

        self.assertEqual(snapshot["health"], "HEALTHY")
        self.assertEqual(snapshot["pipelineStatus"], "OK")
        self.assertTrue(snapshot["engineAvailable"])
        self.assertTrue(snapshot["executionEnabled"])
        self.assertFalse(snapshot["executionAllowed"])
        self.assertEqual(snapshot["executionReason"], "AI_HOLD")
        self.assertEqual(snapshot["loops"]["strategy-loop"], "RUNNING")
        self.assertEqual(snapshot["loops"]["ai-loop"], "RUNNING")
        self.assertEqual(snapshot["loops"]["governance-loop"], "RUNNING")
        self.assertEqual(snapshot["loops"]["execution-queue"], "RUNNING")
        self.assertEqual(snapshot["stages"]["execution-runtime"]["status"], "OK")
        self.assertEqual(
            snapshot["stages"]["execution-governance"]["status"],
            "IDLE",
        )
        self.assertEqual(snapshot["stages"]["execution-engine"]["status"], "IDLE")
        self.assertEqual(len(snapshot["timeline"]), 3)
        self.assertEqual(snapshot["timeline"][-1]["source"], "Execution Runtime")

    def test_runtime_exception_is_critical(self):
        snapshot = self._active_snapshot(runtime_healthy=False)

        self.assertEqual(snapshot["health"], "CRITICAL")
        self.assertFalse(snapshot["runtimeHealthy"])

    def test_stopped_runtime_does_not_reuse_previous_cycle_as_running(self):
        snapshot = self._active_snapshot(
            running=False,
            market_stale=True,
            ws_connected=False,
            engine_available=False,
        )

        self.assertEqual(snapshot["pipelineStatus"], "WAIT")
        self.assertEqual(snapshot["loops"]["strategy-loop"], "WAIT")
        self.assertEqual(snapshot["stages"]["strategy-plugin"]["status"], "WAIT")
        self.assertEqual(snapshot["timeline"], [])


if __name__ == "__main__":
    unittest.main()
