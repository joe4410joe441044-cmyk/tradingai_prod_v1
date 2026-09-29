"""Phase 3D-1 bounded trigger request/response/idempotency/gate/budget tests.

Pure inputs, injected clocks and temporary data only.  No route, no runner, no
persistence, no scheduler.
"""
from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.supervisor import monitoring_trigger_models as models
from backend.supervisor.monitoring_trigger_models import (
    MAX_AUDIT_WARNINGS,
    RESTART_SAFE_API_IDEMPOTENCY,
    VALIDATION_GATE_ORDER,
    ExecutionBudgetResult,
    GateDecision,
    IdempotencyRecord,
    OwnershipResult,
    TriggerAuditRecord,
    TriggerRequest,
    TriggerResponse,
    build_response,
    canonical_fingerprint_payload,
    evaluate_execution_budget,
    evaluate_gate_order,
    evaluate_idempotency,
    proposed_http_status,
    request_fingerprint,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def base_request(**changes) -> TriggerRequest:
    data = dict(request_id="req-1", scope="ALL", max_observations=10, reason="manual check")
    data.update(changes)
    return TriggerRequest(**data)


# --- request bounds: 16-24 --------------------------------------------------

def test_valid_bounded_request():
    request = base_request(symbols=("BTC-USDT",), modes=("PAPER",), correlation_id="corr-1")
    assert request.request_id == "req-1"
    assert request.symbols == ("BTC-USDT",)
    assert request.persistence_requested is False


def test_request_id_length_boundary():
    assert TriggerRequest(request_id="a" * 128).request_id == "a" * 128
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="a" * 129)
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="")


def test_symbol_count_boundary():
    ok = tuple(f"S{i:02d}" for i in range(8))
    assert TriggerRequest(request_id="r", symbols=ok).symbols == tuple(sorted(set(ok)))
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", symbols=tuple(f"S{i:02d}" for i in range(9)))


def test_symbol_length_boundary():
    assert TriggerRequest(request_id="r", symbols=("A" * 32,)).symbols == ("A" * 32,)
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", symbols=("A" * 33,))


def test_observation_limit_boundary():
    assert TriggerRequest(request_id="r", max_observations=1).max_observations == 1
    assert TriggerRequest(request_id="r", max_observations=128).max_observations == 128
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", max_observations=0)
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", max_observations=129)


def test_reason_length_boundary():
    assert TriggerRequest(request_id="r", reason="a" * 256).reason == "a" * 256
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", reason="a" * 257)


def test_arbitrary_path_rejected():
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", symbols=("../../etc/passwd",))
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", reason="/etc/passwd")


def test_url_or_raw_payload_rejected():
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", symbols=("http://example.test",))
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", reason="see http://example.test")
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", reason="sk-1234567890")


@pytest.mark.parametrize(
    "forbidden",
    ["actor", "authorization", "authorization_result", "received_at", "run_id",
     "csrf_result", "feature_flag_result", "audit_result", "trading_command"],
)
def test_server_authoritative_fields_not_trusted(forbidden):
    with pytest.raises(ValidationError):
        TriggerRequest.model_validate({"request_id": "r", forbidden: "value"})


def test_unsupported_mode_rejected():
    with pytest.raises(ValidationError):
        TriggerRequest(request_id="r", modes=("SANDBOX",))


# --- fingerprint: 25-29 -----------------------------------------------------

def test_deterministic_fingerprint():
    request = base_request()
    assert request_fingerprint(request) == request_fingerprint(request)
    assert len(request_fingerprint(request)) == 64


def test_field_order_independence():
    first = TriggerRequest.model_validate(
        {"request_id": "r", "scope": "ALL", "max_observations": 5, "reason": "x"}
    )
    second = TriggerRequest.model_validate(
        {"reason": "x", "max_observations": 5, "scope": "ALL", "request_id": "r"}
    )
    assert request_fingerprint(first) == request_fingerprint(second)


def test_canonical_filter_order():
    a = TriggerRequest(request_id="r", symbols=("B", "A"))
    b = TriggerRequest(request_id="r", symbols=("A", "B"))
    assert a.symbols == b.symbols == ("A", "B")
    assert request_fingerprint(a) == request_fingerprint(b)


def test_meaningful_change_changes_fingerprint():
    a = base_request(scope="ALL")
    b = base_request(scope="HEALTH")
    assert request_fingerprint(a) != request_fingerprint(b)


def test_secret_excluded_from_fingerprint_input():
    request = base_request(correlation_id="client-correlation")
    payload = canonical_fingerprint_payload(request)
    assert "correlation_id" not in payload
    assert "client-correlation" not in payload
    # Correlation identifier is not execution-relevant, so it does not change it.
    assert request_fingerprint(request) == request_fingerprint(base_request(correlation_id="other"))


# --- idempotency: 30-37 -----------------------------------------------------

def stored_record(status, fingerprint=None, *, expires_in=3600):
    return IdempotencyRecord(
        key="req-1",
        fingerprint=fingerprint or request_fingerprint(base_request()),
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=expires_in),
    )


def test_idempotency_new():
    assert evaluate_idempotency(
        key="req-1", request_fingerprint="f", stored=None, now=NOW
    ).decision == "NEW"


def test_idempotency_replay_same_request():
    fingerprint = request_fingerprint(base_request())
    result = evaluate_idempotency(
        key="req-1", request_fingerprint=fingerprint,
        stored=stored_record("COMPLETED", fingerprint), now=NOW,
    )
    assert result.decision == "REPLAY_SAME_REQUEST"
    assert result.replay is True


def test_idempotency_conflicting_request():
    result = evaluate_idempotency(
        key="req-1", request_fingerprint="different",
        stored=stored_record("COMPLETED"), now=NOW,
    )
    assert result.decision == "CONFLICT_DIFFERENT_REQUEST"


def test_idempotency_in_progress():
    assert evaluate_idempotency(
        key="req-1", request_fingerprint=request_fingerprint(base_request()),
        stored=stored_record("IN_PROGRESS"), now=NOW,
    ).decision == "IN_PROGRESS"


def test_idempotency_expired():
    assert evaluate_idempotency(
        key="req-1", request_fingerprint=request_fingerprint(base_request()),
        stored=stored_record("COMPLETED"), now=NOW + timedelta(hours=2),
    ).decision == "EXPIRED"


def test_idempotency_unavailable_authority():
    assert evaluate_idempotency(
        key="req-1", request_fingerprint="f", stored=None, now=NOW, authority_available=False
    ).decision == "AUTHORITY_UNAVAILABLE"


def test_idempotency_exact_timestamp_boundary():
    record = stored_record("COMPLETED")
    # Inclusive expiry: at exactly expires_at the record is EXPIRED (fail closed).
    assert evaluate_idempotency(
        key="req-1", request_fingerprint=record.fingerprint, stored=record,
        now=record.expires_at,
    ).decision == "EXPIRED"
    assert evaluate_idempotency(
        key="req-1", request_fingerprint=record.fingerprint, stored=record,
        now=record.expires_at - timedelta(microseconds=1),
    ).decision == "REPLAY_SAME_REQUEST"


def test_idempotency_no_persistence_or_write():
    assert RESTART_SAFE_API_IDEMPOTENCY == "NOT_IMPLEMENTED"
    record = stored_record("FAILED_RETRYABLE")
    before = record.stable_json()
    evaluate_idempotency(
        key="req-1", request_fingerprint=record.fingerprint, stored=record, now=NOW
    )
    assert record.stable_json() == before
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert "MonitoringStateStore" not in names
    assert "open" not in calls
    assert "write" not in calls
    assert "sqlite3" not in imports


# --- gate ordering: 38-47 ---------------------------------------------------

def gate_index(name: str) -> int:
    return VALIDATION_GATE_ORDER.index(name)


@pytest.mark.parametrize(
    "blocking,blocked_next",
    [
        ("ROUTE_ENABLED", "AUTHENTICATION"),
        ("AUTHENTICATION", "AUTHORIZATION"),
        ("AUTHORIZATION", "CSRF"),
        ("CSRF", "REQUEST_VALIDATION"),
        ("REQUEST_VALIDATION", "IDEMPOTENCY"),
        ("IDEMPOTENCY", "CROSS_PROCESS_OWNERSHIP"),
        ("CROSS_PROCESS_OWNERSHIP", "IN_PROCESS_OVERLAP"),
        ("IN_PROCESS_OVERLAP", "EXECUTION_BUDGET"),
    ],
)
def test_gate_blocking_stops_before_downstream(blocking, blocked_next):
    result = evaluate_gate_order({blocking: "BLOCK"})
    assert result.first_blocking_gate == blocking
    assert result.ready_for_runner is False
    assert result.gates[gate_index(blocked_next)].status == "NOT_EVALUATED"


def test_route_disabled_stops_first():
    result = evaluate_gate_order({"ROUTE_ENABLED": "BLOCK"})
    assert result.first_blocking_gate == "ROUTE_ENABLED"
    assert result.classification == "DISABLED"
    assert all(g.status == "NOT_EVALUATED" for g in result.gates[1:])


def test_all_gates_allow_ready_for_runner():
    result = evaluate_gate_order({name: "ALLOW" for name in VALIDATION_GATE_ORDER})
    assert result.first_blocking_gate is None
    assert result.ready_for_runner is True
    assert result.classification == "READY_FOR_RUNNER"


def test_gate_decision_override_reason():
    result = evaluate_gate_order({
        "CSRF": GateDecision(gate="CSRF", status="BLOCK", reason_code="CSRF_TOKEN_MISSING")
    })
    assert result.first_blocking_gate == "CSRF"
    assert result.gates[gate_index("CSRF")].reason_code == "CSRF_TOKEN_MISSING"


def test_runner_is_never_called():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not any("manual_monitoring_runner" in name for name in imports)
    assert "ManualMonitoringRunner" not in names
    assert "run_once" not in calls
    assert evaluate_gate_order({}).ready_for_runner is True


def test_gate_order_is_exact():
    assert VALIDATION_GATE_ORDER == (
        "ROUTE_ENABLED", "AUTHENTICATION", "AUTHORIZATION", "CSRF",
        "REQUEST_VALIDATION", "IDEMPOTENCY", "CROSS_PROCESS_OWNERSHIP",
        "IN_PROCESS_OVERLAP", "EXECUTION_BUDGET", "RUNNER_ELIGIBILITY",
    )


# --- execution budget: 48-52 ------------------------------------------------

def test_valid_deadline_available():
    result = evaluate_execution_budget(
        max_duration_seconds=10, started_at=NOW, now=NOW + timedelta(seconds=3)
    )
    assert result.state == "AVAILABLE"
    assert result.remaining_seconds == pytest.approx(7.0)
    assert result.deadline_at == NOW + timedelta(seconds=10)


def test_exact_deadline_boundary_expired():
    result = evaluate_execution_budget(
        max_duration_seconds=10, started_at=NOW, now=NOW + timedelta(seconds=10)
    )
    assert result.state == "EXPIRED"
    assert result.remaining_seconds == 0.0


def test_expired_deadline():
    result = evaluate_execution_budget(
        max_duration_seconds=10, started_at=NOW, now=NOW + timedelta(seconds=11)
    )
    assert result.state == "EXPIRED"


def test_invalid_duration():
    for bad in (0, -1, 10**9, float("inf"), float("nan"), "nope"):
        assert evaluate_execution_budget(
            max_duration_seconds=bad, started_at=NOW, now=NOW
        ).state == "INVALID"
    assert evaluate_execution_budget(
        max_duration_seconds=10, started_at="not-a-time", now=NOW
    ).state == "INVALID"


def test_no_timer_thread_or_task():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not imports & {"asyncio", "threading", "signal", "sched"}
    assert "Timer" not in names
    assert "Thread" not in names
    assert "create_task" not in calls


# --- ownership: 53-55 -------------------------------------------------------

def test_all_ownership_states_represented():
    for state in (
        "NOT_CONFIGURED", "AVAILABLE", "ACQUIRED", "BUSY",
        "STALE_METADATA", "ERROR", "UNSUPPORTED",
    ):
        result = OwnershipResult(state=state, reason_code="X")
        assert result.state == state
        assert result.acquired is False


def test_ownership_does_not_open_lock_files_or_flock():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert "flock" not in names
    assert "lockf" not in names
    assert not imports & {"fcntl", "os"}
    assert "open" not in calls


# --- audit / security: 56-60 ------------------------------------------------

def audit_kwargs(**changes):
    data = dict(
        audit_event_id="evt-1", request_id="req-1", principal_ref="Pabc",
        result_classification="READY_FOR_RUNNER", received_at=NOW,
    )
    data.update(changes)
    return data


def test_sanitized_audit_model():
    record = TriggerAuditRecord(**audit_kwargs())
    data = json.loads(record.stable_json())
    forbidden_keys = {
        "password", "cookie", "cookies", "api_key", "apikey", "csrf_token",
        "session", "session_token", "session_id", "token", "secret",
        "traceback", "stack_trace", "raw_body", "evidence", "trace",
    }
    assert not set(data) & forbidden_keys


def test_secret_key_rejected_or_redacted():
    record = TriggerAuditRecord.from_mapping(
        audit_kwargs(password="hunter2", cookie="session=abc", api_key="sk-1")
    )
    assert record.redacted is True
    assert "FORBIDDEN_KEY_REDACTED" in record.warnings
    assert "hunter2" not in record.stable_json()
    assert "sk-1" not in record.stable_json()
    with pytest.raises(ValidationError):
        TriggerAuditRecord(**audit_kwargs(password="hunter2"))


def test_audit_warnings_bounded():
    with pytest.raises(ValidationError):
        TriggerAuditRecord(
            **audit_kwargs(warnings=tuple(f"W{i}" for i in range(MAX_AUDIT_WARNINGS + 1)))
        )


def test_no_stack_trace_exposed():
    response = build_response("INTERNAL_DEPENDENCY_ERROR")
    assert "Traceback" not in response.stable_json()
    assert "Error" not in response.message
    record = TriggerAuditRecord.from_mapping(audit_kwargs(stack_trace="boom"))
    assert record.redacted is True


def test_privacy_safe_principal_reference():
    from backend.supervisor.monitoring_trigger_security import principal_reference

    ref = principal_reference("operator-secret-identity")
    assert ref.startswith("P")
    assert "operator-secret-identity" not in ref
    assert len(ref) == 33


# --- response: 61-63 --------------------------------------------------------

def test_bounded_response():
    response = build_response("READY_FOR_RUNNER", request_id="req-1")
    assert len(response.stable_json()) < 2000
    assert response.production_activation_allowed is False
    assert response.cross_process_safety.startswith("NOT_GUARANTEED")


def test_stable_http_classification_proposal():
    assert proposed_http_status("UNAUTHENTICATED") == 401
    assert proposed_http_status("UNAUTHORIZED") == 403
    assert proposed_http_status("CSRF_REJECTED") == 403
    assert proposed_http_status("INVALID_REQUEST") == 400
    assert proposed_http_status("IDEMPOTENCY_CONFLICT") == 409
    assert proposed_http_status("OWNERSHIP_UNAVAILABLE") == 503
    assert proposed_http_status("BUSY") == 409
    assert proposed_http_status("DEADLINE_INVALID") == 504
    assert proposed_http_status("READY_FOR_RUNNER") == 200


def test_internal_exception_sanitized():
    response = build_response("INTERNAL_DEPENDENCY_ERROR")
    assert isinstance(response, TriggerResponse)
    assert response.message == "Request could not be completed."
    assert response.retryable is True


def test_idempotent_replay_flag_only_for_replay():
    replayed = build_response("IDEMPOTENCY_REPLAY", idempotent_replay=True)
    assert replayed.idempotent_replay is True
    assert build_response("READY_FOR_RUNNER", idempotent_replay=True).idempotent_replay is False


# --- static boundaries: 64-70 -----------------------------------------------

def _ast_index(source: str) -> tuple[set, set, set]:
    tree = ast.parse(source)
    imports: set[str] = set()
    names: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return imports, names, calls


def test_no_fastapi_route():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not any("fastapi" in name.lower() for name in imports)
    assert "include_router" not in calls
    assert "APIRouter" not in names


def test_no_manual_runner_invocation():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not any("manual_monitoring_runner" in name for name in imports)
    assert "ManualMonitoringRunner" not in names
    assert "run_once" not in calls


def test_no_production_composition_change():
    imports, _, _ = _ast_index(inspect.getsource(models))
    assert not any(name.startswith("backend.api") for name in imports)
    assert not any(name.startswith("backend.main") for name in imports)


def test_no_state_persistence():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert "MonitoringStateStore" not in names
    assert "MonitoringStateService" not in names
    assert "sqlite3" not in imports
    assert "open" not in calls
    assert "write" not in calls


def test_no_scheduler_background_task():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not imports & {"asyncio", "threading", "sched", "signal"}
    assert "Timer" not in names
    assert "create_task" not in calls


def test_no_notification():
    imports, names, calls = _ast_index(inspect.getsource(models))
    assert not imports & {"smtplib", "requests", "httpx"}
    for name in names | calls:
        assert "notify" not in name.lower()
        assert "webhook" not in name.lower()
        assert "smtp" not in name.lower()


def test_no_trading_authority():
    forbidden = {
        "allow", "block", "order", "execute", "arm", "disarm", "runtime",
        "tradingRecommendation", "governance", "remediate",
    }
    assert not set(TriggerResponse.model_fields) & forbidden
    _, names, calls = _ast_index(inspect.getsource(models))
    for marker in ("place_order", "submit_order", "cancel_order", "live_arm", "arm_live"):
        assert marker not in names
        assert marker not in calls

