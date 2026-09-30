"""Phase 3C read-only monitoring read-service tests (synthetic, no Production)."""
from __future__ import annotations

import ast
import builtins
import inspect
import types
from datetime import timedelta

import pytest

from backend.supervisor import monitoring_read_service as read_module
from backend.supervisor.monitoring_read_service import (
    CROSS_PROCESS_SAFETY,
    FEATURE_FLAG_NAME,
    AnomalyCounts,
    ManualRunSummary,
    MonitoringReadResponse,
    MonitoringReadService,
)
from backend.supervisor.monitoring_scheduler_models import FeatureFlagStatus
from backend.supervisor.monitoring_state_models import (
    AnomalyState,
    RecoveryResult,
    StateEvent,
)
from backend.supervisor.monitoring_state_store import MonitoringStateStore
from test_supervisor_monitoring_models import NOW

CLOCK_AT = NOW + timedelta(minutes=1)


def fixed_clock():
    return CLOCK_AT


FLAG_ON = FeatureFlagStatus(
    enabled=True, source="ENV", raw_value_present=True, valid=True, reason_code=None,
)


def anomaly_state(fingerprint, lifecycle="ACTIVE", **changes):
    data = dict(
        fingerprint=fingerprint, episode_key="b" * 64, family="c" * 64,
        metric="entry_candidate_rate", policy_version="monitoring-v1",
        category="STATISTICAL_DRIFT", lifecycle_state=lifecycle,
        current_severity="WARNING", highest_severity="WARNING",
        first_seen_at=NOW, last_seen_at=NOW, occurrence_count=1, consecutive_count=1,
        last_evaluation_id="eval-1", last_observation_id="obs-1",
        last_content_digest="d" * 64, active=True,
    )
    if lifecycle == "ACKNOWLEDGED":
        data.update(acknowledged_at=NOW, acknowledged_by="operator")
    elif lifecycle == "RESOLVED":
        data.update(active=False, current_severity="NONE", resolved_at=NOW,
                    resolution_reason="CONSECUTIVE_NORMAL_VALID")
    elif lifecycle == "UNKNOWN":
        data.update(current_severity="NONE", reason_codes=("DEGRADED_INPUT",))
    data.update(changes)
    return AnomalyState.model_validate(data)


def make_event(state, suffix):
    return StateEvent(
        occurred_at=NOW, fingerprint=state.fingerprint, episode_number=1,
        evaluation_id=f"eval-{suffix}", observation_id=f"obs-{suffix}",
        transition="CREATED", notification_eligible=False, state=state,
    )


def recovery_result(states=(), **changes):
    data = dict(
        states=tuple(states),
        event_ids=tuple(s.fingerprint for s in states),
        records_read=len(states), bytes_read=100, corruption_count=0,
        duplicate_events=0, partial=False, exists=True, warnings=(), corrupted=(),
    )
    data.update(changes)
    return RecoveryResult(**data)


def service(**kwargs):
    kwargs.setdefault("clock", fixed_clock)
    return MonitoringReadService(**kwargs)


# --- 1-2 import / construction -------------------------------------------

def test_import_has_no_side_effects(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    source = inspect.getsource(read_module)
    module = types.ModuleType("backend.supervisor._read_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        exec(compile(source, "monitoring_read_service.py", "exec"), module.__dict__)
    assert callable(module.MonitoringReadService)


def test_constructor_has_no_io(tmp_path, monkeypatch):
    path = tmp_path / "absent.jsonl"

    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during construction")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        instance = MonitoringReadService(store=MonitoringStateStore(path), clock=fixed_clock)
    assert instance is not None
    assert not path.exists()


# --- 8-14 flag / fixed facts ---------------------------------------------

def test_feature_flag_default_off():
    result = service().read()
    assert result.featureFlagName == FEATURE_FLAG_NAME
    assert result.featureEnabled is False
    assert result.defaultEnabled is False
    assert result.activationStatus == "DISABLED"


def test_invalid_flag_fails_closed():
    flag = FeatureFlagStatus(
        enabled=True, source="INVALID", raw_value_present=True, valid=False,
        reason_code="FLAG_INVALID",
    )
    result = service(feature_flag=flag).read()
    assert result.featureEnabled is False
    assert result.activationStatus == "INVALID"


def test_enabled_flag_is_inactive_not_running():
    result = service(feature_flag=FLAG_ON).read()
    assert result.featureEnabled is True
    assert result.activationStatus == "CONFIGURED_ENABLED_INACTIVE"
    assert result.schedulerConnected is False
    assert result.backgroundTaskActive is False
    assert result.productionActivationAllowed is False


def test_cross_process_limitation_explicit():
    result = service().read()
    assert result.crossProcessSafety == CROSS_PROCESS_SAFETY
    assert result.productionActivationAllowed is False


# --- 15-18 journal states ------------------------------------------------

def test_journal_missing_not_created(tmp_path):
    path = tmp_path / "missing.jsonl"
    result = service(store=MonitoringStateStore(path)).read()
    assert result.journalAvailability == "UNAVAILABLE"
    assert result.recoveryStatus == "UNAVAILABLE"
    assert "JOURNAL_MISSING" in result.warnings
    assert not path.exists()


def test_journal_partial(tmp_path):
    path = tmp_path / "partial.jsonl"
    store = MonitoringStateStore(path, max_recovery_records=1)
    store.append(make_event(anomaly_state("a" * 64), "1"))
    store.append(make_event(anomaly_state("b" * 64), "2"))
    result = service(store=store).read()
    assert result.journalAvailability == "PARTIAL"
    assert result.partialResult is True
    assert result.recordsRead == 1
    assert "JOURNAL_PARTIAL" in result.warnings


def test_corrupt_record_isolated(tmp_path):
    path = tmp_path / "corrupt.jsonl"
    store = MonitoringStateStore(path)
    store.append(make_event(anomaly_state("a" * 64), "1"))
    with path.open("ab") as handle:
        handle.write(b"{not valid json\n")
    result = service(store=store).read()
    assert result.corruptionCount >= 1
    assert result.journalAvailability == "CORRUPT"
    assert result.totalCount == 1
    assert "JOURNAL_CORRUPT" in result.warnings


def test_bounded_recovery(tmp_path):
    path = tmp_path / "bounded.jsonl"
    store = MonitoringStateStore(path, max_recovery_records=2)
    for index in range(5):
        store.append(make_event(anomaly_state(f"{index:064d}"), str(index)))
    result = service(store=store).read()
    assert result.recordsRead <= 2
    assert result.partialResult is True


def test_injected_recovery_preferred_over_store(tmp_path):
    path = tmp_path / "never.jsonl"
    store = MonitoringStateStore(path)
    result = service(store=store, recovery=recovery_result([anomaly_state("a" * 64)])).read()
    assert result.journalAvailability == "AVAILABLE"
    assert result.recordsRead == 1
    assert not path.exists()


# --- 19-30 projection fields ---------------------------------------------

def test_freshness_available_and_stale():
    fresh = service(recovery=recovery_result([anomaly_state("a" * 64)]), freshness="FRESH").read()
    assert fresh.freshness == "FRESH"
    stale = service(freshness="STALE").read()
    assert stale.freshness == "STALE"


def test_provenance_exposed():
    derived = service(recovery=recovery_result([anomaly_state("a" * 64)])).read()
    assert "SUPERVISOR_MONITORING_JOURNAL" in derived.provenance
    injected = service(provenance=("CUSTOM_SOURCE",)).read()
    assert injected.provenance == ("CUSTOM_SOURCE",)


def test_availability_exposed():
    available = service(recovery=recovery_result([anomaly_state("a" * 64)])).read()
    assert available.availability == "AVAILABLE"
    missing = service().read()
    assert missing.availability == "NOT_CONFIGURED"


def test_partial_result_exposed():
    result = service(recovery=recovery_result([anomaly_state("a" * 64)], partial=True)).read()
    assert result.partialResult is True
    assert result.journalAvailability == "PARTIAL"


def test_corruption_count_exposed():
    result = service(
        recovery=recovery_result([anomaly_state("a" * 64)], corruption_count=3)
    ).read()
    assert result.corruptionCount == 3


def test_warnings_bounded_and_sorted():
    result = service(
        recovery=recovery_result([anomaly_state("a" * 64)], corruption_count=1)
    ).read()
    assert list(result.warnings) == sorted(set(result.warnings))
    assert len(result.warnings) <= 64


def test_anomaly_counts():
    states = (
        anomaly_state("a" * 64, "ACTIVE"),
        anomaly_state("b" * 64, "ACKNOWLEDGED", cooldown_until=NOW + timedelta(hours=1)),
        anomaly_state("c" * 64, "RESOLVED"),
        anomaly_state("d" * 64, "SUPPRESSED"),
        anomaly_state("e" * 64, "UNKNOWN"),
    )
    result = service(recovery=recovery_result(states)).read()
    assert result.totalCount == 5
    assert result.activeCount == 4
    assert result.acknowledgedCount == 1
    assert result.resolvedCount == 1
    assert result.suppressedCount == 1
    assert result.cooldownCount == 1
    assert isinstance(result.anomalyCounts, AnomalyCounts)
    assert result.anomalyCounts.unknownCount == 1


def test_last_run_summary_propagated():
    class Run:
        run_id = "run-1"
        mode = "MANUAL"
        status = "SUCCESS"
        started_at = NOW
        finished_at = NOW + timedelta(seconds=1)
        persistence_status = "PERSISTED"
        persisted_event_count = 2
        partial_result = False
        anomaly_count = 1
        observation_count = 3
        warnings = ("W",)
        errors = ()
        provenance = ("P",)
        source_freshness = "FRESH"
        source_availability = "AVAILABLE"

    result = service(last_run=Run()).read()
    assert result.lastRunId == "run-1"
    assert result.lastRunMode == "MANUAL"
    assert result.lastRunStatus == "SUCCESS"
    assert isinstance(result.lastRun, ManualRunSummary)
    assert result.lastRun.persistedEventCount == 2


def test_health_reduction_from_scheduler_state():
    from backend.supervisor.monitoring_scheduler_state import initial_scheduler_state

    result = service(scheduler_state=initial_scheduler_state()).read()
    assert result.schedulerState == "DISABLED"
    assert result.health is not None
    assert result.health.scheduler_state == "DISABLED"


# --- 31-32 determinism ----------------------------------------------------

def test_injected_clock_determinism():
    instance = service()
    assert instance.read().stable_json() == instance.read().stable_json()
    assert instance.read().generatedAt == CLOCK_AT


# --- 33-35 no writes ------------------------------------------------------

def test_read_does_not_create_or_modify_journal(tmp_path):
    path = tmp_path / "stable.jsonl"
    store = MonitoringStateStore(path)
    store.append(make_event(anomaly_state("a" * 64), "1"))
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    service(store=store).read()
    service(store=store).read()
    after = (path.stat().st_size, path.stat().st_mtime_ns)
    assert before == after


# --- 36-47 static safety / bounded / secrets ------------------------------

def test_no_runner_or_scheduler_activation():
    tree = ast.parse(inspect.getsource(read_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("manual_monitoring_runner" in name for name in imported)
    assert not imported & {"asyncio", "threading", "sched"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "ManualMonitoringRunner" not in names
    assert "run_once" not in names and "run_once" not in attrs
    assert "create_task" not in attrs


def test_no_production_trace_access():
    source = inspect.getsource(read_module)
    for marker in (
        "trading_trace", "cycle_evidence", "logs/runtime", "sqlite3", "socket",
        "os.environ", "getenv",
    ):
        assert marker not in source


def test_no_notification():
    source = inspect.getsource(read_module)
    for marker in ("notify", "webhook", "smtp", "send("):
        assert marker not in source


def test_no_trading_authority_fields():
    forbidden = {
        "allow", "block", "order", "execute", "arm", "disarm", "runtime",
        "tradingRecommendation", "governance", "remediate",
    }
    assert not set(MonitoringReadResponse.model_fields) & forbidden


def test_bounded_response():
    result = service(recovery=recovery_result([anomaly_state("a" * 64)])).read()
    assert len(result.stable_json()) < 50000


def test_no_secret_leakage():
    text = service().read().stable_json()
    assert "sk-" not in text
    assert "API_KEY" not in text.upper()


def test_dependency_exception_isolated(tmp_path, monkeypatch):
    store = MonitoringStateStore(tmp_path / "raises.jsonl")

    def boom():
        raise RuntimeError("disk failure")

    monkeypatch.setattr(store, "recover", boom)
    result = service(store=store).read()
    assert result.journalAvailability == "UNAVAILABLE"
    assert result.recoveryStatus == "UNAVAILABLE"
    assert "JOURNAL_READ_FAILED" in result.warnings
