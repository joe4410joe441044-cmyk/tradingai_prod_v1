# -*- coding: utf-8 -*-
"""Backend DTO validation tests for the read-only Market Recorder proxy."""

import unittest

from backend.models.recorder_proxy import (
    RecorderProxyDTOError,
    validate_archives_dto,
    validate_control_dto,
    validate_envelope,
    validate_health_dto,
    validate_status_dto,
    validate_storage_dto,
)


def health_payload():
    return {
        "status": "ok",
        "contract_version": "0.1.0",
        "uptime_seconds": 12345,
    }


def status_payload():
    return {
        "status": "running",
        "connection_state": "connected",
        "pid": 12345,
        "uptime_seconds": 5025,
        "subscribed_streams": ["trades", "orderbook", "ticker"],
        "messages_received": 1250000,
        "bytes_received": 250000000,
        "reconnect_count": 0,
        "sequence_anomaly_count": 0,
        "active_files": ["BTCUSDT-2026-07-31.jsonl.part"],
        "last_message_at": "2026-07-31T12:34:56Z",
        "last_error": None,
        "process_started_at": "2026-07-31T00:00:00Z",
        "observed_at": "2026-07-31T12:35:00Z",
    }


def storage_payload():
    return {
        "filesystem": "/dev/sda1",
        "total_bytes": 536870912000,
        "used_bytes": 251792850944,
        "free_bytes": 285078061056,
        "usage_percent": 46.9,
        "archive_bytes": 13244702720,
        "active_bytes": 5242880000,
        "manifest_bytes": 20971520,
        "quarantine_count": 0,
        "observed_at": "2026-07-31T12:35:00Z",
    }


def archives_payload():
    return {
        "entries": [
            {
                "id": "arch-001",
                "stream": "btcusdt@trade",
                "symbol": "BTCUSDT",
                "period": "2026-07-31",
                "start_time": "2026-07-31T00:00:00Z",
                "end_time": "2026-07-31T23:59:59Z",
                "record_count": 5000000,
                "compressed_bytes": 257589411,
                "uncompressed_bytes": 1048576000,
                "verification_status": "completed",
                "manifest_status": "complete",
                "downloadable": True,
                "deletion_eligible": True,
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
        "total_pages": 1,
    }


class RecorderProxyEnvelopeTests(unittest.TestCase):
    def test_valid_envelope_returns_data(self):
        data = validate_envelope({"ok": True, "data": {"x": 1}, "error": None})
        self.assertEqual(data, {"x": 1})

    def test_ok_false_rejected(self):
        with self.assertRaises(RecorderProxyDTOError) as error:
            validate_envelope({"ok": False, "data": None, "error": "boom"})
        self.assertEqual(error.exception.code, "market_recorder_upstream_rejected")

    def test_missing_data_rejected(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_envelope({"ok": True})

    def test_non_dict_envelope_rejected(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_envelope([])


class RecorderProxyHealthDTOTests(unittest.TestCase):
    def test_valid_health(self):
        result = validate_health_dto(health_payload())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["contract_version"], "0.1.0")
        self.assertEqual(result["uptime_seconds"], 12345)

    def test_health_rejects_missing_status(self):
        payload = health_payload()
        del payload["status"]
        with self.assertRaises(RecorderProxyDTOError):
            validate_health_dto(payload)

    def test_health_rejects_wrong_type(self):
        payload = health_payload()
        payload["uptime_seconds"] = "12345"
        with self.assertRaises(RecorderProxyDTOError):
            validate_health_dto(payload)


class RecorderProxyStatusDTOTests(unittest.TestCase):
    def test_valid_status(self):
        result = validate_status_dto(status_payload())
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["pid"], 12345)
        self.assertIsNone(result["last_error"])
        self.assertEqual(result["active_files"], ["BTCUSDT-2026-07-31.jsonl.part"])

    def test_status_rejects_missing_active_files(self):
        payload = status_payload()
        del payload["active_files"]
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_rejects_negative_number(self):
        payload = status_payload()
        payload["uptime_seconds"] = -5
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_rejects_bool_as_int(self):
        payload = status_payload()
        payload["pid"] = True
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_subscribed_streams_list_accepted(self):
        result = validate_status_dto(status_payload())
        self.assertEqual(result["subscribed_streams"], ["trades", "orderbook", "ticker"])

    def test_status_subscribed_streams_empty_list_accepted(self):
        payload = status_payload()
        payload["subscribed_streams"] = []
        result = validate_status_dto(payload)
        self.assertEqual(result["subscribed_streams"], [])

    def test_status_subscribed_streams_scalar_rejected(self):
        payload = status_payload()
        payload["subscribed_streams"] = 5
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_subscribed_streams_string_rejected(self):
        payload = status_payload()
        payload["subscribed_streams"] = "trades"
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_subscribed_streams_non_string_entry_rejected(self):
        payload = status_payload()
        payload["subscribed_streams"] = ["trades", 123]
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)

    def test_status_uptime_seconds_float_accepted(self):
        payload = status_payload()
        payload["uptime_seconds"] = 710278.135
        result = validate_status_dto(payload)
        self.assertEqual(result["uptime_seconds"], 710278.135)

    def test_status_uptime_seconds_integer_accepted(self):
        payload = status_payload()
        payload["uptime_seconds"] = 5025
        result = validate_status_dto(payload)
        self.assertEqual(result["uptime_seconds"], 5025)

    def test_status_uptime_seconds_missing_handling(self):
        payload = status_payload()
        del payload["uptime_seconds"]
        result = validate_status_dto(payload)
        self.assertIsNone(result["uptime_seconds"])

    def test_status_uptime_seconds_null_handling(self):
        payload = status_payload()
        payload["uptime_seconds"] = None
        result = validate_status_dto(payload)
        self.assertIsNone(result["uptime_seconds"])

    def test_status_uptime_seconds_negative_rejected(self):
        payload = status_payload()
        payload["uptime_seconds"] = -710278.135
        with self.assertRaises(RecorderProxyDTOError):
            validate_status_dto(payload)


class RecorderProxyStorageDTOTests(unittest.TestCase):
    def test_valid_storage(self):
        result = validate_storage_dto(storage_payload())
        self.assertEqual(result["total_bytes"], 536870912000)
        self.assertEqual(result["usage_percent"], 46.9)

    def test_storage_rejects_non_object(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto([])

    def test_storage_rejects_negative_total_bytes(self):
        payload = storage_payload()
        payload["total_bytes"] = -1
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_rejects_negative_usage_percent(self):
        payload = storage_payload()
        payload["usage_percent"] = -0.5
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_rejects_bool_as_total_bytes(self):
        payload = storage_payload()
        payload["total_bytes"] = True
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_rejects_string_as_used_bytes(self):
        payload = storage_payload()
        payload["used_bytes"] = "251792850944"
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_rejects_negative_quarantine_count(self):
        payload = storage_payload()
        payload["quarantine_count"] = -1
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_rejects_bool_as_quarantine_count(self):
        payload = storage_payload()
        payload["quarantine_count"] = False
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_allows_zero_values(self):
        payload = storage_payload()
        payload["total_bytes"] = 0
        payload["used_bytes"] = 0
        payload["free_bytes"] = 0
        payload["quarantine_count"] = 0
        result = validate_storage_dto(payload)
        self.assertEqual(result["total_bytes"], 0)
        self.assertEqual(result["quarantine_count"], 0)

    def test_storage_allows_none_fields(self):
        payload = {"filesystem": "/dev/sda1"}
        result = validate_storage_dto(payload)
        self.assertEqual(result["filesystem"], "/dev/sda1")
        self.assertIsNone(result["total_bytes"])
        self.assertIsNone(result["usage_percent"])

    def test_storage_runtime_bytes_present(self):
        payload = storage_payload()
        payload["runtime_bytes"] = 524288000
        result = validate_storage_dto(payload)
        self.assertEqual(result["runtime_bytes"], 524288000)

    def test_storage_runtime_bytes_zero(self):
        payload = storage_payload()
        payload["runtime_bytes"] = 0
        result = validate_storage_dto(payload)
        self.assertEqual(result["runtime_bytes"], 0)

    def test_storage_runtime_bytes_missing(self):
        result = validate_storage_dto(storage_payload())
        self.assertIsNone(result["runtime_bytes"])

    def test_storage_runtime_bytes_null(self):
        payload = storage_payload()
        payload["runtime_bytes"] = None
        result = validate_storage_dto(payload)
        self.assertIsNone(result["runtime_bytes"])

    def test_storage_runtime_bytes_rejects_negative(self):
        payload = storage_payload()
        payload["runtime_bytes"] = -100
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_runtime_bytes_rejects_string(self):
        payload = storage_payload()
        payload["runtime_bytes"] = "524288000"
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)

    def test_storage_runtime_bytes_rejects_bool(self):
        payload = storage_payload()
        payload["runtime_bytes"] = True
        with self.assertRaises(RecorderProxyDTOError):
            validate_storage_dto(payload)


class RecorderProxyArchivesDTOTests(unittest.TestCase):
    def test_valid_archives(self):
        result = validate_archives_dto(archives_payload())
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["entries"][0]["id"], "arch-001")
        self.assertEqual(result["entries"][0]["verification_status"], "completed")

    def test_archives_rejects_missing_entries(self):
        payload = archives_payload()
        del payload["entries"]
        with self.assertRaises(RecorderProxyDTOError):
            validate_archives_dto(payload)

    def test_archives_rejects_non_list_entries(self):
        payload = archives_payload()
        payload["entries"] = {}
        with self.assertRaises(RecorderProxyDTOError):
            validate_archives_dto(payload)

    def test_archives_rejects_invalid_entry(self):
        payload = archives_payload()
        payload["entries"] = [{"id": 123}]
        with self.assertRaises(RecorderProxyDTOError):
            validate_archives_dto(payload)

    def test_empty_entries_allowed(self):
        payload = archives_payload()
        payload["entries"] = []
        result = validate_archives_dto(payload)
        self.assertEqual(result["entries"], [])


class RecorderProxyControlDTOTests(unittest.TestCase):
    def test_state_machine_rejection_is_preserved(self):
        payload = {
            "operation_id": "op-123",
            "operation": "start",
            "result": "rejected",
            "previous_state": "running",
            "current_state": "running",
            "requested_at": "2026-08-09T01:02:03Z",
            "completed_at": "2026-08-09T01:02:04Z",
            "plan": {
                "error_code": "invalid_state_transition",
                "error_message": "already running",
            },
        }

        result = validate_control_dto(payload)

        self.assertEqual(result["operation_id"], "op-123")
        self.assertEqual(result["operation"], "start")
        self.assertEqual(result["result"], "rejected")
        self.assertEqual(result["previous_state"], "running")
        self.assertEqual(result["current_state"], "running")
        self.assertEqual(result["requested_at"], "2026-08-09T01:02:03Z")
        self.assertEqual(result["completed_at"], "2026-08-09T01:02:04Z")
        self.assertEqual(result["plan"], payload["plan"])

    def test_control_dto_rejects_structurally_unrelated_object(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_control_dto({"unrelated": "value"})

    def test_control_dto_rejects_wrong_plan_type(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_control_dto({
                "operation_id": "op-123",
                "operation": "stop",
                "result": "dry_run",
                "plan": [],
            })

    def test_valid_control_dto_started(self):
        result = validate_control_dto({
            "status": "started",
            "current_state": "running",
            "plan": "recording_started",
            "event_count": 0,
            "message": "Recording started successfully",
        })
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["current_state"], "running")
        self.assertEqual(result["event_count"], 0)

    def test_valid_control_dto_stopped(self):
        result = validate_control_dto({
            "status": "stopped",
            "current_state": "idle",
            "plan": "recording_stopped",
            "event_count": 42,
            "message": "Recording stopped",
        })
        self.assertEqual(result["event_count"], 42)

    def test_control_dto_minimal(self):
        result = validate_control_dto({"status": "started"})
        self.assertEqual(result["status"], "started")
        self.assertIsNone(result["event_count"])

    def test_control_dto_rejects_non_dict(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_control_dto([])

    def test_control_dto_rejects_negative_event_count(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_control_dto({"status": "started", "event_count": -1})

    def test_control_dto_rejects_bool_event_count(self):
        with self.assertRaises(RecorderProxyDTOError):
            validate_control_dto({"status": "started", "event_count": True})


if __name__ == "__main__":
    unittest.main()
