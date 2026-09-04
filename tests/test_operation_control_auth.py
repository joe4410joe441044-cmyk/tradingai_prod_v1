"""TR-OPERATION-CONTROL-AUTH-BOUNDARY-REPAIR-1: control route auth boundary.

Proves the fail-closed security contract for every Operation control mutation
route: no session, a forged session, an invalid/expired session, and a valid
session without a valid CSRF token are all denied; a valid operator session
with an exact CSRF token reaches the existing control handler. Also proves an
auth/CSRF denial never mutates runtime state (neither a BotManager call nor a
governance-state mutation).
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import bot_api, governance, runtime
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
)
from backend.auth.operator_auth import (
    OperatorAuthenticator,
    hash_operator_credential,
)
from backend.auth.operator_session import (
    COOKIE_NAME,
    OperatorSessionManager,
)
from backend.auth.api import create_operator_auth_router
from backend.auth.dependencies import require_operator_session
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.runtime.governance_runtime import governance_state


SESSION_SECRET = "b" * 32
TEST_CREDENTIAL = "control-operator-credential-7"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)

SUPPORTED_PROTECTED_PATHS = frozenset({
    "/api/bot/start",
    "/api/bot/stop",
    "/api/bot/loop/start",
    "/api/bot/loop/stop",
    "/api/bot/live-auto/approve",
    "/api/bot/live-auto/start",
    "/api/bot/live-auto/stop",
    "/api/bot/paper-account/capital",
    "/api/governance/mode",
    "/api/governance/execution",
    "/api/governance/risk-profile",
    "/api/governance/emergency-stop",
    "/api/governance/emergency-orchestrate",
    "/api/governance/emergency/unlock",
    "/api/governance/emergency/retry",
    "/api/runtime/stopped-paper-safety/refresh",
    "/api/runtime/paper-auto/start",
    "/api/runtime/paper-auto/cycle",
    "/api/runtime/paper-auto/stop",
})

CSRF_PATHS = SUPPORTED_PROTECTED_PATHS | frozenset({
    "/api/auth/logout",
    "/api/ai-advisor/conversation",
})


class FakeBotManager:
    """Records calls so tests can prove denied requests never mutate runtime."""

    def __init__(self):
        self.calls = []

    def _record(self, name):
        self.calls.append(name)

    def start(self, config):
        self._record("start")
        return {"status": "started", "success": True}

    def stop(self):
        self._record("stop")
        return {"status": "stopped", "success": True}

    def start_loop(self):
        self._record("start_loop")
        return {"status": "started", "success": True}

    def stop_loop(self):
        self._record("stop_loop")
        return {"status": "stopped", "success": True}

    def set_execution_enabled(self, enabled):
        self._record("set_execution_enabled")
        return {"success": True, "execution_enabled": enabled}

    def run_emergency_orchestrator(self):
        self._record("run_emergency_orchestrator")
        return {
            "success": True,
            "completed": True,
            "partial": False,
            "state_unknown": False,
            "emergency_locked": True,
            "auto_trade_disabled": True,
            "execution_path": None,
            "symbol": None,
            "cancel": None,
            "flatten": None,
            "position_remaining": False,
            "retryable": False,
            "error_code": None,
        }

    def get_authoritative_pending_order_state(self):
        self._record("get_authoritative_pending_order_state")
        return {"pending_order": False, "known": True}

    def retry_emergency_orchestrator(self):
        self._record("retry_emergency_orchestrator")
        return {"success": False, "retry_rejected": True}

    def _set_lifecycle_state(self, state):
        self._record(f"_set_lifecycle_state:{state}")

    def reset_paper_capital(self, capital, source=None):
        self._record("reset_paper_capital")
        return {"success": True, "paperBalance": float(capital)}

    def approve_live_auto_control(
        self,
        approval_identity=None,
        approval_source=None,
        ttl_seconds=None,
    ):
        self._record("approve_live_auto_control")
        return {"accepted": True}

    def start_live_auto_control(self):
        self._record("start_live_auto_control")
        return {"accepted": True}

    def stop_live_auto_control(self):
        self._record("stop_live_auto_control")
        return {"accepted": True}

    def start_auto_market_selection_runtime(self):
        self._record("start_auto_market_selection_runtime")
        return {"success": True}

    def run_auto_market_selection_cycle(self):
        self._record("run_auto_market_selection_cycle")
        return {"accepted": True}

    def stop_auto_market_selection_runtime(self):
        self._record("stop_auto_market_selection_runtime")
        return {"success": True}

    def refresh_stopped_paper_safety_authority(self):
        self._record("refresh_stopped_paper_safety_authority")
        return {"success": True}


def _build_control_app(session_ttl=3600):
    config = OperatorAuthConfig(
        credential_hash=TEST_CREDENTIAL_HASH,
        session_secret=SESSION_SECRET,
        session_ttl_seconds=session_ttl,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
    )
    manager = OperatorSessionManager(SESSION_SECRET, session_ttl)
    authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)

    app = FastAPI()
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=manager,
        config=config,
    )
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=CSRF_PATHS,
    )
    app.include_router(create_operator_auth_router(authenticator, manager, config))
    app.include_router(bot_api.router, prefix="/api/bot")
    app.include_router(governance.router)
    app.include_router(runtime.router)
    return app


def _extract_cookie(response, name):
    for header in response.headers.get_list("set-cookie"):
        for part in header.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                if key.strip() == name:
                    return value.strip()
    return None


def _login(client):
    resp = client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
    assert resp.status_code == 200, resp.text
    session = _extract_cookie(resp, COOKIE_NAME)
    csrf = _extract_cookie(resp, CSRF_TOKEN_COOKIE)
    assert session and csrf
    return session, csrf


# (path, method, body, expected_bot_call | None)
# Routes that mutate module governance_state directly (set_mode, set_risk_profile)
# use expected_bot_call == "GOVERNANCE_STATE" and are verified separately.
ROUTE_CASES = [
    ("/api/bot/start", "POST",
     {"symbol": "BTCUSDT", "risk_percent": 1,
      "sl_percent": 1, "leverage": 5, "mode": "paper"},
     "start"),
    ("/api/bot/stop", "POST", None, "stop"),
    ("/api/bot/loop/start", "POST", None, "start_loop"),
    ("/api/bot/loop/stop", "POST", None, "stop_loop"),
    ("/api/bot/live-auto/approve", "POST",
     {"approvalIdentity": "operator",
      "approvalSource": "EXPLICIT_OPERATOR_APPROVAL",
      "ttlSeconds": 600},
     "approve_live_auto_control"),
    ("/api/bot/live-auto/start", "POST", None, "start_live_auto_control"),
    ("/api/bot/live-auto/stop", "POST", None, "stop_live_auto_control"),
    ("/api/bot/paper-account/capital", "POST", {"capital": "100"},
     "reset_paper_capital"),
    ("/api/governance/mode", "POST", {"mode": "SAFE"}, "GOVERNANCE_STATE"),
    ("/api/governance/execution", "POST", {"enabled": True},
     "set_execution_enabled"),
    ("/api/governance/risk-profile", "POST", {"risk_profile": "SAFE"},
     "GOVERNANCE_STATE"),
    ("/api/governance/emergency-stop", "POST", None, "GOVERNANCE_STATE"),
    ("/api/governance/emergency-orchestrate", "POST", None,
     "run_emergency_orchestrator"),
    ("/api/governance/emergency/unlock", "POST", None,
     "_set_lifecycle_state:STOPPED"),
    ("/api/governance/emergency/retry", "POST", None,
     "retry_emergency_orchestrator"),
    ("/api/runtime/stopped-paper-safety/refresh", "POST", None,
     "refresh_stopped_paper_safety_authority"),
    ("/api/runtime/paper-auto/start", "POST", None,
     "start_auto_market_selection_runtime"),
    ("/api/runtime/paper-auto/cycle", "POST", None,
     "run_auto_market_selection_cycle"),
    ("/api/runtime/paper-auto/stop", "POST", None,
     "stop_auto_market_selection_runtime"),
]

# Routes WITHOUT a payload body (used to keep denied requests body-free).
BODYLESS_ROUTES = {
    path for path, method, body, _name in ROUTE_CASES if body is None
}


def _request(client, path, method, body, cookies=None, headers=None):
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["headers"]["Content-Type"] = "application/json"
        kwargs["json"] = body
    if cookies:
        kwargs["cookies"] = cookies
    return client.request(method, path, **kwargs)


class TestOperationControlAuthBoundary:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = _build_control_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.bot = FakeBotManager()
        self._bot_patch = patch(
            "backend.api.bot_api.get_bot_manager", return_value=self.bot
        )
        self._gov_patch = patch(
            "backend.api.governance.get_bot_manager", return_value=self.bot
        )
        self._runtime_patch = patch(
            "backend.api.runtime.get_bot_manager", return_value=self.bot
        )
        self._bot_patch.start()
        self._gov_patch.start()
        self._runtime_patch.start()
        self._state_saved = dict(governance_state)
        yield
        self._runtime_patch.stop()
        self._gov_patch.stop()
        self._bot_patch.stop()
        governance_state.clear()
        governance_state.update(self._state_saved)

    def _assert_denied_no_mutation(
        self, path, method, body, session=None, csrf=None, csrf_header=None
    ):
        cookies = {}
        if session:
            cookies[COOKIE_NAME] = session
        if csrf:
            cookies[CSRF_TOKEN_COOKIE] = csrf
        headers = {}
        if csrf_header:
            headers[CSRF_TOKEN_HEADER] = csrf_header
        before_calls = len(self.bot.calls)
        before_state = dict(governance_state)
        resp = _request(
            self.client, path, method, body, cookies=cookies, headers=headers
        )
        assert resp.status_code in (401, 403), (
            f"{method} {path} expected 401/403, got {resp.status_code}: {resp.text}"
        )
        assert len(self.bot.calls) == before_calls, (
            f"denied {method} {path} still mutated bot runtime: {self.bot.calls}"
        )
        assert governance_state == before_state, (
            f"denied {method} {path} still mutated governance state: "
            f"{governance_state}"
        )

    def test_no_session_denied(self):
        for path, method, body, _name in ROUTE_CASES:
            self._assert_denied_no_mutation(path, method, body)

    def test_fake_forged_session_denied(self):
        _session, csrf = _login(self.client)
        for path, method, body, _name in ROUTE_CASES:
            self._assert_denied_no_mutation(
                path, method, body,
                session="forged.invalidsignature",
                csrf=csrf,
                csrf_header=csrf,
            )

    def test_invalid_session_denied(self):
        _session, csrf = _login(self.client)
        for path, method, body, _name in ROUTE_CASES:
            self._assert_denied_no_mutation(
                path, method, body,
                session="random.garbage",
                csrf=csrf,
                csrf_header=csrf,
            )

    def test_expired_session_denied(self):
        app = _build_control_app(session_ttl=0)
        client = TestClient(app, raise_server_exceptions=False)
        bot = FakeBotManager()
        with patch(
            "backend.api.bot_api.get_bot_manager", return_value=bot
        ), patch(
            "backend.api.governance.get_bot_manager", return_value=bot
        ), patch(
            "backend.api.runtime.get_bot_manager", return_value=bot
        ):
            resp = client.post(
                "/api/auth/login", json={"credential": TEST_CREDENTIAL}
            )
            assert resp.status_code == 200
            session = _extract_cookie(resp, COOKIE_NAME)
            csrf = _extract_cookie(resp, CSRF_TOKEN_COOKIE)
            before_state = dict(governance_state)
            for path, method, body, _name in ROUTE_CASES:
                before = len(bot.calls)
                r = _request(
                    client, path, method, body,
                    cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                    headers={CSRF_TOKEN_HEADER: csrf},
                )
                assert r.status_code in (401, 403), (
                    f"expired-session {method} {path} got {r.status_code}: {r.text}"
                )
                assert len(bot.calls) == before
                assert governance_state == before_state

    def test_authenticated_missing_csrf_denied(self):
        session, _csrf = _login(self.client)
        for path, method, body, _name in ROUTE_CASES:
            before = len(self.bot.calls)
            before_state = dict(governance_state)
            r = _request(
                self.client, path, method, body,
                cookies={COOKIE_NAME: session},
            )
            assert r.status_code == 403, (
                f"{method} {path} missing CSRF got {r.status_code}: {r.text}"
            )
            assert len(self.bot.calls) == before
            assert governance_state == before_state

    def test_authenticated_bad_csrf_denied(self):
        session, csrf = _login(self.client)
        bad = "0" * 64
        assert bad != csrf
        for path, method, body, _name in ROUTE_CASES:
            before = len(self.bot.calls)
            before_state = dict(governance_state)
            r = _request(
                self.client, path, method, body,
                cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                headers={CSRF_TOKEN_HEADER: bad},
            )
            assert r.status_code == 403, (
                f"{method} {path} bad CSRF got {r.status_code}: {r.text}"
            )
            assert len(self.bot.calls) == before
            assert governance_state == before_state

    def test_authenticated_valid_csrf_reaches_handlers(self):
        session, csrf = _login(self.client)
        for path, method, body, handler_name in ROUTE_CASES:
            before = len(self.bot.calls)
            r = _request(
                self.client, path, method, body,
                cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                headers={CSRF_TOKEN_HEADER: csrf},
            )
            assert r.status_code not in (401, 403), (
                f"{method} {path} valid auth+csrf rejected: "
                f"{r.status_code}: {r.text}"
            )
            if handler_name == "GOVERNANCE_STATE":
                continue
            if handler_name is not None:
                assert handler_name in self.bot.calls, (
                    f"{method} {path} handler {handler_name} not called: "
                    f"{self.bot.calls}"
                )
            assert len(self.bot.calls) > before, (
                f"{method} {path} did not reach handler: {self.bot.calls}"
            )

    def test_authenticated_valid_csrf_reaches_mode_and_risk_handlers(self):
        session, csrf = _login(self.client)
        before_state = dict(governance_state)
        try:
            governance_state["mode"] = "STALE"
            r = _request(
                self.client,
                "/api/governance/mode",
                "POST",
                {"mode": "SAFE"},
                cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                headers={CSRF_TOKEN_HEADER: csrf},
            )
            assert r.status_code == 200, r.text
            assert r.json()["mode"] == "SAFE"
            assert governance_state["mode"] == "SAFE"

            governance_state["risk_profile"] = "STALE"
            r2 = _request(
                self.client,
                "/api/governance/risk-profile",
                "POST",
                {"risk_profile": "CONSERVATIVE"},
                cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                headers={CSRF_TOKEN_HEADER: csrf},
            )
            assert r2.status_code == 200, r2.text
            assert r2.json()["risk_profile"] == "CONSERVATIVE"
            assert governance_state["risk_profile"] == "CONSERVATIVE"
        finally:
            governance_state.clear()
            governance_state.update(before_state)

    def test_authenticated_valid_csrf_emergency_stop_reaches_handler(self):
        session, csrf = _login(self.client)
        before_state = dict(governance_state)
        try:
            governance_state["emergency_stop"] = False
            r = _request(
                self.client,
                "/api/governance/emergency-stop",
                "POST",
                None,
                cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
                headers={CSRF_TOKEN_HEADER: csrf},
            )
            assert r.status_code == 200, r.text
            assert r.json()["success"] is True
            assert r.json()["emergency_stop"] is True
            assert governance_state["emergency_stop"] is True
        finally:
            governance_state.clear()
            governance_state.update(before_state)


class TestOperationControlRouteEnforcement:
    def test_control_routes_registered_with_session_dependency(self):
        registered = set()
        routers = [
            (bot_api.router, "/api/bot"),
            (governance.router, ""),
            (runtime.router, ""),
        ]
        for router, include_prefix in routers:
            for route in router.routes:
                has_dependency = False
                for dependency in route.dependant.dependencies:
                    call = dependency.call
                    if call is not None and (
                        call is require_operator_session
                        or getattr(call, "__name__", None) == "require_operator_session"
                    ):
                        has_dependency = True
                        break
                if has_dependency:
                    registered.add(include_prefix + route.path)
        assert registered == SUPPORTED_PROTECTED_PATHS, (
            f"control routes with session dependency mismatch: {registered}"
        )

    def test_main_definition_csrf_paths_superset(self):
        # main.py loads heavy module-level composition and must not be imported
        # here. Read the `_csrf_protected` frozenset literal from source and
        # assert it is a superset of every Operation control route.
        import re
        from pathlib import Path

        source = Path("backend/main.py").read_text(encoding="utf-8")
        block = re.search(
            r"_csrf_protected = frozenset\(\{(.*?)\}\)",
            source,
            re.DOTALL,
        )
        assert block is not None, "could not locate _csrf_protected in main.py"
        declared = frozenset(
            re.findall(r'"([^"]+)"', block.group(1))
        )
        assert SUPPORTED_PROTECTED_PATHS <= declared, (
            f"main.py CSRF set missing required control routes: "
            f"{SUPPORTED_PROTECTED_PATHS - declared}"
        )
