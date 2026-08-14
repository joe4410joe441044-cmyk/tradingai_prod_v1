import hashlib
import hmac
import json
import os
import secrets
import time
import unittest
from datetime import datetime, timezone
from http.cookiejar import Cookie, CookieJar

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.auth_config import OperatorAuthConfig, load_operator_auth_config
from backend.auth.operator_session import (
    COOKIE_NAME,
    OperatorSession,
    OperatorSessionManager,
)
from backend.auth.operator_auth import (
    OperatorAuthenticator,
    hash_operator_credential,
    verify_operator_credential,
)
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
    generate_csrf_token,
)
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.auth.api import create_operator_auth_router


SESSION_SECRET = "a" * 32
TEST_CREDENTIAL = "test-operator-credential-42"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)


class TestCredentialHashing(unittest.TestCase):
    def test_hash_and_verify(self):
        h = hash_operator_credential("my-password")
        self.assertTrue(verify_operator_credential("my-password", h))
        self.assertFalse(verify_operator_credential("wrong-password", h))
        self.assertFalse(verify_operator_credential("", h))
        self.assertFalse(verify_operator_credential("my-password", "not-a-hash"))
        self.assertFalse(verify_operator_credential("my-password", "pbkdf2:sha256:bad"))
        self.assertFalse(verify_operator_credential("my-password", ""))

    def test_hash_unique_per_call(self):
        h1 = hash_operator_credential("same")
        h2 = hash_operator_credential("same")
        self.assertNotEqual(h1, h2)

    def test_verify_invalid_format(self):
        self.assertFalse(verify_operator_credential("x", "pbkdf2:md5:1000$aa$bb"))
        self.assertFalse(verify_operator_credential("x", "pbkdf2:sha256:notint$aa$bb"))
        self.assertFalse(verify_operator_credential("x", "pbkdf2:sha256:1000$nothex$bb"))


class TestOperatorAuthenticator(unittest.TestCase):
    def test_authenticate_valid(self):
        auth = OperatorAuthenticator(TEST_CREDENTIAL_HASH)
        self.assertTrue(auth.authenticate(TEST_CREDENTIAL))

    def test_authenticate_invalid(self):
        auth = OperatorAuthenticator(TEST_CREDENTIAL_HASH)
        self.assertFalse(auth.authenticate("wrong"))
        self.assertFalse(auth.authenticate(""))

    def test_authenticator_rejects_invalid_hash(self):
        with self.assertRaises(ValueError):
            OperatorAuthenticator("not-a-hash")
        with self.assertRaises(ValueError):
            OperatorAuthenticator("")


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.manager = OperatorSessionManager(SESSION_SECRET, session_ttl_seconds=3600)

    def test_create_and_validate(self):
        session = self.manager.create_session("operator")
        self.assertEqual(session.identity, "operator")
        validated = self.manager.validate_session(session.session_id)
        self.assertIsNotNone(validated)
        self.assertEqual(validated.identity, "operator")

    def test_invalid_session_id(self):
        self.assertIsNone(self.manager.validate_session("nonexistent"))

    def test_revoke_session(self):
        session = self.manager.create_session("operator")
        self.manager.revoke_session(session.session_id)
        self.assertIsNone(self.manager.validate_session(session.session_id))

    def test_sign_and_unsign(self):
        session = self.manager.create_session("operator")
        signed = self.manager.sign(session.session_id)
        self.assertIn(".", signed)
        unsigned = self.manager.unsign(signed)
        self.assertEqual(unsigned, session.session_id)

    def test_unsign_tampered(self):
        session = self.manager.create_session("operator")
        signed = self.manager.sign(session.session_id)
        tampered = signed[:-1] + ("f" if signed[-1] != "f" else "e")
        self.assertIsNone(self.manager.unsign(tampered))

    def test_unsign_invalid_format(self):
        self.assertIsNone(self.manager.unsign(""))
        self.assertIsNone(self.manager.unsign("no-dot"))
        self.assertIsNone(self.manager.unsign(".nosession"))
        self.assertIsNone(self.manager.unsign("session.invalidhex"))

    def test_session_expiry(self):
        manager = OperatorSessionManager(SESSION_SECRET, session_ttl_seconds=0)
        session = manager.create_session("operator")
        self.assertIsNone(manager.validate_session(session.session_id))

    def test_active_sessions_count(self):
        self.assertEqual(self.manager.active_sessions, 0)
        s1 = self.manager.create_session("op1")
        s2 = self.manager.create_session("op2")
        self.assertEqual(self.manager.active_sessions, 2)
        self.manager.revoke_session(s1.session_id)
        self.assertEqual(self.manager.active_sessions, 1)

    def test_session_secret_too_short(self):
        with self.assertRaises(ValueError):
            OperatorSessionManager("short", session_ttl_seconds=3600)


def _build_test_app(
    auth_configured=True,
    session_ttl=3600,
    rate_limit=100,
    rate_window=60,
):
    app = FastAPI()
    config = OperatorAuthConfig(
        credential_hash=TEST_CREDENTIAL_HASH if auth_configured else None,
        session_secret=SESSION_SECRET if auth_configured else None,
        session_ttl_seconds=session_ttl,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
        auth_rate_limit=rate_limit,
        auth_rate_window_seconds=rate_window,
    )
    if auth_configured:
        manager = OperatorSessionManager(config.session_secret, session_ttl)
        authenticator = OperatorAuthenticator(config.credential_hash)
        app.add_middleware(OperatorSessionMiddleware, session_manager=manager, config=config)
        csrf_paths = frozenset({"/api/auth/logout"})
        app.add_middleware(OperatorCsrfProtection, csrf_required_paths=csrf_paths)
        app.include_router(create_operator_auth_router(authenticator, manager, config))
    return app


def _extract_cookies(response, names=None):
    cookies = {}
    for header in response.headers.get_list("set-cookie"):
        for part in header.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                if names is None or key.strip() in names:
                    cookies[key.strip()] = value.strip()
    return cookies


class TestAuthEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_1_valid_authentication_creates_session(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "AUTHENTICATED")
        cookies = _extract_cookies(resp, {COOKIE_NAME})
        self.assertIn(COOKIE_NAME, cookies)

    def test_2_invalid_authentication_rejects(self):
        resp = self.client.post("/api/auth/login", json={"credential": "wrong"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["status"], "UNAUTHENTICATED")

    def test_3_missing_authentication_rejects(self):
        resp = self.client.post("/api/auth/login", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["status"], "UNAUTHENTICATED")

    def test_4_valid_session_returns_authenticated(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        cookies = _extract_cookies(resp, {COOKIE_NAME, CSRF_TOKEN_COOKIE})
        session_value = cookies[COOKIE_NAME]
        resp2 = self.client.get(
            "/api/auth/status",
            cookies={COOKIE_NAME: session_value},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "AUTHENTICATED")

    def test_5_random_session_rejects(self):
        resp = self.client.get(
            "/api/auth/status",
            cookies={COOKIE_NAME: "random.invalidsig"},
        )
        self.assertEqual(resp.json()["status"], "UNAUTHENTICATED")

    def test_6_expired_session_rejects(self):
        app = _build_test_app(session_ttl=0)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        cookies = _extract_cookies(resp, {COOKIE_NAME})
        session_value = cookies[COOKIE_NAME]
        resp2 = client.get("/api/auth/status", cookies={COOKIE_NAME: session_value})
        self.assertEqual(resp2.json()["status"], "UNAUTHENTICATED")

    def test_7_logout_revokes_session(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        cookies = _extract_cookies(resp, {COOKIE_NAME, CSRF_TOKEN_COOKIE})
        session_value = cookies[COOKIE_NAME]
        csrf_token = cookies[CSRF_TOKEN_COOKIE]

        resp2 = self.client.post(
            "/api/auth/logout",
            cookies={COOKIE_NAME: session_value, CSRF_TOKEN_COOKIE: csrf_token},
            headers={CSRF_TOKEN_HEADER: csrf_token},
        )
        self.assertEqual(resp2.status_code, 200)

        resp3 = self.client.get(
            "/api/auth/status",
            cookies={COOKIE_NAME: session_value},
        )
        self.assertEqual(resp3.json()["status"], "UNAUTHENTICATED")

    def test_8_session_fixation_prevented(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        cookies_before = _extract_cookies(resp, {COOKIE_NAME})
        session_before = cookies_before[COOKIE_NAME]

        resp2 = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
            cookies={COOKIE_NAME: session_before},
        )
        cookies_after = _extract_cookies(resp2, {COOKIE_NAME})
        session_after = cookies_after[COOKIE_NAME]

        self.assertNotEqual(session_before, session_after)

        resp3 = self.client.get(
            "/api/auth/status",
            cookies={COOKIE_NAME: session_before},
        )
        self.assertEqual(resp3.json()["status"], "UNAUTHENTICATED")

    def test_9_authentication_rate_limit(self):
        app = _build_test_app(rate_limit=3, rate_window=60)
        client = TestClient(app, raise_server_exceptions=False)
        for _ in range(3):
            client.post("/api/auth/login", json={"credential": "wrong"})
        resp = client.post("/api/auth/login", json={"credential": "wrong"})
        self.assertEqual(resp.status_code, 429)

    def test_10_no_credential_in_response(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        body = resp.json()
        self.assertNotIn("credential", body)
        self.assertNotIn("hash", body)
        self.assertNotIn("password", body)

    def test_11_status_without_session(self):
        resp = self.client.get("/api/auth/status")
        self.assertEqual(resp.json()["status"], "UNAUTHENTICATED")

    def test_12_large_body_rejected(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"credential": "x" * 5000},
        )
        self.assertEqual(resp.status_code, 413)

    def test_13_content_type_validation(self):
        resp = self.client.post(
            "/api/auth/login",
            content="credential=test",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(resp.status_code, 415)


class TestCsrfProtection(unittest.TestCase):
    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_logout_without_csrf_rejected(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        cookies = _extract_cookies(resp, {COOKIE_NAME, CSRF_TOKEN_COOKIE})
        session_value = cookies[COOKIE_NAME]

        resp2 = self.client.post(
            "/api/auth/logout",
            cookies={COOKIE_NAME: session_value},
        )
        self.assertEqual(resp2.status_code, 403)

    def test_logout_with_wrong_csrf_rejected(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        cookies = _extract_cookies(resp, {COOKIE_NAME, CSRF_TOKEN_COOKIE})
        session_value = cookies[COOKIE_NAME]
        wrong_token = generate_csrf_token()

        resp2 = self.client.post(
            "/api/auth/logout",
            cookies={
                COOKIE_NAME: session_value,
                CSRF_TOKEN_COOKIE: cookies[CSRF_TOKEN_COOKIE],
            },
            headers={CSRF_TOKEN_HEADER: wrong_token},
        )
        self.assertEqual(resp2.status_code, 403)

    def test_csrf_token_generated_on_login(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        cookies = _extract_cookies(resp, {CSRF_TOKEN_COOKIE})
        self.assertIn(CSRF_TOKEN_COOKIE, cookies)
        token = cookies[CSRF_TOKEN_COOKIE]
        self.assertEqual(len(token), 64)

    def test_csrf_token_in_response_header(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        csrf_header = resp.headers.get(CSRF_TOKEN_HEADER)
        self.assertIsNotNone(csrf_header)
        cookies = _extract_cookies(resp, {CSRF_TOKEN_COOKIE})
        self.assertEqual(csrf_header, cookies[CSRF_TOKEN_COOKIE])


class TestBrowserGatewaySessionAuth(unittest.TestCase):
    def setUp(self):
        self.gateway_app = self._build_gateway_app()
        self.client = TestClient(self.gateway_app, raise_server_exceptions=False)

    def _build_gateway_app(self):
        from backend.ai_advisor.api_rate_limit import (
            AdvisorConcurrencyLimiter,
            AdvisorRateLimiter,
        )
        from backend.ai_advisor.browser_gateway import (
            AdvisorBrowserGatewayComposition,
            AdvisorBrowserGatewayConfig,
            AdvisorGatewayPreflightDenyMiddleware,
            create_browser_gateway_router,
        )
        from backend.ai_advisor.observability import NoOpAdvisorObservationSink

        config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
            secure_cookie=False,
        )
        self._session_manager = OperatorSessionManager(SESSION_SECRET, 3600)
        authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)

        gw_config = AdvisorBrowserGatewayConfig(
            enabled=True,
            trustedProxyPeers=(),
            allowedOrigins=("http://testserver",),
            endpointTimeoutSeconds=5,
        )

        class CountingService:
            def __init__(self):
                self.calls = 0

            def generate_response(self, service_input):
                self.calls += 1
                from backend.ai_advisor.service_models import (
                    AdvisorServiceFailureCode,
                    AdvisorServiceFailure,
                    AdvisorServiceResult,
                    AdvisorServiceStatus,
                )
                return AdvisorServiceResult(
                    status=AdvisorServiceStatus.FAILED,
                    failure=AdvisorServiceFailure(
                        code=AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
                        safeMessage="advisor provider unavailable",
                    ),
                )

        self._service = CountingService()

        rate_limiter = AdvisorRateLimiter(limit=10, window_seconds=60, clock=time.monotonic)
        concurrency = AdvisorConcurrencyLimiter(limit=2, acquire_timeout_seconds=1)

        composition = AdvisorBrowserGatewayComposition(
            config=gw_config,
            service=self._service,
            rateLimiter=rate_limiter,
            concurrencyLimiter=concurrency,
            externalStatus="OFFLINE",
            observationSink=NoOpAdvisorObservationSink(),
        )

        app = FastAPI()
        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self._session_manager,
            config=config,
        )
        app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
        app.include_router(create_browser_gateway_router(composition))
        app.include_router(
            create_operator_auth_router(
                authenticator, self._session_manager, config,
            ),
        )
        return app

    def _login_and_get_cookies(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        return _extract_cookies(resp, {COOKIE_NAME})

    def test_13_no_session_no_trusted_peer_rejected(self):
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_14_authenticated_session_accesses_gateway(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertIn(resp.status_code, [200, 503])

    def test_15_spoofed_header_without_session_rejected(self):
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
                "X-TradingAI-Authenticated-User": "admin",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_16_session_identity_used_not_header(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
                "X-TradingAI-Authenticated-User": "attacker",
            },
        )
        self.assertIn(resp.status_code, [200, 503])

    def test_17_wrong_origin_rejected_even_with_session(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "https://evil.example.com",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_18_valid_origin_no_session_rejected(self):
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_19_web_client_header_required_with_session(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "Hello"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_20_gateway_status_with_session(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.get(
            "/api/ai-advisor/conversation/status",
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(resp.json()["status"], ["AVAILABLE", "OFFLINE", "UNAVAILABLE"])

    def test_21_gateway_runtime_with_session(self):
        cookies = self._login_and_get_cookies()
        resp = self.client.get(
            "/api/ai-advisor/conversation/runtime",
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
            },
        )
        self.assertEqual(resp.status_code, 200)


class TestSessionCookieSecurity(unittest.TestCase):
    def setUp(self):
        self.app = _build_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_session_cookie_httponly(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        for header in resp.headers.get_list("set-cookie"):
            if header.startswith(COOKIE_NAME):
                self.assertIn("HttpOnly", header)

    def test_session_cookie_path(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        for header in resp.headers.get_list("set-cookie"):
            if header.startswith(COOKIE_NAME):
                self.assertIn("Path=/", header)

    def test_session_cookie_samesite(self):
        resp = self.client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
        for header in resp.headers.get_list("set-cookie"):
            if header.startswith(COOKIE_NAME):
                self.assertIn("SameSite", header)


class TestAuthNotConfigured(unittest.TestCase):
    def test_auth_endpoints_disabled_when_not_configured(self):
        app = _build_test_app(auth_configured=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/auth/login", json={"credential": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_config_loads_from_env(self):
        os.environ["TRADINGAI_OPERATOR_CREDENTIAL_HASH"] = TEST_CREDENTIAL_HASH
        os.environ["TRADINGAI_SESSION_SECRET"] = SESSION_SECRET
        try:
            config = load_operator_auth_config()
            self.assertEqual(config.credential_hash, TEST_CREDENTIAL_HASH)
            self.assertEqual(config.session_secret, SESSION_SECRET)
        finally:
            del os.environ["TRADINGAI_OPERATOR_CREDENTIAL_HASH"]
            del os.environ["TRADINGAI_SESSION_SECRET"]

    def test_config_defaults_when_not_set(self):
        for key in [
            "TRADINGAI_OPERATOR_CREDENTIAL_HASH",
            "TRADINGAI_SESSION_SECRET",
        ]:
            os.environ.pop(key, None)
        config = load_operator_auth_config()
        self.assertIsNone(config.credential_hash)
        self.assertIsNone(config.session_secret)
        self.assertEqual(config.session_ttl_seconds, 28800)


class TestHeaderSpoofing(unittest.TestCase):
    def setUp(self):
        from backend.ai_advisor.browser_gateway import (
            AdvisorBrowserGatewayComposition,
            AdvisorBrowserGatewayConfig,
            AdvisorGatewayPreflightDenyMiddleware,
            create_browser_gateway_router,
        )
        from backend.ai_advisor.observability import NoOpAdvisorObservationSink
        from backend.ai_advisor.api_rate_limit import (
            AdvisorConcurrencyLimiter,
            AdvisorRateLimiter,
        )

        config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
            secure_cookie=False,
        )
        self._session_manager = OperatorSessionManager(SESSION_SECRET, 3600)
        authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)

        gw_config = AdvisorBrowserGatewayConfig(
            enabled=True,
            trustedProxyPeers=(),
            allowedOrigins=("http://testserver",),
            endpointTimeoutSeconds=5,
        )

        class NoopService:
            def generate_response(self, _input):
                from backend.ai_advisor.service_models import (
                    AdvisorServiceFailureCode,
                    AdvisorServiceFailure,
                    AdvisorServiceResult,
                    AdvisorServiceStatus,
                )
                return AdvisorServiceResult(
                    status=AdvisorServiceStatus.FAILED,
                    failure=AdvisorServiceFailure(
                        code=AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
                        safeMessage="advisor provider unavailable",
                    ),
                )

        composition = AdvisorBrowserGatewayComposition(
            config=gw_config,
            service=NoopService(),
            rateLimiter=AdvisorRateLimiter(limit=10, window_seconds=60, clock=time.monotonic),
            concurrencyLimiter=AdvisorConcurrencyLimiter(limit=2, acquire_timeout_seconds=1),
            externalStatus="OFFLINE",
            observationSink=NoOpAdvisorObservationSink(),
        )

        app = FastAPI()
        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self._session_manager,
            config=config,
        )
        app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)
        app.include_router(create_browser_gateway_router(composition))
        app.include_router(
            create_operator_auth_router(authenticator, self._session_manager, config),
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_no_session_spoofed_header_rejected(self):
        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "test"},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
                "X-TradingAI-Authenticated-User": "admin",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_session_exists_spoofed_header_ignored(self):
        login_resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        cookies = _extract_cookies(login_resp, {COOKIE_NAME})
        self.assertIn(COOKIE_NAME, cookies)

        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "test"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "web",
                "X-TradingAI-Authenticated-User": "attacker",
            },
        )
        self.assertIn(resp.status_code, [200, 503])

    def test_session_without_client_header_rejected(self):
        login_resp = self.client.post(
            "/api/auth/login",
            json={"credential": TEST_CREDENTIAL},
        )
        cookies = _extract_cookies(login_resp, {COOKIE_NAME})

        resp = self.client.post(
            "/api/ai-advisor/conversation",
            json={"prompt": "test"},
            cookies={COOKIE_NAME: cookies[COOKIE_NAME]},
            headers={
                "Origin": "http://testserver",
                "X-TradingAI-Client": "cli",
            },
        )
        self.assertEqual(resp.status_code, 403)


class TestSessionMiddleware(unittest.TestCase):
    def setUp(self):
        self.manager = OperatorSessionManager(SESSION_SECRET, 3600)

    def test_valid_cookie_populates_scope(self):
        session = self.manager.create_session("operator")
        signed = self.manager.sign(session.session_id)

        from fastapi import Request as FastAPIRequest

        app = FastAPI()
        config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
        )

        captured = {}

        @app.get("/test")
        async def test_route(req: FastAPIRequest):
            captured["session"] = req.scope.get("operator_session")

        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self.manager,
            config=config,
        )

        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(COOKIE_NAME, signed)
        client.get("/test")
        self.assertIsNotNone(captured.get("session"))
        self.assertEqual(captured["session"]["identity"], "operator")

    def test_invalid_cookie_does_not_populate_scope(self):
        from fastapi import Request as FastAPIRequest

        app = FastAPI()
        config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
        )

        captured = {}

        @app.get("/test")
        async def test_route(req: FastAPIRequest):
            captured["session"] = req.scope.get("operator_session")

        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self.manager,
            config=config,
        )

        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.set(COOKIE_NAME, "invalid.fakesig")
        client.get("/test")
        self.assertIsNone(captured.get("session"))

    def test_no_cookie_no_scope(self):
        from fastapi import Request as FastAPIRequest

        app = FastAPI()
        config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
        )

        captured = {}

        @app.get("/test")
        async def test_route(req: FastAPIRequest):
            captured["session"] = req.scope.get("operator_session")

        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self.manager,
            config=config,
        )

        client = TestClient(app)
        client.get("/test")
        self.assertIsNone(captured.get("session"))
