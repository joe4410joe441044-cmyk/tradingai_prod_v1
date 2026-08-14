# -*- coding: utf-8 -*-
"""Route tests for the read-only Market Recorder proxy."""

import asyncio
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.recorder_proxy import create_recorder_proxy_router
from backend.config.recorder_proxy import RecorderProxyConfig
from backend.services.http.recorder_http_client import RecorderUpstreamError
from backend.services.recorder_proxy.service import RecorderProxyService


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
        return {
            "ok": True,
            "data": {"status": "ok", "contract_version": "0.1.0", "uptime_seconds": 10},
            "error": None,
        }
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


def make_client(service):
    app = FastAPI()
    app.include_router(create_recorder_proxy_router(service=service))
    return TestClient(app), service


class RecorderProxyRouteTests(unittest.TestCase):
    def test_health_proxy(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["status"], "ok")
        self.assertIsNone(body["error"])

    def test_status_proxy(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["data"]["status"], "running")

    def test_storage_proxy(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/storage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["filesystem"], "/x")

    def test_storage_query_rejected(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/storage?any=param")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_query_invalid"
        )

    def test_archives_proxy(self):
        client, service = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get(
            "/api/market-recorder/archives?page=1&page_size=10&sort=start_time"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        _, endpoint, params = service._client.calls[0]
        self.assertEqual(params, {"page": "1", "page_size": "10", "sort": "start_time"})

    def test_unknown_query_not_forwarded(self):
        client, service = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get(
            "/api/market-recorder/archives?page=1&evil=value"
        )
        self.assertEqual(response.status_code, 200)
        _, endpoint, params = service._client.calls[0]
        self.assertNotIn("evil", params)
        self.assertEqual(params, {"page": "1"})

    def test_missing_config_disabled(self):
        client, _ = make_client(
            RecorderProxyService(
                config=RecorderProxyConfig(
                    enabled=False,
                    base_url="",
                    timeout_seconds=1.0,
                    verify_tls=True,
                )
            )
        )
        response = client.get("/api/market-recorder/health")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "market_recorder_proxy_disabled")

    def test_invalid_config_disabled(self):
        client, _ = make_client(
            RecorderProxyService(
                config=RecorderProxyConfig(
                    enabled=True,
                    base_url="",
                    timeout_seconds=1.0,
                    verify_tls=True,
                )
            )
        )
        response = client.get("/api/market-recorder/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_proxy_configuration_error"
        )

    def test_invalid_query_returns_400(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/archives?page=0")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_query_invalid"
        )

    def test_from_greater_than_to_rejected(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get(
            "/api/market-recorder/archives?from=2026-08-01T00:00:00Z&to=2026-07-01T00:00:00Z"
        )
        self.assertEqual(response.status_code, 400)

    def test_upstream_timeout_safe_error(self):
        def handler(endpoint_key, query_params):
            raise RecorderUpstreamError("market_recorder_upstream_timeout", retryable=True)

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.get("/api/market-recorder/status")
        self.assertEqual(response.status_code, 504)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_upstream_timeout"
        )

    def test_upstream_unavailable_safe_error(self):
        def handler(endpoint_key, query_params):
            raise RecorderUpstreamError("market_recorder_upstream_unavailable", retryable=True)

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.get("/api/market-recorder/storage")
        self.assertEqual(response.status_code, 503)

    def test_invalid_upstream_response_safe_error(self):
        def handler(endpoint_key, query_params):
            return {"ok": True, "data": {"unexpected": True}, "error": None}

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.get("/api/market-recorder/health")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["error"]["code"],
            "market_recorder_upstream_invalid_response",
        )

    def test_internal_error_is_safe(self):
        def handler(endpoint_key, query_params):
            raise RuntimeError("/home/secret/path stacktrace credential=abc")

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.get("/api/market-recorder/health")
        self.assertEqual(response.status_code, 500)
        rendered = str(response.json())
        self.assertNotIn("home", rendered)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("credential", rendered)
        self.assertNotIn("RuntimeError", rendered)

    def test_get_only(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.post("/api/market-recorder/health")
        self.assertEqual(response.status_code, 405)
        response = client.delete("/api/market-recorder/archives")
        self.assertEqual(response.status_code, 405)
        response = client.put("/api/market-recorder/storage")
        self.assertEqual(response.status_code, 405)
        response = client.patch("/api/market-recorder/status")
        self.assertEqual(response.status_code, 405)

    def test_no_arbitrary_path(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/upload")
        self.assertEqual(response.status_code, 404)
        response = client.get("/api/recorder/health")
        self.assertEqual(response.status_code, 404)

    def test_internal_url_not_exposed(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/status")
        rendered = response.text
        self.assertNotIn("recorder.example.com", rendered)
        self.assertNotIn("http://", rendered)

    def test_storage_runtime_bytes_route(self):
        def handler(endpoint_key, query_params):
            if endpoint_key == "storage":
                return {
                    "ok": True,
                    "data": {"filesystem": "/x", "runtime_bytes": 524288000},
                    "error": None,
                }
            return {"ok": True, "data": {}, "error": None}

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.get("/api/market-recorder/storage")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["filesystem"], "/x")
        self.assertEqual(body["data"]["runtime_bytes"], 524288000)


class RecorderProxyControlRouteTests(unittest.TestCase):
    def test_start_route_dry_run(self):
        def handler(endpoint_key, body):
            self.assertEqual(endpoint_key, "start")
            self.assertIn("dry_run", body)
            self.assertTrue(body["dry_run"])
            return {
                "ok": True,
                "data": {"status": "dry_run_ok", "current_state": "idle", "plan": "would_start"},
                "error": None,
            }

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["status"], "dry_run_ok")

    def test_stop_route(self):
        def handler(endpoint_key, body):
            return {
                "ok": True,
                "data": {"status": "stopped", "current_state": "idle", "event_count": 10},
                "error": None,
            }

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/stop", json={"dry_run": False})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["status"], "stopped")
        self.assertEqual(body["data"]["event_count"], 10)

    def test_control_disabled(self):
        client, _ = make_client(
            RecorderProxyService(
                config=RecorderProxyConfig(
                    enabled=False,
                    base_url="",
                    timeout_seconds=1.0,
                    verify_tls=True,
                )
            )
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_proxy_disabled"
        )

    def test_control_upstream_conflict_409(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError(
                "market_recorder_upstream_rejected",
                retryable=False,
                status_code=409,
            )

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_upstream_conflict"
        )

    def test_control_upstream_client_identity_401_remains_diagnostic(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError(
                "market_recorder_upstream_rejected",
                retryable=False,
                status_code=401,
            )

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            "market_recorder_client_identity_invalid",
        )

    def test_control_upstream_locked_423(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError(
                "market_recorder_upstream_rejected",
                retryable=False,
                status_code=423,
            )

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/stop", json={"dry_run": True})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_upstream_locked"
        )

    def test_control_upstream_rate_limited_429(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError(
                "market_recorder_upstream_rejected",
                retryable=False,
                status_code=429,
            )

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json()["error"]["code"], "market_recorder_upstream_rate_limited"
        )

    def test_control_upstream_timeout(self):
        def handler(endpoint_key, body):
            raise RecorderUpstreamError("market_recorder_upstream_timeout", retryable=True)

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/stop", json={"dry_run": True})
        self.assertEqual(response.status_code, 504)
        body = response.json()
        self.assertEqual(body["error"]["code"], "market_recorder_upstream_timeout")
        self.assertTrue(body["error"]["retryable"])

    def test_control_internal_error_is_safe(self):
        def handler(endpoint_key, body):
            raise RuntimeError("/secret/path credential=abc")

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start", json={"dry_run": True})
        self.assertEqual(response.status_code, 500)
        rendered = str(response.json())
        self.assertNotIn("secret", rendered)
        self.assertNotIn("credential", rendered)

    def test_get_on_control_endpoint_405(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.get("/api/market-recorder/start")
        self.assertEqual(response.status_code, 405)
        response = client.get("/api/market-recorder/stop")
        self.assertEqual(response.status_code, 405)

    def test_start_without_body_is_rejected(self):
        def handler(endpoint_key, body):
            self.assertIsNone(body)
            return {
                "ok": True,
                "data": {"status": "started", "current_state": "running"},
                "error": None,
            }

        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(handler))
        )
        response = client.post("/api/market-recorder/start")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "market_recorder_query_invalid")

    def test_control_rejects_non_boolean_dry_run(self):
        client, _ = make_client(
            RecorderProxyService(config=enabled_config(), client=FakeClient(ok_handler))
        )
        response = client.post("/api/market-recorder/stop", json={"dry_run": "true"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
