"""Phase 3B explicit manual one-shot runner: synthetic, in-memory tests only.

No network, no Ollama, no Production paths.  Every dependency is injected and
all persistence uses temporary directories.
"""
from __future__ import annotations

import ast
import builtins
import inspect
import types
from datetime import timedelta
from pathlib import Path

import pytest

from backend.supervisor import manual_monitoring_runner as runner_module
from backend.supervisor.manual_monitoring_runner import (
    ManualMonitoringRunner,
    ManualRunResult,
    MonitoringQueryOutcome,
    MonitoringRunRequest,
)
from backend.supervisor.monitoring_scheduler_models import (
    FeatureFlagStatus,
    SchedulerConfig,
)
from backend.supervisor.monitoring_state_models import (
    Acknowledgement,
    MonitoringCycleResult,
)
from backend.supervisor.monitoring_state_service import MonitoringStateService
from backend.supervisor.monitoring_state_store import (
    AppendOutcome,
    AppendResult,
    MonitoringStateStore,
)
from backend.supervisor.monitoring_state_transitions import apply_acknowledgement
from backend.supervisor.one_shot_monitor import MonitorResult, one_shot_monitor
from test_supervisor_monitoring_models import NOW, raw
from test_supervisor_drift_evaluator import POLICY, comparison, persistent

CLOCK_AT = NOW + timedelta(minutes=3)
FLAG_ON = FeatureFlagStatus(
    enabled=True, source="ENV", raw_value_present=True, valid=True, reason_code=None,
)
FLAG_OFF = FeatureFlagStatus()
FLAG_INVALID = FeatureFlagStatus(
    enabled=True, source="INVALID", raw_value_present=True, valid=False,
    reason_code="FLAG_INVALID",
)


def clock():
    return CLOCK_AT


def query_warning(_request):
    return MonitoringQueryOutcome(
        observation_inputs={"warn": raw(persistent())},
        provenance=("CYCLE_EVIDENCE",),
    )


def query_normal(_request):
    return MonitoringQueryOutcome(observation_inputs={"norm": raw(comparison())})


def make_request(**changes):
    data = dict(
        request_id="req-1", requested_at=NOW, caller="TEST",
        max_observations=128, dry_run=True, persist=False,
    )
    data.update(changes)
    return MonitoringRunRequest(**data)


def make_runner(*, query=query_warning, flag=FLAG_ON, state_service=None, config=None,
                policy=POLICY, evaluator=one_shot_monitor, clock_fn=clock):
    return ManualMonitoringRunner(
        query=query, config=config, policy=policy, evaluator=evaluator,
        state_service=state_service, feature_flag=flag, clock=clock_fn,
    )


def make_service(tmp_path, name="state.jsonl"):
    store = MonitoringStateStore(tmp_path / name, fsync=False)
    return MonitoringStateService(store=store), store


def parse_source():
    return ast.parse(inspect.getsource(runner_module))


# --- 1-2 import / construction -------------------------------------------

def test_import_has_no_side_effects(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    source = inspect.getsource(runner_module)
    module = types.ModuleType("backend.supervisor._manual_runner_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        exec(compile(source, "manual_monitoring_runner.py", "exec"), module.__dict__)
    assert callable(module.ManualMonitoringRunner)
    assert callable(module.MonitoringRunRequest)


def test_construction_has_no_side_effects():
    calls = []
    runner = make_runner(query=lambda req: calls.append(req) or query_warning(req))
    assert calls == []
    assert runner.is_running is False
    assert runner.active_run_id is None


# --- 3-6 feature flag ----------------------------------------------------

def test_flag_off_returns_disabled():
    result = make_runner(flag=FLAG_OFF).run_once(make_request())
    assert result.status == "DISABLED"
    assert result.run_id is None
    assert result.evaluation is None


def test_flag_off_performs_no_query():
    calls = []
    runner = make_runner(flag=FLAG_OFF,
                         query=lambda req: calls.append(req) or query_warning(req))
    runner.run_once(make_request())
    assert calls == []


def test_flag_off_performs_no_persistence(tmp_path):
    service, store = make_service(tmp_path)
    runner = make_runner(flag=FLAG_OFF, state_service=service)
    result = runner.run_once(make_request(dry_run=False, persist=True))
    assert result.persistence_status == "NOT_ATTEMPTED"
    assert result.persisted_event_count == 0
    assert not store.path.exists()


def test_malformed_flag_fails_closed():
    calls = []
    runner = make_runner(flag=FLAG_INVALID,
                         query=lambda req: calls.append(req) or query_warning(req))
    result = runner.run_once(make_request())
    assert result.status == "DISABLED"
    assert "FLAG_INVALID" in result.errors
    assert calls == []


def test_flag_expectation_mismatch_fails_closed():
    calls = []
    runner = make_runner(query=lambda req: calls.append(req) or query_warning(req))
    result = runner.run_once(make_request(expected_flag_enabled=False))
    assert result.status == "INVALID"
    assert "FLAG_EXPECTATION_MISMATCH" in result.errors
    assert calls == []


# --- 7-8 request validation ----------------------------------------------

def test_invalid_request_fails_before_dependencies():
    calls = []
    runner = make_runner(query=lambda req: calls.append(req) or query_warning(req))
    result = runner.run_once({"request_id": "req-1"})
    assert result.status == "INVALID"
    assert "INVALID_REQUEST" in result.errors
    assert calls == []


def test_bounded_limit_validation():
    runner = make_runner()
    assert runner.run_once(
        {"request_id": "r", "requested_at": NOW, "max_observations": 10 ** 7}
    ).status == "INVALID"
    assert runner.run_once(
        {"request_id": "r", "requested_at": NOW, "max_observations": 0}
    ).status == "INVALID"
    constrained = make_runner(config=SchedulerConfig(max_observations=64))
    assert constrained.run_once(make_request(max_observations=128)).status == "INVALID"


# --- 9-11 invocation / determinism ---------------------------------------

def test_deterministic_result_with_fixed_inputs_and_clock():
    first = make_runner().run_once(make_request())
    second = make_runner().run_once(make_request())
    assert first.stable_json() == second.stable_json()
    assert first.run_id == second.run_id


def test_explicit_invocation_required():
    calls = []
    runner = make_runner(query=lambda req: calls.append(req) or query_warning(req))
    assert calls == []
    runner.run_once(make_request())
    assert len(calls) == 1


def test_successful_one_shot_composition(tmp_path):
    service, _store = make_service(tmp_path)
    result = make_runner(state_service=service).run_once(
        make_request(dry_run=False, persist=True)
    )
    assert result.status == "SUCCESS"
    assert isinstance(result.evaluation, MonitorResult)
    assert isinstance(result.cycle, MonitoringCycleResult)
    assert result.health is not None


# --- 12-15 authority reuse -----------------------------------------------

def test_phase1_evaluator_reused():
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        return one_shot_monitor(*args, **kwargs)

    result = make_runner(evaluator=spy).run_once(make_request())
    assert len(calls) == 1
    assert isinstance(result.evaluation, MonitorResult)


def test_phase2_transition_authority_reused(tmp_path):
    class Recording(MonitoringStateService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.reduce_calls = 0

        def reduce(self, *args, **kwargs):
            self.reduce_calls += 1
            return super().reduce(*args, **kwargs)

    service = Recording(store=MonitoringStateStore(tmp_path / "s.jsonl", fsync=False))
    result = make_runner(state_service=service).run_once(make_request())
    assert service.reduce_calls == 1
    assert isinstance(result.cycle, MonitoringCycleResult)


def test_phase2_store_reused(tmp_path):
    service, store = make_service(tmp_path)
    result = make_runner(state_service=service).run_once(
        make_request(dry_run=False, persist=True)
    )
    assert result.persistence_status == "PERSISTED"
    recovery = store.recover()
    assert recovery.records_read >= 1
    assert recovery.corruption_count == 0
    assert recovery.exists is True


def test_no_new_persistence_authority():
    source = inspect.getsource(runner_module)
    assert "MonitoringStateStore" not in source
    assert "os.open" not in source
    assert "fcntl" not in source


# --- 16-20 overlap / lock ------------------------------------------------

def test_overlap_returns_busy_or_skipped(tmp_path):
    holder = {}
    results = {}

    def query(req):
        if "inner" not in results:
            results["inner"] = holder["runner"].run_once(
                make_request(request_id="req-inner")
            )
        return query_warning(req)

    class Recording(MonitoringStateService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.reduce_calls = 0

        def reduce(self, *args, **kwargs):
            self.reduce_calls += 1
            return super().reduce(*args, **kwargs)

    service = Recording(store=MonitoringStateStore(tmp_path / "s.jsonl", fsync=False))
    runner = make_runner(query=query, state_service=service)
    holder["runner"] = runner
    outer = runner.run_once(make_request(request_id="req-outer"))
    assert outer.status == "SUCCESS"
    inner = results["inner"]
    assert inner.status == "SKIPPED_OVERLAP"
    assert inner.overlap.decision == "REJECT_OVERLAP"
    assert inner.cycle is None and inner.persisted_event_count == 0
    assert service.reduce_calls == 1


def test_overlap_performs_no_duplicate_append(tmp_path):
    results = {}
    holder = {}

    def query(req):
        if "inner" not in results:
            results["inner"] = holder["runner"].run_once(
                make_request(request_id="req-inner")
            )
        return query_warning(req)

    service, store = make_service(tmp_path)
    holder["runner"] = make_runner(query=query, state_service=service)
    holder["runner"].run_once(make_request(request_id="req-outer", dry_run=False, persist=True))
    assert results["inner"].status == "SKIPPED_OVERLAP"
    assert store.recover().records_read == 1


def test_lock_released_after_success():
    runner = make_runner()
    assert runner.run_once(make_request(request_id="a")).status == "SUCCESS"
    assert runner.is_running is False
    assert runner.run_once(make_request(request_id="b")).status == "SUCCESS"


def test_lock_released_after_exception():
    calls = {"n": 0}

    def query(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return query_warning(req)

    runner = make_runner(query=query)
    first = runner.run_once(make_request(request_id="a"))
    assert first.status == "UNAVAILABLE"
    assert runner.is_running is False
    assert runner.run_once(make_request(request_id="b")).status == "SUCCESS"


# --- 21-30 failure isolation and propagation -----------------------------

def test_observation_unavailable_remains_unavailable(tmp_path):
    service, store = make_service(tmp_path)
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            available=False, source_freshness="UNKNOWN",
            source_availability="UNAVAILABLE", error_code="SOURCE_DOWN",
        ),
        state_service=service,
    )
    result = runner.run_once(make_request(dry_run=False, persist=True))
    assert result.status == "UNAVAILABLE"
    assert result.evaluation is None and result.cycle is None
    assert result.source_availability == "UNAVAILABLE"
    assert not store.path.exists()


def test_partial_result_propagated():
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            observation_inputs={"n": raw(comparison())}, partial_result=True,
            warnings=("SOURCE_PARTIAL",),
        )
    )
    result = runner.run_once(make_request())
    assert result.status == "PARTIAL"
    assert result.partial_result is True
    assert "SOURCE_PARTIAL" in result.warnings


def test_corruption_metadata_propagated():
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            observation_inputs={"n": raw(comparison())}, corruption_count=2,
        )
    )
    result = runner.run_once(make_request())
    assert result.corruption_count == 2


def test_provenance_propagated():
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            observation_inputs={"n": raw(comparison())},
            provenance=("CYCLE_EVIDENCE", "TRADING_TRACE"),
        )
    )
    result = runner.run_once(make_request())
    assert result.provenance == ("CYCLE_EVIDENCE", "TRADING_TRACE")


def test_freshness_propagated():
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            observation_inputs={"n": raw(comparison())}, source_freshness="STALE",
        )
    )
    result = runner.run_once(make_request())
    assert result.source_freshness == "STALE"


def test_warnings_propagated():
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(
            observation_inputs={"n": raw(comparison())}, warnings=("SOURCE_STALE",),
        )
    )
    result = runner.run_once(make_request())
    assert "SOURCE_STALE" in result.warnings


def test_query_failure_isolated(tmp_path):
    service, store = make_service(tmp_path)

    def query(_req):
        raise ConnectionError("source down")

    runner = make_runner(query=query, state_service=service)
    result = runner.run_once(make_request(dry_run=False, persist=True))
    assert result.status == "UNAVAILABLE"
    assert "QUERY_UNAVAILABLE" in result.errors
    assert result.persisted_event_count == 0
    assert not store.path.exists()


def test_evaluator_failure_isolated(tmp_path):
    service, store = make_service(tmp_path)

    def bad(*_args, **_kwargs):
        raise RuntimeError("evaluator")

    runner = make_runner(evaluator=bad, state_service=service)
    result = runner.run_once(make_request(dry_run=False, persist=True))
    assert result.status == "FAILED"
    assert "EVALUATION_FAILED" in result.errors
    assert not store.path.exists()


def test_transition_failure_isolated(tmp_path):
    class Failing(MonitoringStateService):
        def reduce(self, *args, **kwargs):
            raise RuntimeError("transition")

    service = Failing(store=MonitoringStateStore(tmp_path / "s.jsonl", fsync=False))
    result = make_runner(state_service=service).run_once(
        make_request(dry_run=False, persist=True)
    )
    assert result.status == "FAILED"
    assert "TRANSITION_FAILED" in result.errors


def test_persistence_failure_exposed(tmp_path, monkeypatch):
    service, _store = make_service(tmp_path)
    monkeypatch.setattr(
        service, "persist",
        lambda cycle: [AppendResult(AppendOutcome.REJECTED, error="disk full")],
    )
    result = make_runner(state_service=service).run_once(
        make_request(dry_run=False, persist=True)
    )
    assert result.status == "DEGRADED"
    assert result.persistence_status == "REJECTED"
    assert "PERSISTENCE_REJECTED" in result.warnings
    assert result.persisted_event_count == 0


# --- 31-35 persistence boundary ------------------------------------------

def test_persistence_requires_explicit_permission(tmp_path):
    service, store = make_service(tmp_path)
    result = make_runner(state_service=service).run_once(make_request())
    assert result.persistence_status == "NOT_ATTEMPTED"
    assert not store.path.exists()

    unauthorized = make_runner().run_once(make_request(dry_run=False, persist=True))
    assert unauthorized.status == "INVALID"
    assert "PERSISTENCE_UNAUTHORIZED" in unauthorized.errors


def test_temp_path_persistence_only():
    source = inspect.getsource(runner_module)
    for marker in ("logs/runtime", "supervisor_monitoring_state.jsonl", "/home/"):
        assert marker not in source


def test_idempotent_retry(tmp_path):
    service, store = make_service(tmp_path)
    runner = make_runner(state_service=service)
    request = make_request(dry_run=False, persist=True)
    first = runner.run_once(request)
    second = runner.run_once(request)
    assert first.persistence_status == "PERSISTED"
    assert second.persisted_event_count == 0
    assert any(t.duplicate for t in second.cycle.transitions)
    assert store.recover().records_read == 1


def test_duplicate_event_handling(tmp_path):
    service, store = make_service(tmp_path)
    runner = make_runner(state_service=service)
    request = make_request(dry_run=False, persist=True)
    first = runner.run_once(request)
    assert first.persistence_status == "PERSISTED"
    outcomes = store.append_many(first.cycle.events)
    assert all(o.outcome is AppendOutcome.DUPLICATE for o in outcomes)
    assert all(o.idempotent for o in outcomes)


def test_conflict_handling(tmp_path, monkeypatch):
    service, _store = make_service(tmp_path)
    monkeypatch.setattr(
        service, "persist",
        lambda cycle: [AppendResult(AppendOutcome.CONFLICT, event_id="x", error="conflict")],
    )
    result = make_runner(state_service=service).run_once(
        make_request(dry_run=False, persist=True)
    )
    assert result.persistence_status == "PARTIAL"
    assert "PERSISTENCE_CONFLICT" in result.warnings


# --- 36-39 state outcomes / health ---------------------------------------

def test_cooldown_result_propagated(tmp_path):
    service, _store = make_service(tmp_path)
    counter = {"n": 0}

    def query(_req):
        counter["n"] += 1
        value = 0.5 if counter["n"] == 1 else 0.55
        return MonitoringQueryOutcome(observation_inputs={"warn": raw(persistent(value=value))})

    runner = make_runner(query=query, state_service=service)
    first = runner.run_once(make_request(request_id="a", dry_run=False, persist=True))
    second = runner.run_once(make_request(request_id="b", dry_run=False, persist=True))
    assert first.status == "SUCCESS" and second.status == "SUCCESS"
    assert any(s.reason for s in second.cycle.suppressed)


def test_dedup_result_propagated(tmp_path):
    service, _store = make_service(tmp_path)
    runner = make_runner(state_service=service)
    request = make_request(dry_run=False, persist=True)
    runner.run_once(request)
    second = runner.run_once(request)
    assert any(t.duplicate for t in second.cycle.transitions)


def test_acknowledgement_resolution_compatibility(tmp_path):
    service, _store = make_service(tmp_path)
    result = make_runner(state_service=service).run_once(make_request())
    state = result.cycle.states[0]
    acknowledgement = Acknowledgement(
        fingerprint=state.fingerprint, acknowledged_at=CLOCK_AT, actor="operator",
        expected_revision=state.state_revision,
    )
    outcome = apply_acknowledgement(
        state, acknowledgement, evaluated_at=CLOCK_AT, cooldown=service.cooldown
    )
    assert outcome.transition == "ACKNOWLEDGED"
    assert outcome.state.lifecycle_state == "ACKNOWLEDGED"


def test_health_reducer_result_included():
    result = make_runner().run_once(make_request())
    assert result.health is not None
    assert result.health.scheduler_state in ("IDLE", "DEGRADED", "RUNNING", "FAILED")
    assert result.health.enabled is True


# --- 40-41 bounded / secret free -----------------------------------------

def test_bounded_output():
    result = make_runner().run_once(make_request())
    assert len(result.stable_json()) < 100000
    for field in ("warnings", "errors", "provenance"):
        values = getattr(result, field)
        assert list(values) == sorted(set(values))


def test_no_secret_leakage():
    data = raw(comparison())
    data["current"]["api_key"] = "sk-supersecret-material"
    runner = make_runner(
        query=lambda req: MonitoringQueryOutcome(observation_inputs={"bad": data})
    )
    result = runner.run_once(make_request())
    text = result.stable_json()
    assert "sk-supersecret-material" not in text
    assert "api_key" not in text


# --- 42-47 static safety -------------------------------------------------

def test_no_production_trace_access():
    source = inspect.getsource(runner_module)
    for marker in ("trading_trace", "cycle_evidence", "knowledge_history_query",
                   "logs/runtime", "sqlite3", "socket"):
        assert marker not in source


def test_no_api_route():
    source = inspect.getsource(runner_module)
    assert "fastapi" not in source.lower()
    assert "APIRouter" not in source and "@app" not in source


def test_no_scheduler():
    tree = parse_source()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({a.name for a in node.names} & {"asyncio", "threading", "sched"})
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {"asyncio", "threading", "sched"}
    source = inspect.getsource(runner_module)
    for marker in ("create_task", "APScheduler", "Thread(", "Timer(", "while True"):
        assert marker not in source


def test_no_timer_thread_background_task():
    tree = parse_source()
    assert not any(
        isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"start", "run_forever", "call_later"}
        for node in ast.walk(tree)
    )


def test_no_production_composition_change():
    root = Path(__file__).resolve().parents[1]
    for relative in ("backend/main.py", "backend/api/supervisor.py"):
        text = (root / relative).read_text()
        assert "manual_monitoring_runner" not in text


def test_cross_process_guarantee_not_claimed():
    source = inspect.getsource(runner_module)
    assert "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED" in source
    for marker in ("fcntl", "flock", "advisory lock", "fencing generation"):
        assert marker not in source


# --- 48 existing behavior preserved --------------------------------------

def test_existing_phase_behavior_preserved():
    from backend.supervisor.monitoring_scheduler_models import resolve_feature_flag_status

    assert resolve_feature_flag_status(None).enabled is False
    baseline = one_shot_monitor({"n": raw(comparison())}, policy=POLICY, evaluated_at=CLOCK_AT)
    assert baseline.aggregate_status == "NORMAL"
    assert isinstance(make_runner().run_once(make_request()), ManualRunResult)
