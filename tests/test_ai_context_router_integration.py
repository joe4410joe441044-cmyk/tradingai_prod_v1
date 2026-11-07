"""Source integration tests for the authenticated context router.

The production application module is not imported. Its startup hook creates a
bot manager and starts the supervisor control plane. Route behavior is checked
on an isolated app that mounts the same router and the existing session
middleware.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.dependencies import require_operator_session
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.context.api_contract import (
    OPERATOR_JSON_PATH,
    OPERATOR_MARKDOWN_PATH,
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
from backend.context.source_truth import read_source_truth
from tests.test_ai_context_support import FIXED_NOW

REPO = Path(__file__).resolve().parents[1]
MAIN = REPO / "backend/main.py"
SECRET = "supersecretvalue-bb4c"
BALANCE = 424242.5
SESSION_SECRET = "c" * 32
PRESERVED_REGISTRATIONS = (
    "governance_router",
    "runtime_api_router",
    "money_management_router",
    "parameter_settings_router",
    "trade_history_router",
    "trading_trace_router",
    "supervisor_router",
    "mode_router",
    "portfolio_router",
    "config_router",
    "logs_router",
    "bot_api.router",
    "OperatorSessionMiddleware",
    "OperatorCsrfProtection",
)


def _main_text() -> str:
    return MAIN.read_text(encoding="utf-8")


def _config() -> OperatorAuthConfig:
    return OperatorAuthConfig(session_secret=SESSION_SECRET, session_ttl_seconds=3600)


def _inputs(**overrides) -> ContextReadInputs:
    payload = {"generated_at": FIXED_NOW}
    payload.update(overrides)
    return ContextReadInputs(**payload)


def _app(ttl: int = 3600, inputs: ContextReadInputs | None = None):
    manager = OperatorSessionManager(SESSION_SECRET, session_ttl_seconds=ttl)
    app = create_isolated_context_app(session_manager=manager, config=_config())
    if inputs is not None:
        app.dependency_overrides[context_read_inputs] = lambda: inputs
    return app, manager


def _cookie(manager: OperatorSessionManager) -> dict[str, str]:
    session = manager.create_session("operator")
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


def test_01_context_router_mounted_once():
    text = _main_text()
    assert text.count("from backend.context.api_router import context_router") == 1
    assert text.count("app.include_router(context_router)") == 1
    assert "create_isolated_context_app" not in text


def test_02_json_endpoint_registered():
    paths = {route.path for route in context_router.routes}
    assert OPERATOR_JSON_PATH in paths


def test_03_markdown_endpoint_registered():
    paths = {route.path for route in context_router.routes}
    assert OPERATOR_MARKDOWN_PATH in paths


def test_04_no_duplicate_routes():
    paths = [route.path for route in context_router.routes]
    assert paths.count(OPERATOR_JSON_PATH) == 1
    assert paths.count(OPERATOR_MARKDOWN_PATH) == 1
    assert len(paths) == len(set(paths))


def test_05_no_public_endpoint():
    text = _main_text()
    assert "/api/ai-context/public" not in text
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert all("public" not in route.path for route in context_router.routes)


def test_06_existing_operator_session_middleware_retained():
    text = _main_text()
    assert "from backend.auth.session_middleware import OperatorSessionMiddleware" in text
    assert "app.add_middleware(\n        OperatorSessionMiddleware," in text


def test_07_require_operator_session_retained():
    for route in context_router.routes:
        assert isinstance(route, APIRoute)
        assert require_operator_session in _route_calls(route)
        assert route.methods == {"GET"}


def test_08_unauthenticated_request_401():
    app, _manager = _app(inputs=_inputs(account_projection={"mode": "PAPER", "balance": BALANCE}))
    assert require_operator_session not in app.dependency_overrides
    response = _client(app).get(OPERATOR_JSON_PATH)
    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "UNAUTHENTICATED"
    assert "424242.5" not in response.text


def test_09_invalid_signature_401():
    app, _manager = _app(inputs=_inputs(account_projection={"balance": BALANCE}))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies={COOKIE_NAME: "random.invalidsig"})
    assert response.status_code == 401
    assert "424242.5" not in response.text


def test_10_expired_session_401():
    app, manager = _app(ttl=0, inputs=_inputs(account_projection={"balance": BALANCE}))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 401
    assert "424242.5" not in response.text


def test_11_authenticated_json_200():
    app, manager = _app(inputs=_inputs())
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "OPERATOR_CONTEXT"
    assert body["productionRuntimeConnected"] is False
    assert body["productionApiAvailable"] is False


def test_12_authenticated_markdown_200():
    app, manager = _app(inputs=_inputs())
    response = _client(app).get(OPERATOR_MARKDOWN_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "OPERATOR_CONTEXT" in response.text
    assert "productionRuntimeConnected" in response.text


def test_13_no_raw_context_leakage():
    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    app, manager = _app(inputs=_inputs(source_truth=source))
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    assert response.status_code == 200
    assert str(REPO) not in response.text
    assert "worktrees" not in response.text
    assert '"repository"' not in response.text


def test_14_no_secret_leakage():
    app, manager = _app(
        inputs=_inputs(
            account_projection={"mode": "PAPER", "balance": 12, "source": "PAPER", "apiKey": SECRET},
            mm_projection={"blockers": [f"Bearer {SECRET}"]},
        )
    )
    response = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager))
    markdown = _client(app).get(OPERATOR_MARKDOWN_PATH, cookies=_cookie(manager))
    assert SECRET not in response.text
    assert SECRET not in markdown.text
    assert "Bearer" not in response.text


def test_15_no_absolute_path_in_public_view():
    from backend.context import collect_runtime_context
    from backend.context.context_views import build_public_context_view, view_to_json

    source = read_source_truth(REPO, observed_at=FIXED_NOW)
    collected = collect_runtime_context(generated_at=FIXED_NOW, source_truth=source)
    public = view_to_json(build_public_context_view(collected.context))
    assert str(REPO) not in public
    assert "/home/" not in public


def test_16_runtime_not_connected():
    router_source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    main = _main_text()
    for token in ("get_bot_manager", "get_status", "get_result"):
        assert token not in router_source
    assert "get_bot_manager" not in main[main.rfind("AI CONTEXT"):]
    assert PRODUCTION_RUNTIME_CONNECTED is False


def test_17_reader_not_injected_preserved():
    _status, body = build_operator_http_body(_inputs())
    categories = {item["category"] for item in body["context"]["readerFailures"]}
    assert "READER_NOT_INJECTED" in categories
    assert categories == {"READER_NOT_INJECTED"}


def test_18_production_runtime_connected_false():
    app, manager = _app(inputs=_inputs())
    body = _client(app).get(OPERATOR_JSON_PATH, cookies=_cookie(manager)).json()
    assert body["productionRuntimeConnected"] is False
    assert body["productionApiAvailable"] is False
    assert PRODUCTION_API_AVAILABLE is False


def test_19_no_bot_start_or_stop():
    added = _main_text().split("# ------------------------------------------------------------\n# AI CONTEXT", 1)[1]
    added = added.split("# ============================================================\n# ROOT", 1)[0]
    for token in ("start_bot", "stop_bot", "get_bot_manager", "place_order"):
        assert token not in added
    assert {method for route in context_router.routes for method in route.methods} == {"GET"}


def test_20_no_authority_mutation():
    source = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
    assert "set_authority" not in source
    assert "saved-mode" not in _main_text().split("# AI CONTEXT", 1)[1].split("# ROOT", 1)[0]


def test_21_no_emergency_mutation():
    added = _main_text().split("# AI CONTEXT", 1)[1].split("# ROOT", 1)[0]
    for token in ("emergency_stop", "emergency_unlock", "emergency-orchestrate"):
        assert token not in added


def test_22_no_exchange_api_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network socket opened")

    monkeypatch.setattr("socket.socket", boom)
    status, body = build_operator_http_body(_inputs())
    assert status == 200
    assert body["productionRuntimeConnected"] is False


def test_23_no_real_order():
    added = _main_text().split("# AI CONTEXT", 1)[1].split("# ROOT", 1)[0]
    for token in ("manual-trade", "live-order", "submit_order", "place_order"):
        assert token not in added


def test_24_existing_api_routes_preserved():
    text = _main_text()
    for name in PRESERVED_REGISTRATIONS:
        assert name in text


def test_25_regression_markers_for_prior_context_phases():
    from backend.context import SCHEMA_VERSION, collect_runtime_context

    collected = collect_runtime_context(generated_at=FIXED_NOW)
    assert collected.context.schemaVersion == SCHEMA_VERSION
    assert collected.production_runtime_connected is False
    assert collected.public_view["view"] == "PUBLIC_CONTEXT"
    assert collected.operator_view["view"] == "OPERATOR_CONTEXT"
