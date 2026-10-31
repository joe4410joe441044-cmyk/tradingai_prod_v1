"""Offline tests for the unmounted authenticated context router.

Authentication uses the existing operator session middleware. These tests do
not call Production, an exchange, or the live bot.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.dependencies import require_operator_session
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.context import SCHEMA_VERSION, build_canonical_context, collect_runtime_context
from backend.context.api_contract import (
    OPERATOR_JSON_PATH,
    OPERATOR_MARKDOWN_PATH,
    PAYLOAD_LIMIT_EXCEEDED,
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
    PUBLIC_ENDPOINT_ENABLED,
)
from backend.context.api_router import (
    ContextReadInputs,
    build_operator_http_body,
    context_read_inputs,
    context_router,
    create_isolated_context_app,
)
from backend.context.context_views import build_public_context_view, view_to_json, view_to_markdown
from backend.context.source_truth import read_source_truth
from tests.test_ai_context_support import FIXED_NOW, make_supervisor_snapshot

REPO = Path(__file__).resolve().parents[1]
SECRET = "supersecretvalue-bb4b"
BALANCE = 424242.5
SESSION_SECRET = "b" * 32


def _config(ttl: int = 3600) -> OperatorAuthConfig:
    return OperatorAuthConfig(session_secret=SESSION_SECRET, session_ttl_seconds=ttl)


def _inputs(**overrides) -> ContextReadInputs:
    payload = {"generated_at": FIXED_NOW}
    payload.update(overrides)
    return ContextReadInputs(**payload)


def _app(ttl: int = 3600, inputs: ContextReadInputs | None = None):
    manager = OperatorSessionManager(SESSION_SECRET, session_ttl_seconds=ttl)
    app = create_isolated_context_app(session_manager=manager, config=_config(ttl))
    if inputs is not None:
        app.dependency_overrides[context_read_inputs] = lambda: inputs
    return app, manager


def _cookie(manager: OperatorSessionManager, identity: str = "operator") -> dict[str, str]:
    session = manager.create_session(identity)
    return {COOKIE_NAME: manager.sign(session.session_id)}


def _client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _route_calls(route: APIRoute) -> list[object]:
    found: list[object] = []

    def walk(dependant) -> None:
        for dependency in dependant.dependencies:
            if dependency.call is not None:
                found.append(dependency.call)
            walk(dependency)

    walk(route.dependant)
    return found


def _section_fields(body: dict, name: str) -> list[dict]:
    return body["context"]["sections"][name]["fields"]


def test_01_schema_compatibility():
    context = collect_runtime_context(generated_at=FIXED_NOW).context
    assert context.schemaVersion == SCHEMA_VERSION == "tradingai-context/v1"
    status, body = build_operator_http_body(_inputs())
    assert status == 200
    assert body["context"]["schemaVersion"] == SCHEMA_VERSION
    assert body["productionRuntimeConnected"] is False


def test_02_require_operator_session_dependency_present():
    paths = set()
    for route in context_router.routes:
        assert isinstance(route, APIRoute)
        assert require_operator_session in _route_calls(route)
        paths.add(route.path)
    assert paths == {OPERATOR_JSON_PATH, OPERATOR_MARKDOWN_PATH}
    assert not any("public" in path for path in paths)
    assert PUBLIC_ENDPOINT_ENABLED is False


def test_03_unauthenticated_request_rejected():
    app, _manager = _app(inputs=_inputs(account_projection={"mode": "PAPER", "balance": BALANCE, "apiKey": SECRET}))
    assert require_operator_session not in app.dependency_overrides
    response = _client(app).get(OPERATOR_JSON_PATH)
    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "UNAUTHENTICATED"
    assert "424242.5" not in response.text
    assert SECRET not in response.text
    assert "context" not in response.json()


def test_04_invalid_session_rejected():
    app, _manager = _app(inputs=_inputs(account_projection={"balance": BALANCE}))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies={COOKIE_NAME: "random.invalidsig"})
    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "UNAUTHENTICATED"
    assert "424242.5" not in response.text


def test_05_expired_session_rejected():
    app, manager = _app(ttl=0, inputs=_inputs(account_projection={"balance": BALANCE}))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "UNAUTHENTICATED"
    assert "424242.5" not in response.text


def test_06_authenticated_operator_accepted():
    app, manager = _app()
    assert require_operator_session not in app.dependency_overrides
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OK"
    assert body["view"] == "OPERATOR_CONTEXT"
    assert body["context"]["authentication"] == "NOT_ASSERTED"
    assert body["productionRuntimeConnected"] is False
    assert body["productionApiAvailable"] is False


def test_07_no_raw_canonical_pack_leakage():
    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    app, manager = _app(inputs=_inputs(source_truth=source))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    text = response.text
    assert str(REPO) not in text
    assert "worktrees" not in text
    assert '"repository"' not in text


def test_08_no_secrets_in_response():
    app, manager = _app(
        inputs=_inputs(
            account_projection={
                "mode": "PAPER",
                "balance": 12,
                "source": "PAPER",
                "apiKey": SECRET,
                "password": SECRET,
            },
            mm_projection={"blockers": [f"Bearer {SECRET}"], "api_key": SECRET},
        )
    )
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    assert SECRET not in response.text
    assert "apiKey" not in response.text
    assert "Bearer" not in response.text


def test_09_no_internal_paths_in_public_view():
    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    collected = collect_runtime_context(generated_at=FIXED_NOW, source_truth=source)
    public = view_to_json(build_public_context_view(collected.context))
    assert str(REPO) not in public
    assert "/home/" not in public
    assert "worktrees" not in public


def test_10_no_account_in_public_view():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        account_projection={
            "selectedMode": "PAPER",
            "paperAccount": {"balance": BALANCE, "source": "PAPER"},
            "realAccount": {"balance": 9, "source": "LIVE"},
        },
    )
    public = view_to_json(build_public_context_view(collected.context))
    assert "424242.5" not in public
    assert "paperBalance" not in public


def test_11_no_position_in_public_view():
    collected = collect_runtime_context(
        generated_at=FIXED_NOW,
        position_view={
            "status": "OPEN",
            "mode": "PAPER",
            "symbol": "XRPUSDTM",
            "side": "LONG",
            "quantity": 2,
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
        },
    )
    public = view_to_json(build_public_context_view(collected.context))
    assert "XRPUSDTM" not in public
    assert "avgEntry" not in public


def test_12_operator_allowlist_enforced():
    app, manager = _app(
        inputs=_inputs(
            execution_projection={
                "selectedMode": "PAPER",
                "realOrderAllowed": False,
                "futureMetric": "998877",
            }
        )
    )
    body = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager)).json()
    assert set(body) == {
        "status",
        "view",
        "productionRuntimeConnected",
        "productionApiAvailable",
        "publicEndpointEnabled",
        "context",
    }
    names = {item["name"] for item in _section_fields(body, "executionControl")}
    assert "selectedMode" in names
    assert "futureMetric" not in names
    assert "998877" not in view_to_json(body)


def test_13_unknown_fields_excluded():
    status, body = build_operator_http_body(
        _inputs(position_view={
            "status": "FLAT",
            "mode": "PAPER",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
            "futureMetric": "998877",
            "apiKey": SECRET,
        })
    )
    rendered = view_to_json(body)
    assert status == 200
    assert "futureMetric" not in rendered
    assert "998877" not in rendered
    assert SECRET not in rendered


def test_14_nested_secrets_excluded():
    status, body = build_operator_http_body(
        _inputs(mm_projection={
            "availableCapital": "5",
            "apiKey": {"nested": {"password": SECRET, "token": SECRET}},
            "blockers": [{"note": f"Bearer {SECRET}"}, "visible"],
        })
    )
    rendered = view_to_json(body)
    assert status == 200
    assert SECRET not in rendered
    assert "password" not in rendered
    assert "Bearer" not in rendered


def test_15_payload_limit_enforced():
    app, manager = _app(
        inputs=_inputs(
            account_projection={"mode": "PAPER", "balance": BALANCE, "source": "PAPER"},
            max_bytes=96,
        )
    )
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 413
    body = response.json()
    assert body["status"] == PAYLOAD_LIMIT_EXCEEDED
    assert "424242.5" not in response.text
    assert body["context"]["reason"] == PAYLOAD_LIMIT_EXCEEDED


def test_16_runtime_not_injected():
    app, manager = _app(inputs=_inputs())
    body = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager)).json()
    assert body["productionRuntimeConnected"] is False
    assert PRODUCTION_RUNTIME_CONNECTED is False
    assert PRODUCTION_API_AVAILABLE is False
    failures = {item["source"]: item["category"] for item in body["context"]["readerFailures"]}
    assert failures["position"] == "READER_NOT_INJECTED"
    assert failures["account"] == "READER_NOT_INJECTED"


def test_17_reader_not_injected_preserved():
    _status, body = build_operator_http_body(_inputs())
    categories = {item["category"] for item in body["context"]["readerFailures"]}
    assert categories == {"READER_NOT_INJECTED"}
    assert "CURRENT" not in {
        item.get("value")
        for item in _section_fields(body, "tradingCycle")
        if item.get("name") == "diagnosticScope"
    }


def test_18_unknown_preserved():
    status, body = build_operator_http_body(
        _inputs(position_view={
            "status": "UNKNOWN",
            "mode": "PAPER",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
            "reason": "MODE_UNRESOLVED",
        })
    )
    assert status == 200
    fields = {item["name"]: item for item in _section_fields(body, "position")}
    assert fields["status"]["value"] == "UNKNOWN"
    assert fields["status"]["value"] != "OPEN"


def test_19_unavailable_preserved():
    _status, body = build_operator_http_body(_inputs())
    account = body["context"]["sections"]["account"]["meta"]
    assert account["availability"] == "UNAVAILABLE"
    assert account["freshness"] == "UNKNOWN"
    currency = {
        item["name"]: item
        for item in _section_fields(
            build_operator_http_body(
                _inputs(account_projection={"mode": "PAPER", "balance": 3, "source": "PAPER"})
            )[1],
            "account",
        )
    }
    assert currency["currency"]["state"] == "UNAVAILABLE"


def test_20_no_exchange_api_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network socket opened")

    monkeypatch.setattr("socket.socket", boom)
    status, body = build_operator_http_body(_inputs())
    assert status == 200
    assert body["productionRuntimeConnected"] is False


def test_21_no_bot_start_or_stop():
    source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    for name in imported:
        assert "bot_manager" not in name
        assert "kucoin" not in name
        assert name != "backend.main"
    for token in ("get_bot_manager", "get_status", "get_result", "start_bot", "stop_bot", "place_order"):
        assert token not in source


def test_22_no_authority_mutation():
    source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    assert "set_authority" not in source
    assert "controlAuthority" not in source or "realOrderAllowed" not in source
    main = (REPO / "backend/main.py").read_text(encoding="utf-8")
    assert main.count("app.include_router(context_router)") == 1
    assert "create_isolated_context_app" not in main
    assert "/api/ai-context/public" not in main


def test_23_no_emergency_mutation():
    source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    for token in ("emergency_stop", "emergency_unlock", "trigger_emergency", "clear_emergency"):
        assert token not in source
    methods = {method for route in context_router.routes for method in route.methods}
    assert methods == {"GET"}


def test_24_deterministic_json():
    app, manager = _app(inputs=_inputs(execution_projection={"selectedMode": "PAPER", "realOrderAllowed": False}))
    client = _client(app)
    cookies = _cookie(manager)
    first = client.get(OPERATOR_JSON_PATH, cookies=cookies).text
    second = client.get(OPERATOR_JSON_PATH, cookies=cookies).text
    assert first == second


def test_25_markdown_safe_rendering():
    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    app, manager = _app(
        inputs=_inputs(
            source_truth=source,
            account_projection={"mode": "PAPER", "balance": BALANCE, "source": "PAPER", "apiKey": SECRET},
        )
    )
    response = _client(app).get(OPERATOR_MARKDOWN_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "OPERATOR_CONTEXT" in response.text
    assert "productionRuntimeConnected" in response.text
    assert str(REPO) not in response.text
    assert SECRET not in response.text
    router_source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    assert "serializer" not in router_source
    assert "view_to_markdown" in router_source


def test_26_json_markdown_scope_parity():
    inputs = _inputs(execution_projection={"selectedMode": "MANUAL", "realOrderAllowed": False})
    status, body = build_operator_http_body(inputs)
    assert status == 200
    raw = view_to_json(body)
    markdown = view_to_markdown(body)
    assert "OPERATOR_CONTEXT" in markdown
    assert "productionRuntimeConnected" in markdown
    assert "`false`" in markdown

    def leaves(value, prefix=""):
        if isinstance(value, dict):
            for key in sorted(value):
                path = f"{prefix}.{key}" if prefix else key
                yield from leaves(value[key], path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from leaves(item, f"{prefix}[{index}]")
        else:
            yield prefix

    for path in leaves(body):
        assert path in markdown
    assert view_to_json(body) == raw


def test_27_isolated_fastapi_app_integration():
    app, manager = _app(inputs=_inputs(supervisor_snapshot=make_supervisor_snapshot()))
    client = _client(app)
    denied = client.get(OPERATOR_JSON_PATH)
    assert denied.status_code == 401
    allowed = client.get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert allowed.status_code == 200
    assert allowed.json()["context"]["sections"]["runtime"]["meta"]["availability"] != "UNAVAILABLE"
    assert require_operator_session not in app.dependency_overrides
    main = (REPO / "backend/main.py").read_text(encoding="utf-8")
    assert main.count("app.include_router(context_router)") == 1


def test_28_existing_context_regression_entry_points():
    built = build_canonical_context(generated_at=FIXED_NOW)
    assert built.schemaVersion == SCHEMA_VERSION
    collected = collect_runtime_context(
        generated_at=FIXED_NOW + timedelta(0),
        supervisor_snapshot=make_supervisor_snapshot(),
    )
    assert collected.production_runtime_connected is False
    assert collected.context.safety.orderWrite is False
    aware = datetime(2026, 10, 25, tzinfo=timezone.utc)
    failed, body = build_operator_http_body(
        ContextReadInputs(generated_at=aware.replace(tzinfo=None))
    )
    assert failed == 500
    assert body["status"] == "CONTEXT_BUILD_FAILED"
    assert "Traceback" not in view_to_json(body)
    assert str(REPO) not in view_to_json(body)
