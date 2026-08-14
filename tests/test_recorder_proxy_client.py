# -*- coding: utf-8 -*-
"""HTTP client tests for the Market Recorder proxy (GET + Control POST)."""

import asyncio
import unittest
from urllib.parse import urlsplit

import httpx

from backend.services.http.recorder_http_client import (
    RecorderReadOnlyClient,
    RecorderUpstreamError,
    _control_metadata,
)


def run(coro):
    return asyncio.run(coro)


def json_response(status=200, payload=None, content_type="application/json"):
    return httpx.Response(
        status,
        json=payload if payload is not None else {"ok": True, "data": {}},
        headers={"content-type": content_type},
    )


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return RecorderReadOnlyClient(
        base_url="http://recorder.example.com",
        timeout_seconds=1.0,
        verify_tls=False,
        transport=transport,
        **kwargs,
    )


class RecorderReadOnlyClientTests(unittest.TestCase):
    def test_health_success(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/health",
            )
            self.assertEqual(request.content, b"")
            return json_response(
                payload={"ok": True, "data": {"status": "ok"}, "error": None}
            )

        result = run(make_client(handler).get("health"))
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["status"], "ok")

    def test_get_health_dedicated_method(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/health",
            )
            return json_response(
                payload={
                    "ok": True,
                    "data": {"status": "ok", "uptime_seconds": 42},
                    "error": None,
                }
            )

        result = run(make_client(handler).get_health())
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["status"], "ok")
        self.assertEqual(result["data"]["uptime_seconds"], 42)

    def test_get_health_only_get(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            return json_response(payload={"ok": True, "data": {"status": "ok"}})

        run(make_client(handler).get_health())

    def test_get_status_dedicated_method(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/status",
            )
            self.assertEqual(request.content, b"")
            return json_response(
                payload={
                    "ok": True,
                    "data": {"status": "running", "active_files": []},
                    "error": None,
                }
            )

        result = run(make_client(handler).get_status())
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["status"], "running")
        self.assertEqual(result["data"]["active_files"], [])

    def test_status_success(self):
        def handler(request):
            self.assertEqual(str(request.url).endswith("/api/recorder/status"), True)
            return json_response(payload={"ok": True, "data": {"status": "running"}})

        result = run(make_client(handler).get("status"))
        self.assertEqual(result["data"]["status"], "running")

    def test_get_storage_dedicated_method(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/storage",
            )
            self.assertEqual(request.content, b"")
            return json_response(
                payload={
                    "ok": True,
                    "data": {"filesystem": "/dev/sda1", "total_bytes": 536870912000},
                    "error": None,
                }
            )

        result = run(make_client(handler).get_storage())
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["filesystem"], "/dev/sda1")
        self.assertEqual(result["data"]["total_bytes"], 536870912000)

    def test_get_storage_only_get(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            return json_response(
                payload={"ok": True, "data": {"filesystem": "/x"}}
            )

        run(make_client(handler).get_storage())

    def test_storage_success(self):
        def handler(request):
            self.assertEqual(str(request.url).endswith("/api/recorder/storage"), True)
            return json_response(payload={"ok": True, "data": {"filesystem": "/x"}})

        result = run(make_client(handler).get("storage"))
        self.assertEqual(result["data"]["filesystem"], "/x")

    def test_archives_success(self):
        def handler(request):
            self.assertEqual(
                urlsplit(str(request.url)).path,
                "/api/recorder/archives",
            )
            self.assertIn("page=1", str(request.url))
            self.assertIn("page_size=10", str(request.url))
            return json_response(
                payload={"ok": True, "data": {"entries": [], "page": 1}}
            )

        result = run(
            make_client(handler).get("archives", query_params={"page": "1", "page_size": "10"})
        )
        self.assertEqual(result["ok"], True)

    def test_get_archives_dedicated_method(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                str(request.url).split("?")[0],
                "http://recorder.example.com/api/recorder/archives",
            )
            self.assertEqual(request.content, b"")
            self.assertIn("page=2", str(request.url))
            self.assertIn("page_size=50", str(request.url))
            self.assertIn("sort=start_time", str(request.url))
            return json_response(
                payload={
                    "ok": True,
                    "data": {"entries": [], "page": 2, "page_size": 50, "total_count": 0, "total_pages": 0},
                    "error": None,
                }
            )

        result = run(
            make_client(handler).get_archives(
                {"page": "2", "page_size": "50", "sort": "start_time"}
            )
        )
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["page"], 2)

    def test_get_archives_only_get(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            return json_response(payload={"ok": True, "data": {"entries": []}})

        run(make_client(handler).get_archives())

    def test_upstream_4xx_rejected(self):
        def handler(request):
            return json_response(404, {"ok": False, "error": "not_found"})

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_rejected")
        self.assertFalse(error.exception.retryable)
        self.assertEqual(error.exception.status_code, 404)

    def test_upstream_5xx_unavailable(self):
        def handler(request):
            return json_response(500, {"ok": False, "error": "boom"})

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_unavailable")
        self.assertTrue(error.exception.retryable)

    def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out")

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_timeout")
        self.assertTrue(error.exception.retryable)

    def test_connection_failure(self):
        def handler(request):
            raise httpx.ConnectError("connect failed")

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_unavailable")
        self.assertTrue(error.exception.retryable)

    def test_invalid_json(self):
        def handler(request):
            return httpx.Response(
                200,
                content=b"not json {{{",
                headers={"content-type": "application/json"},
            )

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(
            error.exception.code, "market_recorder_upstream_invalid_response"
        )
        self.assertFalse(error.exception.retryable)

    def test_invalid_content_type(self):
        def handler(request):
            return httpx.Response(
                200, json={"ok": True}, headers={"content-type": "text/html"}
            )

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(
            error.exception.code, "market_recorder_upstream_invalid_response"
        )

    def test_redirect_rejected(self):
        def handler(request):
            return httpx.Response(
                302, headers={"location": "http://evil.example.com"}
            )

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(
            error.exception.code, "market_recorder_upstream_protocol_error"
        )
        self.assertFalse(error.exception.retryable)

    def test_response_size_limit(self):
        def handler(request):
            return httpx.Response(
                200,
                content=b"{}",
                headers={"content-type": "application/json", "content-length": "99999999"},
            )

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).get("health"))
        self.assertEqual(
            error.exception.code, "market_recorder_upstream_invalid_response"
        )

    def test_get_only_method(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            return json_response(payload={"ok": True, "data": {}})

        run(make_client(handler).get("health"))

    def test_no_cookies_credentials(self):
        def handler(request):
            self.assertEqual(request.headers.get("cookie"), None)
            self.assertEqual(request.headers.get("authorization"), None)
            self.assertEqual(request.headers.get("host"), "recorder.example.com")
            return json_response(payload={"ok": True, "data": {}})

        run(make_client(handler).get("health"))

    def test_query_and_fragment_injected_into_base_url_rejected(self):
        with self.assertRaises(RecorderUpstreamError) as error:
            run(
                RecorderReadOnlyClient(
                    base_url="http://recorder.example.com?target=evil",
                    transport=httpx.MockTransport(lambda r: json_response()),
                ).get("health")
            )
        self.assertEqual(
            error.exception.code, "market_recorder_proxy_configuration_error"
        )

    def test_no_retry_on_failure(self):
        calls = []

        def handler(request):
            calls.append(1)
            return json_response(500, {"ok": False})

        try:
            run(make_client(handler).get("health"))
        except RecorderUpstreamError:
            pass
        self.assertEqual(len(calls), 1)


class RecorderControlClientTests(unittest.TestCase):
    def test_post_start_success(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/start",
            )
            self.assertIn("request-id", request.headers)
            self.assertIn("request-nonce", request.headers)
            self.assertIn("request-timestamp", request.headers)
            import json as _json
            body = _json.loads(request.content)
            self.assertEqual(body["request_id"], request.headers["request-id"])
            return json_response(
                payload={"ok": True, "data": {"status": "started", "current_state": "running"}, "error": None}
            )

        result = run(make_client(handler).post("start"))
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["status"], "started")

    def test_post_stop_success(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                str(request.url),
                "http://recorder.example.com/api/recorder/stop",
            )
            return json_response(
                payload={"ok": True, "data": {"status": "stopped", "current_state": "idle"}, "error": None}
            )

        result = run(make_client(handler).post("stop"))
        self.assertEqual(result["data"]["status"], "stopped")

    def test_post_with_body(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            import json as _json
            body = _json.loads(request.content)
            self.assertTrue(body["dry_run"])
            self.assertEqual(
                set(body),
                {"dry_run", "request_id", "request_nonce", "request_timestamp"},
            )
            self.assertIn("request-id", request.headers)
            return json_response(payload={"ok": True, "data": {"status": "ok"}, "error": None})

        result = run(make_client(handler).post("start", body={"dry_run": True}))
        self.assertTrue(result["ok"])

    def test_post_body_contains_recorder_contract_metadata(self):
        def handler(request):
            import json as _json
            body = _json.loads(request.content)
            self.assertEqual(body["custom_field"], "value")
            self.assertEqual(
                set(body),
                {"custom_field", "request_id", "request_nonce", "request_timestamp"},
            )
            self.assertIn("request-id", request.headers)
            return json_response(payload={"ok": True, "data": {}})

        result = run(make_client(handler).post("start", body={"custom_field": "value"}))
        self.assertTrue(result["ok"])

    def test_post_upstream_4xx_rejected(self):
        def handler(request):
            return json_response(409, {"ok": False, "error": "already_running"})

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("start"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_rejected")
        self.assertEqual(error.exception.status_code, 409)

    def test_post_upstream_5xx_unavailable(self):
        def handler(request):
            return json_response(503, {"ok": False})

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("stop"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_unavailable")
        self.assertTrue(error.exception.retryable)

    def test_post_redirect_is_not_followed(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(307, headers={"location": "http://elsewhere.invalid/"})

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("start", body={"dry_run": True}))
        self.assertEqual(error.exception.code, "market_recorder_upstream_protocol_error")
        self.assertEqual(len(calls), 1)

    def test_post_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out")

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("start"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_timeout")

    def test_post_connection_failure(self):
        def handler(request):
            raise httpx.ConnectError("connect failed")

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("stop"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_unavailable")

    def test_post_no_retry_on_failure(self):
        calls = []

        def handler(request):
            calls.append(1)
            return json_response(500, {"ok": False})

        try:
            run(make_client(handler).post("start"))
        except RecorderUpstreamError:
            pass
        self.assertEqual(len(calls), 1)

    def test_post_invalid_json_response(self):
        def handler(request):
            return httpx.Response(
                200,
                content=b"not json",
                headers={"content-type": "application/json"},
            )

        with self.assertRaises(RecorderUpstreamError) as error:
            run(make_client(handler).post("start"))
        self.assertEqual(error.exception.code, "market_recorder_upstream_invalid_response")

    def test_control_metadata_headers_present(self):
        headers, body = _control_metadata()
        self.assertEqual(set(headers), {"Request-ID", "Request-Nonce", "Request-Timestamp"})
        self.assertTrue(all(isinstance(value, str) for value in headers.values()))
        self.assertEqual(headers["Request-ID"], body["request_id"])
        self.assertEqual(headers["Request-Nonce"], body["request_nonce"])
        self.assertEqual(headers["Request-Timestamp"], body["request_timestamp"])

    def test_control_metadata_headers_are_unique(self):
        h1, _ = _control_metadata()
        h2, _ = _control_metadata()
        self.assertNotEqual(h1["Request-ID"], h2["Request-ID"])
        self.assertNotEqual(h1["Request-Nonce"], h2["Request-Nonce"])

if __name__ == "__main__":
    unittest.main()
