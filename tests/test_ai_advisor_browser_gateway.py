import json
import time
import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.browser_gateway import (
    AdvisorBrowserGatewayComposition,
    AdvisorBrowserGatewayConfig,
    AdvisorGatewayPreflightDenyMiddleware,
    assemble_browser_service_input,
    create_browser_gateway_router,
)
from tests.test_ai_advisor_api import CountingService, FixedClock

NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
ORIGIN = "https://advisor.example.test"


class PeerMiddleware:
    def __init__(self, app, peer):
        self.app = app
        self.peer = peer

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["client"] = (self.peer, 43210)
        await self.app(scope, receive, send)


def gateway(
    *,
    enabled=True,
    peer="127.0.0.1",
    service_dependency=None,
    rate_limit=10,
    timeout=1,
    approved_specifications=(),
    observation_sink=None,
    request_id_factory=None,
):
    dependency = service_dependency or CountingService()
    config = AdvisorBrowserGatewayConfig(
        enabled=enabled,
        trustedProxyPeers=("127.0.0.1",),
        allowedOrigins=(ORIGIN,),
        endpointTimeoutSeconds=timeout,
    )
    composition = AdvisorBrowserGatewayComposition(
        config=config,
        service=dependency,
        rateLimiter=AdvisorRateLimiter(
            limit=rate_limit,
            window_seconds=60,
            clock=FixedClock(),
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=2,
            acquire_timeout_seconds=0.01,
        ),
        clock=lambda: NOW,
        externalStatus="OFFLINE",
        approvedSpecifications=approved_specifications,
        **({"observationSink": observation_sink} if observation_sink else {}),
        **({"requestIdFactory": request_id_factory} if request_id_factory else {}),
    )
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(create_browser_gateway_router(composition))
    app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
    return TestClient(PeerMiddleware(app, peer)), dependency


def headers(**overrides):
    values = {
        "Origin": ORIGIN,
        "X-TradingAI-Client": "web",
        "X-TradingAI-Authenticated-User": "operator-1",
        "Content-Type": "application/json",
    }
    values.update(overrides)
    return values


class BrowserGatewayTest(unittest.TestCase):
    def test_browser_runtime_is_trusted_peer_only_and_coarse(self):
        api, dependency = gateway()
        response = api.get(
            "/api/ai-advisor/conversation/runtime",
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bot"]["state"], "UNKNOWN")
        self.assertEqual(
            response.json()["warnings"],
            ["RUNTIME_DETAIL_NOT_APPROVED"],
        )
        self.assertEqual(dependency.calls, 0)

        direct, dependency = gateway(peer="203.0.113.10")
        denied = direct.get(
            "/api/ai-advisor/conversation/runtime",
            headers={**headers(), "X-Forwarded-For": "127.0.0.1"},
        )
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn("access-control-allow-origin", denied.headers)
        self.assertEqual(dependency.calls, 0)

    def test_gateway_is_disabled_by_default(self):
        api, dependency = gateway(enabled=False)
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers=headers(),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(dependency.calls, 0)

    def test_direct_or_forwarded_peer_spoof_cannot_establish_trust(self):
        api, dependency = gateway(peer="203.0.113.10")
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers={**headers(), "X-Forwarded-For": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(dependency.calls, 0)

    def test_identity_is_required_strict_and_server_owned(self):
        invalid = ("", " operator", "operator ", "bad/name", "a" * 129)
        for identity in invalid:
            api, dependency = gateway()
            request_headers = headers()
            request_headers["X-TradingAI-Authenticated-User"] = identity
            response = api.post(
                "/api/ai-advisor/conversation",
                json={"prompt": "Explain the system."},
                headers=request_headers,
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(dependency.calls, 0)

        api, dependency = gateway()
        duplicate_headers = [
            ("Origin", ORIGIN),
            ("X-TradingAI-Client", "web"),
            ("X-TradingAI-Authenticated-User", "operator-1"),
            ("X-TradingAI-Authenticated-User", "operator-2"),
            ("Content-Type", "application/json"),
        ]
        response = api.post(
            "/api/ai-advisor/conversation",
            content='{"prompt":"Explain the system."}',
            headers=duplicate_headers,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(dependency.calls, 0)

    def test_origin_and_custom_header_are_exact_and_required(self):
        invalid = (
            {"Origin": "https://advisor.example.test.attacker.invalid"},
            {"Origin": "https://user@advisor.example.test"},
            {"Origin": ""},
            {"X-TradingAI-Client": "mobile"},
            {"X-TradingAI-Client": ""},
        )
        for override in invalid:
            api, dependency = gateway()
            response = api.post(
                "/api/ai-advisor/conversation",
                json={"prompt": "Explain the system."},
                headers=headers(**override),
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(dependency.calls, 0)

    def test_browser_contract_rejects_authority_and_override_fields(self):
        for field in (
            "serviceInput",
            "permissionContext",
            "principalId",
            "provider",
            "model",
            "credential",
            "endpoint",
            "networkAllowed",
            "runtimeContext",
            "tradingContext",
        ):
            api, dependency = gateway()
            response = api.post(
                "/api/ai-advisor/conversation",
                json={"prompt": "Explain the system.", field: "forbidden"},
                headers=headers(),
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(dependency.calls, 0)

    def test_json_boundary_rejects_wrong_media_duplicate_and_blank_prompt(self):
        cases = (
            ("text/plain", '{"prompt":"hello"}'),
            ("application/json", '{"prompt":"one","prompt":"two"}'),
            ("application/json", '{"prompt":"   "}'),
        )
        for media_type, body in cases:
            api, dependency = gateway()
            response = api.post(
                "/api/ai-advisor/conversation",
                content=body,
                headers=headers(**{"Content-Type": media_type}),
            )
            self.assertIn(response.status_code, {415, 422})
            self.assertEqual(dependency.calls, 0)

    def test_server_assembly_owns_principal_and_is_read_only(self):
        value = assemble_browser_service_input(
            prompt="Explain the system.",
            principal_id="operator-1",
            now=NOW,
            request_id="request-1",
        )
        permission = value.request.permissionContext
        self.assertEqual(permission.principalId, "operator-1")
        self.assertTrue(permission.readOnly)
        self.assertFalse(permission.executionAllowed)
        self.assertFalse(permission.configurationMutationAllowed)
        self.assertIsNone(value.contextInput.runtime)
        self.assertEqual(value.request.message, "Explain the system.")

    def test_mock_service_e2e_and_safe_response(self):
        api, dependency = gateway()
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        self.assertEqual(dependency.calls, 1)
        service_input = dependency.delegate
        self.assertNotIn("Authorization", response.text)
        self.assertIsNotNone(service_input)

    def test_status_is_coarse_and_does_not_call_service(self):
        api, dependency = gateway()
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "OFFLINE"})
        self.assertEqual(dependency.calls, 0)
        self.assertNotIn("credential", response.text.lower())

    def test_rate_limit_and_timeout_reuse_safe_contracts(self):
        api, dependency = gateway(rate_limit=1)
        first = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "First request."},
            headers=headers(),
        )
        second = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Second request."},
            headers=headers(),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(dependency.calls, 1)

        class SlowService:
            calls = 0

            def generate_response(self, _value):
                self.calls += 1
                time.sleep(0.03)

        slow = SlowService()
        api, _ = gateway(service_dependency=slow, timeout=0.001)
        timed = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Timed request."},
            headers=headers(),
        )
        self.assertEqual(timed.status_code, 504)
        self.assertEqual(slow.calls, 1)

    def test_preflight_is_rejected(self):
        api, dependency = gateway()
        response = api.options(
            "/api/ai-advisor/conversation",
            headers={
                "Origin": "https://attacker.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_gateway_never_emits_cors_allow_headers_on_error_statuses(self):
        api, _ = gateway(enabled=False)
        disabled = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Unavailable."},
            headers=headers(),
        )
        api, _ = gateway(peer="203.0.113.2")
        unauthenticated = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Unauthenticated."},
            headers=headers(),
        )
        api, _ = gateway()
        denied = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Wrong origin."},
            headers=headers(Origin="https://unknown.invalid"),
        )
        invalid = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Valid.", "model": "forbidden"},
            headers=headers(),
        )
        self.assertEqual(
            [item.status_code for item in (disabled, unauthenticated, denied, invalid)],
            [503, 401, 403, 422],
        )
        for response in (disabled, unauthenticated, denied, invalid):
            self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
