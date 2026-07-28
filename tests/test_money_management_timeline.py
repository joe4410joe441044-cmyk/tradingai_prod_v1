import json
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.timeline import (
    MAX_HISTORY_LIMIT,
    METRIC_FIELDS,
    MoneyManagementTimelineEventType,
    MoneyManagementTimelineRecorder,
    MoneyManagementTimelineStore,
    TIMELINE_FILENAME,
)
from tests.test_money_management_loss_runtime_update_dispatcher import (
    NOW,
    metrics,
)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        self.value += timedelta(microseconds=1)
        return self.value


class TimelineStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.clock = Clock()

    def tearDown(self):
        self.temp.cleanup()

    def append(self, store, **overrides):
        values = {
            "event_type": MoneyManagementTimelineEventType.APPLICATION_STARTED,
            "timestamp": self.clock(),
            "source": "TEST",
            "state": "RUNNING",
        }
        values.update(overrides)
        return store.append(**values)

    def test_event_serialization_immutability_and_reason_order(self):
        store = MoneyManagementTimelineStore(self.directory)
        event = self.append(
            store,
            reason_codes=("WARNING_A", "BLOCK_B"),
            diagnostics=("DIAGNOSTIC_C",),
        )
        rendered = event.to_dict()

        self.assertEqual(rendered["sequence"], 1)
        self.assertEqual(
            rendered["reasonCodes"], ["WARNING_A", "BLOCK_B"]
        )
        self.assertTrue(rendered["timestamp"].endswith("Z"))
        self.assertEqual(set(rendered["metrics"]), set(METRIC_FIELDS))
        with self.assertRaises(FrozenInstanceError):
            event.sequence = 2

    def test_append_reload_corrupt_line_and_sequence_continuity(self):
        store = MoneyManagementTimelineStore(self.directory)
        self.append(store)
        target = self.directory / TIMELINE_FILENAME
        with target.open("a", encoding="utf-8") as stream:
            stream.write("{corrupt\n")

        restored = MoneyManagementTimelineStore(self.directory)
        event = self.append(
            restored,
            event_type=MoneyManagementTimelineEventType.RUNTIME_METRICS_UPDATED,
        )

        self.assertEqual(restored.corrupt_lines, 1)
        self.assertEqual(event.sequence, 2)
        self.assertEqual(len(restored.query().events), 2)

    def test_retention_keeps_latest_and_deduplicates_consecutive_events(self):
        store = MoneyManagementTimelineStore(self.directory, maximum_events=3)
        first = self.append(store)
        duplicate = self.append(store)
        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        for index in range(4):
            self.append(
                store,
                event_type=MoneyManagementTimelineEventType.RUNTIME_METRICS_UPDATED,
                state=f"STATE_{index}",
            )
        events = store.query(limit=3).events
        self.assertEqual([event.sequence for event in events], [5, 4, 3])
        restored = MoneyManagementTimelineStore(
            self.directory, maximum_events=3
        )
        self.assertEqual(len(restored.query(limit=3).events), 3)

    def test_query_cursor_filters_order_and_limits(self):
        store = MoneyManagementTimelineStore(self.directory)
        self.append(store, state="NORMAL")
        self.append(
            store,
            event_type=MoneyManagementTimelineEventType.LOSS_STATE_CHANGED,
            state="LOCKED",
        )
        self.append(
            store,
            event_type=MoneyManagementTimelineEventType.RUNTIME_METRICS_UPDATED,
            state="LOCKED",
        )

        page = store.query(limit=1, state="LOCKED")
        self.assertEqual(page.events[0].sequence, 3)
        self.assertTrue(page.has_more)
        next_page = store.query(limit=1, before=page.next_cursor)
        self.assertEqual(next_page.events[0].sequence, 2)
        filtered = store.query(
            event_type="LOSS_STATE_CHANGED", state="LOCKED"
        )
        self.assertEqual(len(filtered.events), 1)
        for invalid in (
            {"limit": 0},
            {"limit": MAX_HISTORY_LIMIT + 1},
            {"before": "../1"},
            {"event_type": "UNKNOWN"},
            {"state": ""},
        ):
            with self.assertRaises((TypeError, ValueError)):
                store.query(**invalid)

    def test_missing_empty_and_symlink_are_safe(self):
        store = MoneyManagementTimelineStore(self.directory)
        self.assertEqual(store.query().events, ())
        target = self.directory / TIMELINE_FILENAME
        target.symlink_to(self.directory / "elsewhere")
        with self.assertRaises(OSError):
            MoneyManagementTimelineStore(self.directory)


class TimelineRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MoneyManagementTimelineStore(Path(self.temp.name))
        self.clock = Clock()
        self.recorder = MoneyManagementTimelineRecorder(
            self.store, self.clock
        )
        self.config = build_default_money_management_config()

    def tearDown(self):
        self.temp.cleanup()

    def test_runtime_changes_diagnostics_lock_unlock_and_dedup(self):
        base = metrics(pending_order_count=0)
        self.recorder.record_runtime(base, self.config, "NORMAL")
        count = len(self.store.query(limit=100).events)
        self.recorder.record_runtime(base, self.config, "NORMAL")
        self.assertEqual(len(self.store.query(limit=100).events), count)

        changed = metrics(
            revision="9",
            open_exposure=Decimal("10"),
            position_count=1,
            position_side="LONG",
            current_risk_amount=Decimal("2"),
            pending_order_count=1,
        )
        self.recorder.record_runtime(
            changed,
            self.config,
            "LOCKED",
            ("CURRENT_POSITION_RISK_UNAVAILABLE",),
        )
        types = {
            event.event_type.value
            for event in self.store.query(limit=100).events
        }
        self.assertIn("RUNTIME_METRICS_UPDATED", types)
        self.assertIn("LOSS_STATE_CHANGED", types)
        self.assertIn("MONEY_MANAGEMENT_LOCKED", types)
        self.assertIn("EXPOSURE_STATE_CHANGED", types)
        self.assertIn("RISK_BUDGET_CHANGED", types)
        self.assertIn("POSITION_STATE_CHANGED", types)
        self.assertIn("DIAGNOSTIC_RAISED", types)
        runtime_event = next(
            event
            for event in self.store.query(limit=100).events
            if event.event_type
            is MoneyManagementTimelineEventType.RUNTIME_METRICS_UPDATED
            and event.metrics["openPositionState"] == "LONG"
        )
        self.assertEqual(runtime_event.metrics["currentRiskAmount"], "2")
        self.assertIsNone(runtime_event.metrics["reservedRiskAmount"])

        self.recorder.record_runtime(base, self.config, "NORMAL")
        types = [
            event.event_type.value
            for event in self.store.query(limit=100).events
        ]
        self.assertIn("MONEY_MANAGEMENT_UNLOCKED", types)
        self.assertIn("DIAGNOSTIC_CLEARED", types)


if __name__ == "__main__":
    unittest.main()
