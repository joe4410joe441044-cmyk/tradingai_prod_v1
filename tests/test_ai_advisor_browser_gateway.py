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
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
    generate_csrf_token,
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


class SessionMiddleware:
    """Simulate OperatorSessionMiddleware injecting an authenticated session."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["operator_session"] = {
            "identity": "operator",
            "session_id": "session-1",
        }
        await self.app(scope, receive, send)


def build_composition(
    *,
    enabled=True,
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
    return composition, dependency


def build_app(composition, *, session=False):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if session:
        app.add_middleware(SessionMiddleware)
    app.include_router(create_browser_gateway_router(composition))
    app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
    return app


def build_csrf_app(composition):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SessionMiddleware)
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=frozenset({"/api/ai-advisor/conversation"}),
    )
    app.include_router(create_browser_gateway_router(composition))
    app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
    return app


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
    session=False,
):
    composition, dependency = build_composition(
        enabled=enabled,
        service_dependency=service_dependency,
        rate_limit=rate_limit,
        timeout=timeout,
        approved_specifications=approved_specifications,
        observation_sink=observation_sink,
        request_id_factory=request_id_factory,
    )
    app = build_app(composition, session=session)
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

    def test_observed_lifecycle_explanation_reaches_read_only_service(self):
        prompt = (
            "TradingAIでBotを開始してから取引判断に至るまで、各主要コンポーネントが"
            "どのような役割を持つのか、現在あなたが参照できるTradingAIの正式な情報だけを"
            "使って説明してください。分からない部分は推測せず、何が不足しているのかも"
            "教えてください。"
        )
        api, dependency = gateway()
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": prompt},
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        self.assertEqual(dependency.calls, 1)
        self.assertNotEqual(
            response.json()["advisorResponse"].get("refusalCategory"),
            "BOT_OPERATION",
        )

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

    def test_session_identity_accepts_browser_fetch_metadata_get(self):
        # Real browsers omit Origin on same-origin GET requests but attach
        # Sec-Fetch-Site: same-origin. The session path must serve those.
        api, dependency = gateway(session=True)
        status = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "X-TradingAI-Client": "web",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json(), {"status": "OFFLINE"})

        runtime = api.get(
            "/api/ai-advisor/conversation/runtime",
            headers={
                "X-TradingAI-Client": "web",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(runtime.status_code, 200)
        self.assertEqual(runtime.json()["bot"]["state"], "UNKNOWN")
        self.assertEqual(dependency.calls, 0)

    def test_session_get_without_origin_and_fetch_metadata_fails_closed(self):
        # A session cookie alone is NOT a same-origin proof. A GET with neither
        # Origin nor browser Fetch Metadata must fail closed.
        api, dependency = gateway(session=True)
        for path in (
            "/api/ai-advisor/conversation/status",
            "/api/ai-advisor/conversation/runtime",
        ):
            response = api.get(path, headers={"X-TradingAI-Client": "web"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(dependency.calls, 0)

    def test_session_get_rejects_non_same_origin_fetch_metadata(self):
        for fetch_site in ("cross-site", "same-site", "none", "attacker", ""):
            api, dependency = gateway(session=True)
            response = api.get(
                "/api/ai-advisor/conversation/status",
                headers={
                    "X-TradingAI-Client": "web",
                    "Sec-Fetch-Site": fetch_site,
                },
            )
            self.assertEqual(response.status_code, 403, fetch_site)
            self.assertEqual(dependency.calls, 0)

    def test_session_get_rejects_duplicate_fetch_metadata(self):
        api, dependency = gateway(session=True)
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers=[
                ("X-TradingAI-Client", "web"),
                ("Sec-Fetch-Site", "same-origin"),
                ("Sec-Fetch-Site", "same-origin"),
            ],
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_session_get_allowed_origin_is_allowed_and_evil_origin_denied(self):
        api, dependency = gateway(session=True)
        allowed = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "X-TradingAI-Client": "web",
                "Origin": ORIGIN,
            },
        )
        self.assertEqual(allowed.status_code, 200)

        api, dependency = gateway(session=True)
        evil = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "X-TradingAI-Client": "web",
                "Origin": "https://evil.invalid",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(evil.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_unauthenticated_get_denied_even_with_fetch_metadata(self):
        api, dependency = gateway(session=False)
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "X-TradingAI-Client": "web",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(dependency.calls, 0)

    def test_session_identity_rejects_wrong_origin_when_present(self):
        api, dependency = gateway(session=True)
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers={
                "X-TradingAI-Client": "web",
                "Origin": "https://attacker.invalid",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_session_post_without_origin_denied(self):
        # Missing Origin must never be accepted for POST even with a valid
        # session and same-origin Fetch Metadata.
        api, dependency = gateway(session=True)
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers={
                "X-TradingAI-Client": "web",
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_session_post_with_disallowed_origin_denied(self):
        api, dependency = gateway(session=True)
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers={
                "X-TradingAI-Client": "web",
                "Content-Type": "application/json",
                "Origin": "https://evil.invalid",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_trusted_proxy_fetch_metadata_does_not_bypass_origin(self):
        # The trusted-proxy identity path keeps requiring an explicit exact
        # Origin. Browser Fetch Metadata is only a same-origin proof for the
        # session path and must not widen the trusted-proxy contract.
        api, dependency = gateway()
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "X-TradingAI-Client": "web",
                "X-TradingAI-Authenticated-User": "operator-1",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_post_without_csrf_denied(self):
        composition, dependency = build_composition()
        app = build_csrf_app(composition)
        api = TestClient(
            PeerMiddleware(app, "127.0.0.1"),
            raise_server_exceptions=False,
        )
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            headers=headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_valid_post_security_contract_passes_with_mock_service(self):
        # Full POST security contract (session + exact Origin + CSRF + client
        # header) passes authorization using only the fake Advisor service.
        # No real OpenAI request is ever made.
        composition, dependency = build_composition()
        app = build_csrf_app(composition)
        api = TestClient(
            PeerMiddleware(app, "127.0.0.1"),
            raise_server_exceptions=False,
        )
        token = generate_csrf_token()
        response = api.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Explain the system."},
            cookies={CSRF_TOKEN_COOKIE: token},
            headers={
                "Origin": ORIGIN,
                "X-TradingAI-Client": "web",
                "Content-Type": "application/json",
                CSRF_TOKEN_HEADER: token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        self.assertEqual(dependency.calls, 1)
        self.assertNotIn("Authorization", response.text)

    def test_session_identity_still_requires_client_header(self):
        api, dependency = gateway(session=True)
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers={
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)

    def test_trusted_proxy_still_requires_explicit_origin(self):
        # The trusted-proxy path must keep requiring an explicit, exact Origin
        # even when the identity header is present.
        api, dependency = gateway()
        request_headers = headers()
        request_headers.pop("Origin")
        response = api.get(
            "/api/ai-advisor/conversation/status",
            headers=request_headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(dependency.calls, 0)


if __name__ == "__main__":
    unittest.main()
