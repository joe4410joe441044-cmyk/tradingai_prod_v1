import math
import unittest

from backend.runtime.runtime_health_snapshot import (
    RUNTIME_SNAPSHOT_CLOCK_SKEW_TOLERANCE_SECONDS,
    build_runtime_health_snapshot,
)


PROJECTION_TIME = 1_700_000_001.0
SESSION_ID = 7
RUNTIME_INSTANCE_ID = "instance-1"
RUNTIME_ID = "feed-1"
EXPECTED_STRATEGY = {
    "direction": "SHORT",
    "executionAllowed": False,
    "suppressionReason": "ENTRY_THRESHOLD_NOT_MET",
}


def _runtime_result(*, captured_at=PROJECTION_TIME, authority_overrides=None):
    authority = {
        "sessionId": SESSION_ID,
        "runtimeInstanceId": RUNTIME_INSTANCE_ID,
        "runtimeId": RUNTIME_ID,
        "capturedAt": captured_at,
    }
    if authority_overrides:
        authority.update(authority_overrides)
    return {
        "runtimeSnapshotAuthority": authority,
        "strategyRuntimeReached": True,
        "strategyOutput": {"strategy": dict(EXPECTED_STRATEGY)},
        "governanceRuntimeReached": False,
        "governanceAllowed": None,
        "executionRuntimeReached": True,
        "executionGovernanceReached": False,
        "handoffAttempted": False,
        "handoffExecuted": False,
        "runtime": {
            "executionAllowed": False,
            "reason": "ENTRY_THRESHOLD_NOT_MET",
        },
    }


def _snapshot(runtime_result, **overrides):
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
            "last_ws_message": PROJECTION_TIME - 1.0,
            "last_callback": PROJECTION_TIME - 1.0,
            "last_bot_update": PROJECTION_TIME - 1.0,
        },
        "governance_state": {
            "execution_enabled": False,
            "emergency_stop": False,
        },
        # The loop metric can legitimately lag the completed result. It is an
        # identity/display timestamp, not the freshness reference clock.
        "snapshot_timestamp": PROJECTION_TIME - 1.0,
        "projection_timestamp": PROJECTION_TIME,
        "loop_state": "RUNNING",
        "session_id": SESSION_ID,
        "runtime_instance_id": RUNTIME_INSTANCE_ID,
        "active_runtime_id": RUNTIME_ID,
    }
    values.update(overrides)
    return build_runtime_health_snapshot(**values)


class RuntimeHealthSnapshotFreshnessRaceTest(unittest.TestCase):

    def assert_projected(self, snapshot):
        self.assertEqual(snapshot["states"]["strategy"], EXPECTED_STRATEGY)
        self.assertTrue(snapshot["strategy"]["reached"])
        self.assertNotIn("RUNTIME_SNAPSHOT_MISSING", snapshot["issues"])

    def assert_failed_closed(self, snapshot):
        self.assertEqual(snapshot["states"]["strategy"], {})
        self.assertFalse(snapshot["strategy"]["reached"])
        self.assertIn("RUNTIME_SNAPSHOT_MISSING", snapshot["issues"])
        self.assertFalse(snapshot["executionAllowed"])

    def test_small_negative_age_torn_read_remains_projected(self):
        result = _runtime_result(captured_at=PROJECTION_TIME + 0.25)
        self.assert_projected(_snapshot(result))

    def test_normal_small_positive_age_is_unchanged(self):
        result = _runtime_result(captured_at=PROJECTION_TIME - 0.25)
        self.assert_projected(_snapshot(result))

    def test_genuinely_stale_completed_result_fails_closed(self):
        result = _runtime_result(captured_at=PROJECTION_TIME - 5.01)
        self.assert_failed_closed(_snapshot(result))

    def test_missing_completed_result_fails_closed(self):
        self.assert_failed_closed(_snapshot(None))

    def test_missing_runtime_snapshot_authority_fails_closed(self):
        result = _runtime_result()
        result.pop("runtimeSnapshotAuthority")
        self.assert_failed_closed(_snapshot(result))

    def test_wrong_session_id_fails_closed(self):
        result = _runtime_result(authority_overrides={"sessionId": SESSION_ID - 1})
        self.assert_failed_closed(_snapshot(result))

    def test_wrong_runtime_instance_id_fails_closed(self):
        result = _runtime_result(
            authority_overrides={"runtimeInstanceId": "instance-old"},
        )
        self.assert_failed_closed(_snapshot(result))

    def test_wrong_runtime_id_fails_closed(self):
        result = _runtime_result(authority_overrides={"runtimeId": "feed-old"})
        self.assert_failed_closed(_snapshot(result))

    def test_malformed_or_non_finite_timestamp_fails_closed(self):
        for name, captured_at in (
            ("none", None),
            ("nan", math.nan),
            ("positive-infinity", math.inf),
            ("negative-infinity", -math.inf),
            ("non-numeric", "1700000001.0"),
            ("boolean", True),
        ):
            with self.subTest(name=name):
                self.assert_failed_closed(
                    _snapshot(_runtime_result(captured_at=captured_at)),
                )

    def test_clearly_invalid_future_snapshot_fails_closed(self):
        captured_at = (
            PROJECTION_TIME
            + RUNTIME_SNAPSHOT_CLOCK_SKEW_TOLERANCE_SECONDS
            + 0.01
        )
        self.assert_failed_closed(_snapshot(_runtime_result(captured_at=captured_at)))

    def test_strategy_projection_does_not_broaden_execution_authority(self):
        snapshot = _snapshot(_runtime_result(captured_at=PROJECTION_TIME + 0.25))
        self.assert_projected(snapshot)
        self.assertFalse(snapshot["executionEnabled"])
        self.assertFalse(snapshot["executionAllowed"])
        self.assertFalse(snapshot["executionAuthority"]["enabled"])
        self.assertEqual(
            snapshot["executionAuthority"]["status"],
            "DISABLED_BY_OPERATOR",
        )
        self.assertFalse(snapshot["governance"]["reached"])
        self.assertIsNone(snapshot["governance"]["allowed"])
        self.assertEqual(snapshot["loops"]["governance-loop"], "IDLE")
        self.assertFalse(snapshot["states"]["execution"]["handoffAttempted"])
        self.assertFalse(snapshot["states"]["execution"]["handoffExecuted"])
        for authority_key in (
            "realOrderAllowed",
            "armEnabled",
            "loopEnabled",
            "autoTradeEnabled",
        ):
            self.assertNotIn(authority_key, snapshot)

    def test_torn_read_that_previously_null_projected_is_consistent(self):
        result = _runtime_result(captured_at=PROJECTION_TIME + 0.25)
        for _ in range(5):
            snapshot = _snapshot(result)
            self.assertEqual(result["strategyOutput"]["strategy"], EXPECTED_STRATEGY)
            self.assert_projected(snapshot)


if __name__ == "__main__":
    unittest.main()
