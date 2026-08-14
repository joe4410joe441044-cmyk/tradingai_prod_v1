# -*- coding: utf-8 -*-
"""Service layer tests for the read-only Market Recorder proxy."""

import asyncio
import unittest

from backend.config.recorder_proxy import RecorderProxyConfig
from backend.models.recorder_proxy import RecorderProxyDTOError
from backend.services.http.recorder_http_client import RecorderUpstreamError
from backend.services.recorder_proxy.service import (
    RecorderProxyConfigurationError,
    RecorderProxyDisabledError,
    RecorderProxyQueryError,
    RecorderProxyService,
    validate_archives_query,
)


def run(coro):
    return asyncio.run(coro)


def enabled_config():
    return RecorderProxyConfig(
        enabled=True,
        base_url="http://recorder.example.com",
        timeout_seconds=1.0,
        verify_tls=False,
    )


class FakeClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def get(self, endpoint_key, query_params=None):
        self.calls.append(("get", endpoint_key, query_params))
        return self.handler(endpoint_key, query_params)

    async def post(self, endpoint_key, body=None):
        self.calls.append(("post", endpoint_key, body))
        return self.handler(endpoint_key, body)


def ok_handler(endpoint_key, query_params):
    if endpoint_key == "health":
        return {"ok": True, "data": {"status": "ok", "uptime_seconds": 10}, "error": None}
    if endpoint_key == "status":
        return {
            "ok": True,
            "data": {
                "status": "running",
                "active_files": [],
                "subscribed_streams": ["trades"],
            },
            "error": None,
        }
    if endpoint_key == "storage":
        return {"ok": True, "data": {"filesystem": "/x"}, "error": None}
    return {
        "ok": True,
        "data": {"entries": [], "page": 1, "page_size": 10, "total_count": 0, "total_pages": 0},
        "error": None,
    }


class RecorderProxyServiceTests(unittest.TestCase):
    def test_disabled_fails_closed(self):
        service = RecorderProxyService(
            config=RecorderProxyConfig(
                enabled=False,
                base_url="http://recorder.example.com",
                timeout_seconds=1.0,
                verify_tls=True,
            )
        )
        with self.assertRaises(RecorderProxyDisabledError):
            run(service.get_health())

    def test_missing_base_url_fails_closed(self):
        service = RecorderProxyService(
            config=RecorderProxyConfig(
                enabled=True,
                base_url="",
                timeout_seconds=1.0,
                verify_tls=True,
            )
        )
        with self.assertRaises(RecorderProxyConfigurationError):
            run(service.get_health())

    def test_health_success(self):
        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(ok_handler)
        )
        result = run(service.get_health())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "ok")

    def test_status_success(self):
        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(ok_handler)
        )
        result = run(service.get_status())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "running")

    def test_storage_success(self):
        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(ok_handler)
        )
        result = run(service.get_storage())
        self.assertEqual(result["data"]["filesystem"], "/x")

    def test_archives_success(self):
        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(ok_handler)
        )
        result = run(
            service.get_archives({"page": "1", "page_size": "10", "sort": "start_time"})
        )
        self.assertEqual(result["data"]["entries"], [])

    def test_archives_unknown_query_dropped(self):
        client = FakeClient(ok_handler)
        service = RecorderProxyService(config=enabled_config(), client=client)
        run(service.get_archives({"page": "1", "unknown_param": "drop_me"}))
        _, endpoint, params = client.calls[0]
        self.assertNotIn("unknown_param", params)
        self.assertEqual(params, {"page": "1"})

    def test_archives_validates_page(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"page": "0"}))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"page": "-1"}))

    def test_archives_validates_page_size(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"page_size": "201"}))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"page_size": "0"}))

    def test_archives_validates_sort_allowlist(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"sort": "id"}))
        result = run(
            service.get_archives({"sort": "record_count", "order": "desc"})
        )
        self.assertTrue(result["ok"])

    def test_archives_validates_order(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"order": "sideways"}))

    def test_archives_validates_downloadable(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"downloadable": "yes"}))
        result = run(service.get_archives({"downloadable": "true"}))
        self.assertTrue(result["ok"])

    def test_archives_validates_from_to_iso_and_order(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_archives({"from": "not-a-date"}))
        with self.assertRaises(RecorderProxyQueryError):
            run(
                service.get_archives(
                    {"from": "2026-08-01T00:00:00Z", "to": "2026-07-01T00:00:00Z"}
                )
            )
        result = run(
            service.get_archives(
                {"from": "2026-07-01T00:00:00Z", "to": "2026-08-01T00:00:00Z"}
            )
        )
        self.assertTrue(result["ok"])

    def test_health_rejects_any_query(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_health({"page": "1"}))

    def test_status_rejects_any_query(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_status({"page": "1"}))

    def test_storage_rejects_any_query(self):
        service = RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        with self.assertRaises(RecorderProxyQueryError):
            run(service.get_storage({"any": "param"}))

    def test_invalid_upstream_envelope_fails_closed(self):
        def handler(endpoint_key, query_params):
            return {"ok": False, "data": None, "error": "boom"}

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        with self.assertRaises(RecorderProxyDTOError) as error:
            run(service.get_health())
        self.assertEqual(error.exception.code, "market_recorder_upstream_rejected")

    def test_invalid_dto_fails_closed(self):
        def handler(endpoint_key, query_params):
            return {"ok": True, "data": {"unexpected": "shape"}, "error": None}

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        with self.assertRaises(RecorderProxyDTOError):
            run(service.get_health())

    def test_upstream_error_propagates(self):
        def handler(endpoint_key, query_params):
            raise RecorderUpstreamError("market_recorder_upstream_timeout", retryable=True)

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        with self.assertRaises(RecorderUpstreamError) as error:
            run(service.get_status())
        self.assertEqual(error.exception.code, "market_recorder_upstream_timeout")

    def test_validate_archives_query_known_keys(self):
        validated = validate_archives_query(
            {
                "page": "2",
                "page_size": "50",
                "stream": "btcusdt@trade",
                "symbol": "BTCUSDT",
                "verification_status": "completed",
                "downloadable": "false",
                "sort": "end_time",
                "order": "desc",
            }
        )
        self.assertEqual(validated["page"], "2")
        self.assertEqual(validated["page_size"], "50")
        self.assertEqual(validated["order"], "desc")

    def test_storage_runtime_bytes_propagates(self):
        def handler(endpoint_key, query_params):
            return {
                "ok": True,
                "data": {
                    "filesystem": "/x",
                    "runtime_bytes": 524288000,
                },
                "error": None,
            }

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        result = run(service.get_storage())
        self.assertEqual(result["data"]["filesystem"], "/x")
        self.assertEqual(result["data"]["runtime_bytes"], 524288000)

    def test_storage_runtime_bytes_missing_still_ok(self):
        def handler(endpoint_key, query_params):
            return {
                "ok": True,
                "data": {"filesystem": "/x"},
                "error": None,
            }

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        result = run(service.get_storage())
        self.assertEqual(result["data"]["filesystem"], "/x")
        self.assertIsNone(result["data"].get("runtime_bytes"))

    def test_storage_runtime_bytes_zero_propagates(self):
        def handler(endpoint_key, query_params):
            return {
                "ok": True,
                "data": {
                    "filesystem": "/x",
                    "runtime_bytes": 0,
                },
                "error": None,
            }

        service = RecorderProxyService(
            config=enabled_config(), client=FakeClient(handler)
        )
        result = run(service.get_storage())
        self.assertEqual(result["data"]["runtime_bytes"], 0)


class RecorderProxyControlServiceTests(unittest.TestCase):
    def test_start_state_machine_dry_run_response(self):
        upstream = {
            "operation_id": "start-dry-1",
            "operation": "start",
            "result": "dry_run",
            "previous_state": "idle",
            "current_state": "idle",
            "requested_at": "2026-08-09T01:00:00Z",
            "completed_at": "2026-08-09T01:00:01Z",
            "plan": {"action": "start", "mutates": False},
        }
        service = RecorderProxyService(
            config=enabled_config(),
            client=FakeClient(lambda endpoint_key, body: {
                "ok": True, "data": upstream, "error": None,
            }),
        )

        result = run(service.start(dry_run=True))

        self.assertEqual(result["data"], {"status": None, **upstream,
            "event_count": None, "message": None})

    def test_stop_state_machine_dry_run_response(self):
        upstream = {
            "operation_id": "stop-dry-1",
            "operation": "stop",
            "result": "dry_run",
            "previous_state": "running",
            "current_state": "running",
            "requested_at": "2026-08-09T01:00:00Z",
            "completed_at": "2026-08-09T01:00:01Z",
            "plan": {"action": "stop", "mutates": False},
        }
        service = RecorderProxyService(
            config=enabled_config(),
            client=FakeClient(lambda endpoint_key, body: {
                "ok": True, "data": upstream, "error": None,
            }),
        )

        result = run(service.stop(dry_run=True))

        self.assertEqual(result["data"]["operation_id"], "stop-dry-1")
        self.assertEqual(result["data"]["plan"], upstream["plan"])

    def test_control_success_envelope_requires_null_error_member(self):
        service = RecorderProxyService(
            config=enabled_config(),
            client=FakeClient(lambda endpoint_key, body: {
                "ok": True,
                "data": {"status": "dry_run_ok"},
            }),
        )
        with self.assertRaises(RecorderProxyDTOError):
            run(service.start(dry_run=True))

    def test_start_dry_run(self):
        def handler(endpoint_key, body):
            self.assertEqual(endpoint_key, "start")
            self.assertEqual(body["dry_run"], True)
            return {
                "ok": True,
                "data": {"status": "dry_run_ok", "current_state": "idle", "plan": "would_start"},
                "error": None,
            }

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        result = run(service.start(dry_run=True))
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "dry_run_ok")

    def test_start_live(self):
        def handler(endpoint_key, body):
            self.assertEqual(body, {"dry_run": False})
            return {
                "ok": True,
                "data": {"status": "started", "current_state": "running", "event_count": 0},
                "error": None,
            }

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        result = run(service.start())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "started")

    def test_stop_dry_run(self):
        def handler(endpoint_key, body):
            self.assertEqual(endpoint_key, "stop")
            self.assertEqual(body["dry_run"], True)
            return {
                "ok": True,
                "data": {"status": "dry_run_ok", "current_state": "idle", "plan": "would_stop"},
                "error": None,
            }

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        result = run(service.stop(dry_run=True))
        self.assertTrue(result["ok"])

    def test_stop_live(self):
        def handler(endpoint_key, body):
            self.assertEqual(body, {"dry_run": False})
            return {
                "ok": True,
                "data": {"status": "stopped", "current_state": "idle", "event_count": 42},
                "error": None,
            }

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        result = run(service.stop())
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["event_count"], 42)

    def test_control_disabled_fails_closed(self):
        service = RecorderProxyService(
            config=RecorderProxyConfig(
                enabled=False,
                base_url="http://recorder.example.com",
                timeout_seconds=1.0,
                verify_tls=True,
            )
        )
        with self.assertRaises(RecorderProxyDisabledError):
            run(service.start())

    def test_control_upstream_error_mapped(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError(
                "market_recorder_upstream_rejected",
                retryable=False,
                status_code=409,
            )

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        with self.assertRaises(RecorderUpstreamError) as error:
            run(service.start())
        self.assertEqual(error.exception.code, "market_recorder_upstream_conflict")

    def test_control_invalid_envelope_fails(self):
        def handler(endpoint_key, body):
            return {"ok": False, "data": None, "error": "boom"}

        service = RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        with self.assertRaises(RecorderProxyDTOError) as error:
            run(service.start())
        self.assertEqual(error.exception.code, "market_recorder_upstream_rejected")


if __name__ == "__main__":
    unittest.main()
