"""Supervisor monitoring control-plane tests: authorization, trigger service,
POST route, control-plane status, flags and compatibility.

Temporary paths only.  No API route is enabled by default, no Production
database/lock/outbox is opened, and no monitoring run occurs.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.api_rate_limit import AdvisorRateLimiter
from backend.auth.csrf import CSRF_TOKEN_COOKIE, CSRF_TOKEN_HEADER, OperatorCsrfProtection
from backend.auth.dependencies import require_operator_session
from backend.api import supervisor_monitoring_control as control_api
from backend.api.supervisor_monitoring_control import (
    create_supervisor_monitoring_control_router,
)
from backend.supervisor.monitoring_alert_service import MonitoringAlertService
from backend.supervisor.monitoring_control_flags import (
    ADVISOR_ALERT_EXPLANATION_FLAG,
    ALERT_OUTBOX_FLAG,
    MANUAL_TRIGGER_API_FLAG,
    MONITORING_SCHEDULER_FLAG,
    resolve_control_flags,
)
from backend.supervisor.monitoring_trigger_coordinator import MonitoringTriggerCoordinator
from backend.supervisor.monitoring_trigger_idempotency_store import (
    MonitoringTriggerIdempotencyStore,
)
from backend.supervisor.monitoring_trigger_ownership import MonitoringTriggerOwnership
from backend.supervisor.monitoring_trigger_security import evaluate_trigger_flags
from backend.supervisor.supervisor_authorization import (
    AUTHORIZED_PRINCIPALS_ENV,
    SupervisorAuthorizationAuthority,
    load_supervisor_authorization_config,
)
from backend.supervisor.supervisor_control_plane import (
    ControlPlaneConfig,
    SupervisorControlPlane,
)
from backend.supervisor.supervisor_trigger_audit import SupervisorTriggerAuditStore
from backend.supervisor.supervisor_trigger_service import SupervisorTriggerService

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INSTANCE = "I" + "a" * 16
READY_FLAGS = evaluate_trigger_flags(api_raw="1", monitoring_raw="1")


# --- authorization ----------------------------------------------------------

def test_missing_config_denies(tmp_path):
    authority = SupervisorAuthorizationAuthority.from_environ({})
    assert authority.availability == "NOT_CONFIGURED"
    assert authority.decide("operator").allowed is False


def test_empty_allowlist_denies():
    authority = SupervisorAuthorizationAuthority(
        load_supervisor_authorization_config({AUTHORIZED_PRINCIPALS_ENV: "   "})
    )
    assert authority.availability == "NOT_CONFIGURED"
    assert authority.decide("operator").allowed is False


def test_malformed_config_denies():
    authority = SupervisorAuthorizationAuthority(
        load_supervisor_authorization_config({AUTHORIZED_PRINCIPALS_ENV: "bad principal spaces"})
    )
    assert authority.availability == "INVALID"
    assert authority.decide("operator").allowed is False


def test_constant_operator_identity_alone_is_not_enough():
    authority = SupervisorAuthorizationAuthority.from_environ({AUTHORIZED_PRINCIPALS_ENV: "svc"})
    assert authority.decide("operator").allowed is False


def test_secret_like_principal_rejected():
    config = load_supervisor_authorization_config(
        {AUTHORIZED_PRINCIPALS_ENV: "API_KEY_123"}
    )
    assert config.valid is False


def test_valid_allowlist_grants_capability():
    authority = SupervisorAuthorizationAuthority.from_environ({AUTHORIZED_PRINCIPALS_ENV: "operator"})
    assert authority.availability == "AVAILABLE"
    decision = authority.decide("operator")
    assert decision.allowed is True
    assert decision.result == "ALLOW"


def test_duplicate_and_order_deterministic():
    config = load_supervisor_authorization_config(
        {AUTHORIZED_PRINCIPALS_ENV: "b, a ,b,  a"}
    )
    assert config.authorized_principals == ("a", "b")


# --- trigger service fixtures ----------------------------------------------

def _rate_limiter(limit=10):
    return AdvisorRateLimiter(limit=limit, window_seconds=60, clock=lambda: 0.0)


def make_trigger_service(tmp_path, *, enabled=True, rate_limit=10, runner=None):
    store = MonitoringTriggerIdempotencyStore(tmp_path / "idem.sqlite3")
    store.initialize()
    ownership = MonitoringTriggerOwnership(
        tmp_path / "trigger.lock", instance_id=INSTANCE, clock=lambda: NOW
    )
    coordinator = MonitoringTriggerCoordinator(
        ownership=ownership,
        store=store,
        runner=runner or (lambda request, context: {"status": "SUCCESS", "run_id": "R1"}),
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )
    audit = SupervisorTriggerAuditStore(tmp_path / "audit.sqlite3")
    audit.initialize()
    authority = SupervisorAuthorizationAuthority.from_environ(
        {AUTHORIZED_PRINCIPALS_ENV: "operator"}
    )
    service = SupervisorTriggerService(
        coordinator=coordinator,
        authorization=authority,
        audit_store=audit,
        rate_limiter=_rate_limiter(rate_limit),
        manual_trigger_enabled=enabled,
        feature_flags=READY_FLAGS,
        clock=lambda: NOW,
    )
    return service, audit, store, ownership


def test_valid_request_executes_once(tmp_path):
    calls = []
    service, audit, store, _ = make_trigger_service(
        tmp_path, runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"}
    )
    result = service.handle(principal_id="operator", body={"request_id": "req-1"})
    assert result.http_status == 200
    assert result.outcome == "RUNNER_SUCCEEDED"
    assert len(calls) == 1
    assert audit.count() >= 1


def test_replay_returns_stored_response_without_rerun(tmp_path):
    calls = []
    service, _audit, _store, _ = make_trigger_service(
        tmp_path, runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"}
    )
    service.handle(principal_id="operator", body={"request_id": "req-1"})
    second = service.handle(principal_id="operator", body={"request_id": "req-1"})
    assert second.http_status == 200
    assert second.outcome == "REPLAYED"
    assert second.replay is True
    assert len(calls) == 1


def test_unauthorized_rejected(tmp_path):
    service, audit, store, _ = make_trigger_service(tmp_path)
    result = service.handle(principal_id="nobody", body={"request_id": "req-1"})
    assert result.http_status == 403
    assert result.outcome == "UNAUTHORIZED"
    assert audit.count() >= 1


def test_constant_operator_without_mapping_rejected(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    service._authorization = SupervisorAuthorizationAuthority.from_environ({})
    result = service.handle(principal_id="operator", body={"request_id": "req-1"})
    assert result.http_status == 503
    assert result.outcome == "AUTHORIZATION_AUTHORITY_UNAVAILABLE"


def test_client_supplied_capability_ignored(tmp_path):
    # The request body DTO rejects unknown fields, including capability claims.
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    result = service.handle(
        principal_id="operator",
        body={"request_id": "req-1", "capabilities": ["SUPERVISOR_MONITORING_RUN_ONCE"]},
    )
    assert result.http_status == 400
    assert result.outcome == "INVALID_REQUEST"


def test_request_cannot_select_paths(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    result = service.handle(
        principal_id="operator", body={"request_id": "req-1", "db_path": "/tmp/evil.sqlite3"}
    )
    assert result.outcome == "INVALID_REQUEST"


def test_feature_flag_off_denies(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path, enabled=False)
    result = service.handle(principal_id="operator", body={"request_id": "req-1"})
    assert result.http_status == 503
    assert result.outcome == "DISABLED"


def test_rate_limit_required(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path, rate_limit=1)
    first = service.handle(principal_id="operator", body={"request_id": "req-1"})
    second = service.handle(principal_id="operator", body={"request_id": "req-2"})
    assert first.http_status == 200
    assert second.http_status == 429
    assert second.outcome == "RATE_LIMITED"


def test_conflict_and_ownership_busy_mapping(tmp_path):
    service, _audit, _store, ownership = make_trigger_service(tmp_path)
    service.handle(principal_id="operator", body={"request_id": "req-1"})
    conflict = service.handle(
        principal_id="operator", body={"request_id": "req-1", "scope": "HEALTH"}
    )
    assert conflict.http_status == 409
    assert conflict.outcome == "IDEMPOTENCY_CONFLICT"

    held = ownership.acquire("held", None, "SUPERVISOR_MONITORING_RUN_ONCE", 1)
    try:
        busy = service.handle(principal_id="operator", body={"request_id": "req-2"})
    finally:
        held.release()
    assert busy.http_status == 423
    assert busy.outcome == "OWNERSHIP_BUSY"


def test_audit_record_is_sanitized(tmp_path):
    service, audit, _store, _ = make_trigger_service(tmp_path)
    service.handle(principal_id="operator", body={"request_id": "req-1"})
    page = audit.list(limit=10)
    assert page.records
    dumped = page.records[0].stable_json()
    assert "req-1" not in dumped  # raw idempotency key is not stored
    assert "/tmp" not in dumped
    assert page.records[0].redacted is True


def test_runner_exception_not_exposed(tmp_path):
    def boom(request, context):
        raise RuntimeError("raw secret detail")

    service, _audit, _store, _ = make_trigger_service(tmp_path, runner=boom)
    result = service.handle(principal_id="operator", body={"request_id": "req-1"})
    assert result.outcome == "RUNNER_FAILED"
    dumped = result.model_dump_json()
    assert "raw secret detail" not in dumped


# --- HTTP route -------------------------------------------------------------

def make_control_client(*, trigger_service=None, alert_service=None, control_plane=None,
                        override_principal="operator", csrf_paths=None):
    app = FastAPI()
    if csrf_paths is not None:
        app.add_middleware(OperatorCsrfProtection, csrf_required_paths=frozenset(csrf_paths))
    app.include_router(
        create_supervisor_monitoring_control_router(
            control_plane=control_plane, trigger_service=trigger_service,
            alert_service=alert_service,
        )
    )
    if override_principal is not None:
        app.dependency_overrides[require_operator_session] = lambda: override_principal
    return TestClient(app)


def test_post_disabled_by_default():
    client = make_control_client()
    response = client.post("/monitoring/run-once", json={"request_id": "req-1"})
    assert response.status_code == 503
    assert response.json()["code"] == "SUPERVISOR_MONITORING_TRIGGER_DISABLED"


def test_post_requires_authentication(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    client = make_control_client(trigger_service=service, override_principal=None)
    response = client.post("/monitoring/run-once", json={"request_id": "req-1"})
    assert response.status_code == 401


def test_post_executes_with_auth(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    client = make_control_client(trigger_service=service)
    response = client.post("/monitoring/run-once", json={"request_id": "req-1"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "RUNNER_SUCCEEDED"


def test_post_csrf_required(tmp_path):
    service, _audit, _store, _ = make_trigger_service(tmp_path)
    client = make_control_client(
        trigger_service=service, csrf_paths=["/monitoring/run-once"]
    )
    assert client.post("/monitoring/run-once", json={"request_id": "r"}).status_code == 403
    headers = {CSRF_TOKEN_HEADER: "token-abc"}
    client.cookies.set(CSRF_TOKEN_COOKIE, "token-abc")
    allowed = client.post("/monitoring/run-once", json={"request_id": "r"}, headers=headers)
    assert allowed.status_code == 200


def test_alert_routes_unavailable_by_default():
    client = make_control_client()
    assert client.get("/monitoring/alerts").status_code == 503
    assert client.get("/monitoring/alerts/A123").status_code == 503


def test_control_route_unavailable_without_plane():
    client = make_control_client()
    assert client.get("/monitoring/control").status_code == 503


# --- control plane status ---------------------------------------------------

def test_control_plane_defaults_off(tmp_path):
    plane = SupervisorControlPlane.from_environ({})
    status = plane.status()
    assert status.manual_trigger_enabled is False
    assert status.scheduler_enabled is False
    assert status.alert_outbox_enabled is False
    assert status.advisor_alert_explanation_enabled is False
    assert status.authorization_availability == "NOT_CONFIGURED"
    assert status.production_activation_allowed is False
    assert status.production_activation_eligibility == "BLOCKED"
    assert plane.trigger_service is None
    assert plane.start() is False
    assert plane.stop() is True


def test_control_flags_default_off(tmp_path):
    flags = resolve_control_flags({})
    assert flags.all_off is True
    env = {
        MANUAL_TRIGGER_API_FLAG: "1",
        MONITORING_SCHEDULER_FLAG: "on",
        ALERT_OUTBOX_FLAG: "true",
        ADVISOR_ALERT_EXPLANATION_FLAG: "yes",
    }
    assert resolve_control_flags(env).all_off is False
    assert resolve_control_flags({MANUAL_TRIGGER_API_FLAG: "maybe"}).manual_trigger_enabled is False


def test_control_plane_status_reflects_configuration(tmp_path):
    config = ControlPlaneConfig(
        trigger_db_path=str(tmp_path / "idem.sqlite3"),
        trigger_lock_path=str(tmp_path / "t.lock"),
        trigger_audit_path=str(tmp_path / "audit.sqlite3"),
    )
    authority = SupervisorAuthorizationAuthority.from_environ({AUTHORIZED_PRINCIPALS_ENV: "operator"})
    plane = SupervisorControlPlane(
        flags=resolve_control_flags({MANUAL_TRIGGER_API_FLAG: "1"}),
        authorization=authority, config=config,
        alert_service=MonitoringAlertService(store=None, enabled=False),
    )
    status = plane.status()
    assert status.manual_trigger_enabled is True
    assert status.capability_mapping_configured is True
    assert status.idempotency_store_configured is True
    assert status.ownership_lock_configured is True
    assert status.audit_store_configured is True


def test_control_plane_alert_route_after_injection(tmp_path):
    from backend.supervisor.monitoring_alert_store import MonitoringAlertStore
    from backend.supervisor.monitoring_alert_models import AlertCandidate

    store = MonitoringAlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    service = MonitoringAlertService(store=store, enabled=True)
    service.ingest([AlertCandidate(
        anomaly_fingerprint="F" + "a" * 20, severity="WARNING",
        category="STATISTICAL_DRIFT", metric="entry_candidate_rate", occurred_at=NOW,
    )], now=NOW)
    client = make_control_client(alert_service=service)
    body = client.get("/monitoring/alerts").json()
    assert len(body["alerts"]) == 1
    alert_id = body["alerts"][0]["alert_id"]
    detail = client.get(f"/monitoring/alerts/{alert_id}")
    assert detail.status_code == 200
    assert detail.json()["alert_id"] == alert_id
    assert client.get("/monitoring/alerts/A" + "0" * 31).status_code == 404


def test_control_plane_health_read_model_integration(tmp_path):
    from backend.supervisor.monitoring_read_service import MonitoringReadService

    default_service = MonitoringReadService(clock=lambda: NOW)
    assert default_service.read().controlPlane is None

    authority = SupervisorAuthorizationAuthority.from_environ(
        {AUTHORIZED_PRINCIPALS_ENV: "operator"}
    )
    plane = SupervisorControlPlane(
        flags=resolve_control_flags({}), authorization=authority, clock=lambda: NOW
    )
    with_control = MonitoringReadService(control_plane=plane, clock=lambda: NOW)
    status = with_control.read().controlPlane
    assert status is not None
    assert status.manual_trigger_enabled is False
    assert status.production_activation_allowed is False


def test_control_route_returns_status(tmp_path):
    authority = SupervisorAuthorizationAuthority.from_environ(
        {AUTHORIZED_PRINCIPALS_ENV: "operator"}
    )
    plane = SupervisorControlPlane(
        flags=resolve_control_flags({}), authorization=authority, clock=lambda: NOW
    )
    client = make_control_client(control_plane=plane)
    body = client.get("/monitoring/control").json()
    assert body["authorization_availability"] == "AVAILABLE"
    assert body["manual_trigger_enabled"] is False
    assert body["production_activation_eligibility"] == "BLOCKED"


# --- static safety ----------------------------------------------------------

def test_control_api_has_no_production_defaults():
    source = inspect.getsource(control_api)
    assert "logs/runtime" not in source
    assert "supervisor_monitoring_trigger.lock" not in source


def test_no_unexpected_methods_on_control_router():
    router = create_supervisor_monitoring_control_router()
    methods = {}
    for route in router.routes:
        methods.setdefault(getattr(route, "path", ""), set()).update(route.methods)
    assert "/monitoring/run-once" in methods
    assert "POST" in methods["/monitoring/run-once"]
    for path, verbs in methods.items():
        if path.startswith("/monitoring/alerts") or path == "/monitoring/control":
            assert verbs <= {"GET", "HEAD"}
