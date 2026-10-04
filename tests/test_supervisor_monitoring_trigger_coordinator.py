"""Phase 3D-2C fenced trigger coordinator tests.

Temporary paths only.  Injected fake runners, temporary SQLite databases and
temporary lock files.  No API route, no Production database/lock, no monitoring
execution, no notification, no scheduler and no background task.
"""
from __future__ import annotations

import builtins
import inspect
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.supervisor import monitoring_trigger_coordinator as coordinator_module
from backend.supervisor.monitoring_trigger_coordinator import (
    DEFAULT_MAX_DURATION_SECONDS,
    RunnerInvocationContext,
    MonitoringTriggerCoordinator,
)
from backend.supervisor.monitoring_trigger_idempotency_store import (
    MonitoringTriggerIdempotencyStore,
    TransitionResult,
)
from backend.supervisor.monitoring_trigger_models import TriggerRequest
from backend.supervisor.monitoring_trigger_ownership import MonitoringTriggerOwnership
from backend.supervisor.monitoring_trigger_security import (
    TRIGGER_CAPABILITY,
    TRIGGER_PERSIST_CAPABILITY,
    AuthorizationInput,
    evaluate_trigger_flags,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INSTANCE = "I" + "a" * 16
OP = "SUPERVISOR_MONITORING_RUN_ONCE"
FP = "a" * 64
SOURCE = inspect.getsource(coordinator_module)
REPO_ROOT = Path(__file__).resolve().parents[1]

READY_FLAGS = evaluate_trigger_flags(api_raw="1", monitoring_raw="1")


class FakeMonotonic:
    def __init__(self, values):
        self._values = list(values)
        self._last = self._values[0] if self._values else 0.0

    def __call__(self):
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def make_store(tmp_path, name="idem.sqlite3"):
    store = MonitoringTriggerIdempotencyStore(tmp_path / name)
    store.initialize()
    return store


def make_ownership(tmp_path, name="trigger.lock"):
    return MonitoringTriggerOwnership(
        tmp_path / name,
        instance_id=INSTANCE,
        clock=lambda: NOW,
        process_start_provider=lambda pid: "fixed-start",
    )


def make_coordinator(tmp_path, *, store=None, runner=None, monotonic=None, name="trigger.lock"):
    store = store if store is not None else make_store(tmp_path)
    ownership = make_ownership(tmp_path, name=name)
    return MonitoringTriggerCoordinator(
        ownership=ownership,
        store=store,
        runner=runner if runner is not None else (lambda request, context: {"status": "SUCCESS"}),
        clock=lambda: NOW,
        monotonic=monotonic if monotonic is not None else (lambda: 0.0),
    )


def authorization(*capabilities):
    return AuthorizationInput(
        authenticated=True,
        principal_id="operator",
        capabilities=tuple(capabilities) or (TRIGGER_CAPABILITY,),
        capability_source="VERIFIED_ADAPTER",
        source_available=True,
        source_freshness="FRESH",
    )


def request(request_id="req-1", **overrides):
    payload = {"request_id": request_id}
    payload.update(overrides)
    return TriggerRequest(**payload)


def record_for(store, request_id="req-1", scope=None):
    # The coordinator derives the privacy-safe scope from the authorization
    # evidence, so look the record up through the store's recent list.
    for view in store.recent_records():
        if view.key == request_id:
            return view
    return None


# --- import / construction --------------------------------------------------

def test_import_has_no_io(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    module = types.ModuleType("backend.supervisor._coordinator_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        patch.setattr(os, "open", boom)
        patch.setitem(sys.modules, module.__name__, module)
        exec(compile(SOURCE, "monitoring_trigger_coordinator.py", "exec"), module.__dict__)
    assert callable(module.MonitoringTriggerCoordinator)


def test_constructor_has_no_io_and_requires_explicit_deps(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    ownership = make_ownership(tmp_path)

    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during construction")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", boom)
        patch.setattr(builtins, "open", boom)
        coordinator = MonitoringTriggerCoordinator(
            ownership=ownership, store=store, runner=lambda request: {"status": "SUCCESS"}
        )
    assert coordinator.ownership is ownership
    with pytest.raises(TypeError):
        MonitoringTriggerCoordinator(ownership=ownership, store=object(), runner=lambda r: None)
    with pytest.raises(TypeError):
        MonitoringTriggerCoordinator(ownership=ownership, store=store, runner=None)


# --- 1: first request claims and runs once ----------------------------------

def test_first_request_claims_and_runs_once(tmp_path):
    calls = []
    coordinator = make_coordinator(
        tmp_path, runner=lambda request, context: calls.append(context) or {"status": "SUCCESS"}
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_SUCCEEDED"
    assert result.executed is True
    assert result.runner_invoked is True
    assert result.persisted is True
    assert len(calls) == 1
    record = record_for(coordinator.store)
    assert record.status == "COMPLETED"
    assert record.generation == 1


# --- 2, 17: replay does not run and does not acquire the lock ---------------

def test_identical_completed_request_replays(tmp_path):
    calls = []
    coordinator = make_coordinator(
        tmp_path, runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"}
    )
    first = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    second = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert first.outcome == "RUNNER_SUCCEEDED"
    assert second.outcome == "REPLAYED"
    assert second.replay is True
    assert second.executed is False
    assert len(calls) == 1


def test_replay_does_not_acquire_execution_lock(tmp_path):
    class NoAcquireOwnership(MonitoringTriggerOwnership):
        def acquire(self, *_args, **_kwargs):
            raise AssertionError("lock acquired unnecessarily on replay")

    store = make_store(tmp_path)
    priming = MonitoringTriggerCoordinator(
        ownership=make_ownership(tmp_path),
        store=store,
        runner=lambda request, context: {"status": "SUCCESS"},
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )
    priming.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    replay = MonitoringTriggerCoordinator(
        ownership=NoAcquireOwnership(
            tmp_path / "trigger.lock", instance_id=INSTANCE, clock=lambda: NOW
        ),
        store=store,
        runner=lambda request, context: {"status": "SUCCESS"},
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )
    result = replay.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "REPLAYED"


# --- claim-only / CLAIMED outcome -------------------------------------------

def test_claim_only_returns_claimed_without_execution(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    result = coordinator.coordinate(
        request=request(),
        authorization=authorization(),
        feature_flags=READY_FLAGS,
        claim_only=True,
        now=NOW,
    )
    assert result.outcome == "CLAIMED"
    assert result.executed is False
    assert calls == []
    assert coordinator.ownership.current_status().active is False


# --- 3: same key different fingerprint conflicts ----------------------------

def test_same_key_different_fingerprint_conflicts(tmp_path):
    calls = []
    coordinator = make_coordinator(
        tmp_path, runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"}
    )
    coordinator.coordinate(
        request=request(scope="ALL"), authorization=authorization(),
        feature_flags=READY_FLAGS, now=NOW,
    )
    conflict = coordinator.coordinate(
        request=request(scope="HEALTH"), authorization=authorization(),
        feature_flags=READY_FLAGS, now=NOW,
    )
    assert conflict.outcome == "IDEMPOTENCY_CONFLICT"
    assert conflict.reason_code == "FINGERPRINT_MISMATCH"
    assert len(calls) == 1


# --- 5: different keys cannot run simultaneously under one lock -------------

def test_lock_contention_does_not_invoke_runner(tmp_path):
    calls = []
    coordinator = make_coordinator(
        tmp_path, runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"}
    )
    held = coordinator.ownership.acquire("held", None, OP, 1)
    assert held.acquired is True
    try:
        result = coordinator.coordinate(
            request=request("req-2"), authorization=authorization(),
            feature_flags=READY_FLAGS, now=NOW,
        )
    finally:
        held.release()
    assert result.outcome == "OWNERSHIP_BUSY"
    assert result.executed is False
    assert calls == []
    record = record_for(coordinator.store, request_id="req-2")
    assert record.status == "FAILED_RETRYABLE"


# --- 6: stale generation cannot write terminal state ------------------------

def test_stale_terminal_write_is_rejected(tmp_path):
    class StaleTerminalStore:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def complete_success(self, **_kwargs):
            return TransitionResult(
                decision="STALE_GENERATION", applied=False, reason_code="STALE_GENERATION"
            )

    calls = []
    inner = make_store(tmp_path)
    coordinator = make_coordinator(
        tmp_path, store=StaleTerminalStore(inner),
        runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"},
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "STALE_GENERATION_REJECTED"
    assert result.persisted is False
    assert len(calls) == 1
    assert record_for(inner).status != "COMPLETED"


def test_stale_generation_cannot_start_run(tmp_path):
    class StaleRunningStore:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def mark_running(self, **_kwargs):
            return TransitionResult(
                decision="STALE_GENERATION", applied=False, reason_code="STALE_GENERATION"
            )

    calls = []
    coordinator = make_coordinator(
        tmp_path, store=StaleRunningStore(make_store(tmp_path)),
        runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"},
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "STALE_GENERATION_REJECTED"
    assert calls == []


# --- 8, 9, 10: restart / recovery / old-result rejection --------------------

def test_recovered_claim_gets_new_generation_and_old_result_rejected(tmp_path):
    store = make_store(tmp_path)
    first = store.claim(
        key="req-1", request_fingerprint=FP, principal_scope="Pscope",
        operation=OP, now=NOW,
    )
    recovered = store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope="Pscope", request_fingerprint=FP,
        expected_generation=first.generation, lock_acquirable=True, lease_expired=True, now=NOW,
    )
    assert recovered.decision == "RECLAIMED"
    assert recovered.generation == first.generation + 1

    stale = store.complete_success(
        key="req-1", operation=OP, principal_scope="Pscope", request_fingerprint=FP,
        expected_generation=first.generation, owner_id=first.owner_id,
        response={"code": "OK"}, now=NOW,
    )
    assert stale.decision == "STALE_GENERATION"
    current = store.get_record(key="req-1", operation=OP, principal_scope="Pscope")
    assert current.generation == recovered.generation
    assert current.status == "CLAIMED"


# --- 11: runner exception records a bounded failed result -------------------

def test_runner_exception_records_bounded_failure(tmp_path):
    def exploding_runner(_request, _context):
        raise RuntimeError("raw secret detail that must never leak")

    coordinator = make_coordinator(tmp_path, runner=exploding_runner)
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_FAILED"
    assert result.runner_invoked is True
    assert result.persisted is False
    record = record_for(coordinator.store)
    assert record.status == "FAILED_RETRYABLE"
    assert record.error_class == "RUNNER_EXCEPTION"
    dumped = result.model_dump_json()
    assert "raw secret detail" not in dumped
    assert str(tmp_path) not in dumped
    assert "RuntimeError" not in dumped


# --- 12: late runner result becomes DEADLINE_EXCEEDED -----------------------

def test_late_runner_result_is_deadline_exceeded(tmp_path):
    calls = []
    monotonic = FakeMonotonic([0.0, 0.0, 10_000.0])
    coordinator = make_coordinator(
        tmp_path,
        runner=lambda request, context: calls.append(1) or {"status": "SUCCESS", "run_id": "R1"},
        monotonic=monotonic,
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "DEADLINE_EXCEEDED"
    assert result.deadline_exceeded is True
    assert result.runner_invoked is True
    assert result.response is None
    assert len(calls) == 1
    record = record_for(coordinator.store)
    assert record.status == "FAILED_FINAL"
    assert record.error_class == "DEADLINE_EXCEEDED"
    assert coordinator.ownership.current_status().active is False


def test_deadline_checked_before_runner(tmp_path):
    calls = []
    monotonic = FakeMonotonic([0.0, 10_000.0])
    coordinator = make_coordinator(
        tmp_path,
        runner=lambda request, context: calls.append(1) or {"status": "SUCCESS"},
        monotonic=monotonic,
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "DEADLINE_EXCEEDED"
    assert result.reason_code == "DEADLINE_EXCEEDED_PRE_RUNNER"
    assert result.runner_invoked is False
    assert calls == []


# --- 13, 14: authority failure does not run or falsely complete -------------

def test_persistence_failure_does_not_invoke_runner(tmp_path):
    class DownStore:
        def claim(self, **_kwargs):
            raise RuntimeError("authority down")

        def get_record(self, **_kwargs):
            raise RuntimeError("authority down")

        def mark_running(self, **_kwargs):
            raise RuntimeError("authority down")

        def complete_success(self, **_kwargs):
            raise RuntimeError("authority down")

        def complete_failure_retryable(self, **_kwargs):
            raise RuntimeError("authority down")

        def complete_failure_final(self, **_kwargs):
            raise RuntimeError("authority down")

    calls = []
    coordinator = MonitoringTriggerCoordinator(
        ownership=make_ownership(tmp_path),
        store=DownStore(),
        runner=lambda request, context: calls.append(1),
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "PERSISTENCE_FAILURE"
    assert calls == []
    assert result.executed is False


def test_authority_unavailable_claim_fails_closed(tmp_path):
    class UnavailableStore:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def claim(self, **kwargs):
            from backend.supervisor.monitoring_trigger_idempotency_store import ClaimResult

            return ClaimResult(decision="AUTHORITY_UNAVAILABLE", reason_code="DATABASE_BUSY")

    calls = []
    coordinator = make_coordinator(
        tmp_path, store=UnavailableStore(make_store(tmp_path)),
        runner=lambda request, context: calls.append(1),
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "PERSISTENCE_FAILURE"
    assert calls == []


# --- 15, 16: ownership released on every path -------------------------------

def test_release_after_success(tmp_path):
    coordinator = make_coordinator(tmp_path)
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_SUCCEEDED"
    assert coordinator.ownership.current_status().active is False
    assert coordinator.ownership.current_status().descriptor_open is False


def test_release_after_runner_failure(tmp_path):
    def exploding_runner(_request, _context):
        raise RuntimeError("boom")

    coordinator = make_coordinator(tmp_path, runner=exploding_runner)
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_FAILED"
    assert coordinator.ownership.current_status().active is False


# --- 18, 19, 20: config / authorization / flag gates ------------------------

def test_feature_flag_off_creates_no_execution(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    flags = evaluate_trigger_flags(api_raw="0", monitoring_raw="1")
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=flags, now=NOW
    )
    assert result.outcome == "DISABLED"
    assert result.executed is False
    assert calls == []
    assert record_for(coordinator.store) is None


def test_malformed_configuration_fails_before_runner(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    flags = evaluate_trigger_flags(api_raw="definitely-not-a-flag", monitoring_raw="1")
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=flags, now=NOW
    )
    assert result.outcome == "DISABLED"
    assert result.reason_code == "FLAG_INVALID"
    assert calls == []
    assert record_for(coordinator.store) is None


def test_unauthorized_request_creates_no_execution(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    result = coordinator.coordinate(
        request=request(),
        authorization=AuthorizationInput(authenticated=False),
        feature_flags=READY_FLAGS,
        now=NOW,
    )
    assert result.outcome == "UNAUTHORIZED"
    assert calls == []
    assert record_for(coordinator.store) is None
    assert coordinator.ownership.current_status().active is False


def test_persist_request_requires_stronger_capability(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    result = coordinator.coordinate(
        request=request(persistence_requested=True),
        authorization=authorization(TRIGGER_CAPABILITY),
        feature_flags=READY_FLAGS,
        now=NOW,
    )
    assert result.outcome == "UNAUTHORIZED"
    assert result.reason_code == "CAPABILITY_MISSING"
    assert calls == []


def test_invalid_request_is_rejected(tmp_path):
    calls = []
    coordinator = make_coordinator(tmp_path, runner=lambda request, context: calls.append(1))
    result = coordinator.coordinate(
        request={"request_id": "has spaces"},  # invalid token
        authorization=authorization(),
        feature_flags=READY_FLAGS,
        now=NOW,
    )
    assert result.outcome == "INVALID_REQUEST"
    assert calls == []


# --- runner interface detection ---------------------------------------------

def test_runner_without_context_is_supported(tmp_path):
    calls = []

    def single_argument_runner(_request):
        calls.append(1)
        return {"status": "SUCCESS"}

    coordinator = make_coordinator(tmp_path, runner=single_argument_runner)
    assert coordinator.runner_accepts_context is False
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_SUCCEEDED"
    assert len(calls) == 1


def test_runner_context_is_cooperative_and_bounded(tmp_path):
    captured = {}

    def context_runner(_request, context: RunnerInvocationContext):
        captured["context"] = context
        return {"status": "SUCCESS"}

    coordinator = make_coordinator(tmp_path, runner=context_runner)
    assert coordinator.runner_accepts_context is True
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_SUCCEEDED"
    context = captured["context"]
    assert context.cooperative_deadline is True
    assert context.hard_cancellation_supported is False
    assert context.generation == 1
    assert context.max_duration_seconds == DEFAULT_MAX_DURATION_SECONDS


def test_runner_failed_status_is_not_success(tmp_path):
    coordinator = make_coordinator(
        tmp_path, runner=lambda request, context: {"status": "FAILED"}
    )
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    assert result.outcome == "RUNNER_FAILED"
    assert result.persisted is False
    record = record_for(coordinator.store)
    assert record.status == "FAILED_RETRYABLE"
    assert record.error_class == "RUNNER_STATUS_FAILED"


# --- bounded output / audit -------------------------------------------------

def test_result_is_bounded_and_path_free(tmp_path):
    coordinator = make_coordinator(tmp_path)
    result = coordinator.coordinate(
        request=request(), authorization=authorization(), feature_flags=READY_FLAGS, now=NOW
    )
    dumped = result.model_dump_json()
    assert str(tmp_path) not in dumped
    assert "trigger.lock" not in dumped
    assert result.production_activation_allowed is False
    assert result.api_route_connected is False
    audit = result.to_audit(moment=NOW)
    assert audit.outcome == result.outcome
    assert str(tmp_path) not in audit.model_dump_json()


# --- static safety ----------------------------------------------------------

def test_no_api_route():
    for token in ("FastAPI", "APIRouter", "add_api_route", "@router", "include_router"):
        assert token not in SOURCE


def test_no_runner_import_or_run_once_token():
    for token in ("manual_monitoring_runner", "ManualMonitoringRunner", "run_once",
                  "ManualRunResult", "one_shot_monitor"):
        assert token not in SOURCE


def test_no_scheduler_or_background_task():
    for token in ("asyncio", "threading", "concurrent.futures", "Timer", "Scheduler", "scheduler"):
        assert token not in SOURCE


def test_no_notification():
    for token in ("notify", "notification", "alert_emit", "webhook"):
        assert token not in SOURCE


def test_no_trading_authority():
    for token in ("bot_manager", "place_order", "governance", "LIVE_ARM", "order_dispatch"):
        assert token not in SOURCE


def test_no_production_trace_or_database():
    for token in ("TRADING_E2E_TRACE", "trading_e2e_trace", "cycle_evidence_store",
                  "sqlite3", ".sqlite3", ".db", "logs/runtime",
                  "supervisor_monitoring_trigger.lock"):
        assert token not in SOURCE


def test_no_repo_artifacts(tmp_path):
    assert not list(REPO_ROOT.glob("*.lock"))
    assert not list(REPO_ROOT.glob("*.sqlite3"))
