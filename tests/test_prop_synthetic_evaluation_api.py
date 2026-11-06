from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.prop_synthetic_evaluation import (
    MAX_REQUEST_BYTES,
    SyntheticPropSessionStore,
    create_prop_synthetic_router,
)
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import CSRF_TOKEN_COOKIE, CSRF_TOKEN_HEADER, OperatorCsrfProtection
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.prop_trading.synthetic_feature import prop_isolated_demo_enabled

PATHS = frozenset({
    "/api/prop-accounts/synthetic/accounts",
    "/api/prop-accounts/synthetic/accounts/revise",
    "/api/prop-accounts/synthetic/evaluate",
})


def account_request(request_id="account-1"):
    return {
        "requestId": request_id,
        "label": "Synthetic Challenge",
        "phase": "CHALLENGE",
        "currency": "USDT",
    }


def evaluation_request(account):
    return {
        "requestId": "evaluation-1",
        "accountId": account["identity"]["account_id"],
        "identityRevision": account["identity"]["revision"],
        "rules": {
            "initialBalance": "100000",
            "maximumLossPct": "6",
            "dailyLossPct": "4",
            "profitTargetPct": "10",
        },
        "baseline": {
            "referenceValue": "100000",
            "tradingDay": "2026-11-04",
            "timezone": "UTC",
            "dayBoundaryLocalTime": "00:00:00",
        },
        "observation": {
            "balance": "101000",
            "equity": "100500",
            "realizedPnl": "1000",
            "unrealizedPnl": "-500",
            "observedAt": "2026-11-04T02:00:00Z",
            "receivedAt": "2026-11-04T02:00:01Z",
        },
        "evaluation": {"evaluatedAt": "2026-11-04T02:00:02Z"},
    }


def build_client(enabled=True):
    config = OperatorAuthConfig(
        credential_hash=None,
        session_secret="test-session-secret-at-least-16",
        session_ttl_seconds=3600,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
    )
    manager = OperatorSessionManager(config.session_secret, config.session_ttl_seconds)
    store = SyntheticPropSessionStore()
    app = FastAPI()
    app.add_middleware(OperatorSessionMiddleware, session_manager=manager, config=config)
    app.add_middleware(OperatorCsrfProtection, csrf_required_paths=PATHS)
    app.include_router(create_prop_synthetic_router(enabled=lambda: enabled, store=store))
    return TestClient(app, raise_server_exceptions=False), manager, store


def auth(manager, identity="operator"):
    session = manager.create_session(identity)
    token = f"csrf-{identity}"
    return (
        {COOKIE_NAME: manager.sign(session.session_id), CSRF_TOKEN_COOKIE: token},
        {CSRF_TOKEN_HEADER: token, "Origin": "http://testserver"},
    )


def test_feature_flag_is_strict_and_default_off(monkeypatch):
    monkeypatch.delenv("PROP_ISOLATED_DEMO_ENABLED", raising=False)
    assert prop_isolated_demo_enabled() is False
    assert prop_isolated_demo_enabled({"PROP_ISOLATED_DEMO_ENABLED": "true"}) is True
    for invalid in ("TRUE", "True", "1", "yes", " true ", ""):
        assert prop_isolated_demo_enabled({"PROP_ISOLATED_DEMO_ENABLED": invalid}) is False


def test_disabled_response_is_fixed_and_does_not_allocate_session_state():
    client, manager, store = build_client(enabled=False)
    cookies, headers = auth(manager)
    response = client.post(next(iter(PATHS)), json=account_request(), cookies=cookies, headers=headers)
    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": {"code": "PROP_DEMO_DISABLED", "message": "isolated PROP demo is disabled", "fields": {}},
    }
    assert store.size == 0


def test_auth_csrf_and_same_origin_fail_closed_without_cors():
    client, manager, store = build_client()
    cookies, headers = auth(manager)
    path = "/api/prop-accounts/synthetic/accounts"
    unauthenticated = client.post(
        path,
        json=account_request(),
        cookies={CSRF_TOKEN_COOKIE: "anonymous"},
        headers={"Origin": "http://testserver", CSRF_TOKEN_HEADER: "anonymous"},
    )
    assert unauthenticated.status_code == 401
    assert client.post(path, json=account_request(), cookies=cookies, headers={"Origin": "http://testserver"}).status_code == 403
    invalid_csrf = client.post(
        path,
        json=account_request(), cookies=cookies,
        headers={"Origin": "http://testserver", CSRF_TOKEN_HEADER: "wrong"},
    )
    assert invalid_csrf.status_code == 403
    rejected = client.post(path, json=account_request(), cookies=cookies, headers={**headers, "Origin": "https://evil.example"})
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "ORIGIN_REJECTED"
    assert "access-control-allow-origin" not in rejected.headers
    assert store.size == 0


def test_create_evaluate_and_cross_session_isolation():
    client, manager, _store = build_client()
    cookies, headers = auth(manager, "one")
    created = client.post(
        "/api/prop-accounts/synthetic/accounts",
        json=account_request(), cookies=cookies, headers=headers,
    )
    assert created.status_code == 200 and created.json()["ok"] is True
    account = created.json()["account"]
    assert account["synthetic"] is True and account["persisted"] is False
    evaluated = client.post(
        "/api/prop-accounts/synthetic/evaluate",
        json=evaluation_request(account), cookies=cookies, headers=headers,
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["outcome"]["calculation"]["overallState"] == "PASS"
    assert evaluated.json()["authority"]["executionAuthorityGranted"] is False

    other_cookies, other_headers = auth(manager, "two")
    isolated = client.post(
        "/api/prop-accounts/synthetic/evaluate",
        json=evaluation_request(account), cookies=other_cookies, headers=other_headers,
    )
    assert isolated.status_code == 404
    assert isolated.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_expired_session_is_rejected_before_state_allocation():
    client, manager, store = build_client()
    session = manager.create_session("expired")
    token = "expired-csrf"
    manager._clock = lambda: session.expires_at + 1
    response = client.post(
        "/api/prop-accounts/synthetic/accounts",
        json=account_request(),
        cookies={COOKIE_NAME: manager.sign(session.session_id), CSRF_TOKEN_COOKIE: token},
        headers={"Origin": "http://testserver", CSRF_TOKEN_HEADER: token},
    )
    assert response.status_code == 401
    assert store.size == 0


def test_strict_json_media_type_duplicates_and_size_limit():
    client, manager, store = build_client()
    cookies, headers = auth(manager)
    path = "/api/prop-accounts/synthetic/accounts"
    text = client.post(path, content=b"{}", cookies=cookies, headers={**headers, "Content-Type": "text/plain"})
    assert text.status_code == 415
    duplicate = b'{"requestId":"one","requestId":"two","label":"Demo","phase":"CHALLENGE","currency":"USDT"}'
    rejected = client.post(path, content=duplicate, cookies=cookies, headers={**headers, "Content-Type": "application/json"})
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "INVALID_JSON"
    oversized = client.post(path, content=b"x" * (MAX_REQUEST_BYTES + 1), cookies=cookies, headers={**headers, "Content-Type": "application/json"})
    assert oversized.status_code == 413
    streamed = client.post(
        path,
        content=(chunk for chunk in (b"x" * 20000, b"y" * 20000)),
        cookies=cookies,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert streamed.status_code == 413
    for invalid in (b'{"requestId":NaN}', b'{"requestId":Infinity}', b'{'):
        response = client.post(
            path, content=invalid, cookies=cookies,
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_JSON"
    assert store.size == 0


def test_unknown_missing_revision_and_official_authority_injection_are_rejected_safely():
    client, manager, _store = build_client()
    cookies, headers = auth(manager)
    path = "/api/prop-accounts/synthetic/accounts"
    for payload in (
        {"requestId": "missing"},
        {**account_request(), "officialVerification": True},
    ):
        response = client.post(path, json=payload, cookies=cookies, headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_INPUT"
        assert "traceback" not in response.text.lower()
    account = client.post(path, json=account_request("valid"), cookies=cookies, headers=headers).json()["account"]
    request = evaluation_request(account)
    request["identityRevision"] += 1
    stale = client.post(
        "/api/prop-accounts/synthetic/evaluate", json=request,
        cookies=cookies, headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "ACCOUNT_REVISION_MISMATCH"
    request = evaluation_request(account)
    request["rules"]["verificationStatus"] = "VERIFIED_FOR_ACCOUNT"
    official = client.post(
        "/api/prop-accounts/synthetic/evaluate", json=request,
        cookies=cookies, headers=headers,
    )
    assert official.status_code == 422
    assert "VERIFIED_FOR_ACCOUNT" not in official.text


def test_api_preserves_pass_block_unknown_and_never_grants_authority():
    client, manager, _store = build_client()
    cookies, headers = auth(manager)
    account = client.post(
        "/api/prop-accounts/synthetic/accounts",
        json=account_request(), cookies=cookies, headers=headers,
    ).json()["account"]
    cases = (("100500", "PASS"), ("93000", "BLOCK"), (None, "UNKNOWN"))
    for equity, expected in cases:
        request = evaluation_request(account)
        request["observation"]["equity"] = equity
        if equity is None:
            request["observation"]["balance"] = None
        response = client.post(
            "/api/prop-accounts/synthetic/evaluate",
            json=request, cookies=cookies, headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["calculation"]["overallState"] == expected
        assert body["authority"] == {
            "executionAuthorityGranted": False,
            "runtimeReady": False,
            "tradeReady": False,
        }


def test_source_boundary_has_no_runtime_order_exchange_or_persistence_dependency():
    source = open("backend/api/prop_synthetic_evaluation.py", encoding="utf-8").read().lower()
    imports = "\n".join(line for line in source.splitlines() if line.startswith(("import ", "from ")))
    for forbidden in ("bot_manager", "execution", "exchange", "credential", "database", "backend.main"):
        assert forbidden not in imports
