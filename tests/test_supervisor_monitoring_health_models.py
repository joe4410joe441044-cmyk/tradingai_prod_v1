"""Phase 3A scheduler health model, reducer and safety-boundary tests."""
from datetime import datetime, timedelta, timezone
import inspect
import pytest
from pydantic import ValidationError

from backend.supervisor import monitoring_health_models as health_module
from backend.supervisor import monitoring_scheduler_models as models_module
from backend.supervisor import monitoring_scheduler_state as state_module
from backend.supervisor.monitoring_health_models import (
    MonitoringHealth, disabled_health, reduce_health,
)
from backend.supervisor.monitoring_scheduler_models import MonitoringRun
from backend.supervisor.monitoring_scheduler_state import (
    SchedulerTransition, initial_scheduler_state, transition_state,
)
from backend.supervisor.monitoring_state_models import CorruptRecord, RecoveryResult

NOW = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
FORBIDDEN_FIELDS = {
    "allow", "block", "order", "execute", "arm", "disarm", "runtime",
    "tradingRecommendation", "governance", "remediate",
}


def ts(minutes=0):
    return NOW + timedelta(minutes=minutes)


def cmd(event, **over):
    data = dict(event=event, requested_at=NOW)
    data.update(over)
    return SchedulerTransition(**data)


def idle_state():
    s = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED")).state
    return transition_state(s, cmd("STARTUP_COMPLETE")).state


def running_state(run_id="run-1"):
    return transition_state(idle_state(), cmd("RUN_START", run_id=run_id)).state


def run(**over):
    data = dict(
        run_id="run-1", trigger_type="SCHEDULED", requested_at=NOW, started_at=NOW,
        completed_at=ts(1), status="SUCCESS", timeout_seconds=10.0, duration_ms=60000,
        observation_count=3, evaluation_count=2, anomaly_count=1, active_anomaly_count=1,
        eligible_notification_count=0, state_event_count=1,
    )
    data.update(over)
    return MonitoringRun(**data)


# --- Health (48-61) --------------------------------------------------------

def test_health_disabled():
    health = disabled_health(updated_at=NOW)
    assert health.scheduler_state == "DISABLED" and health.enabled is False
    assert health.feature_flag_source == "DEFAULT_OFF"
    assert health.run_count == 0 and health.state_recovery_status == "NOT_ATTEMPTED"
    assert health.schema_version == "scheduler-health-v1"


def test_health_idle():
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW)
    assert health.scheduler_state == "IDLE" and health.enabled is True
    assert health.current_run_id is None


def test_health_running():
    health = reduce_health(scheduler_state=running_state(), updated_at=NOW)
    assert health.scheduler_state == "RUNNING" and health.current_run_id == "run-1"


def test_health_success_counter():
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=run())
    assert health.run_count == 1 and health.success_count == 1
    assert health.last_success_at == ts(1) and health.last_result_status == "SUCCESS"


def test_health_failure_counter():
    failed = run(status="FAILED", error_code="RUN_FAILED")
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=failed)
    assert health.failure_count == 1 and health.timeout_count == 0
    assert health.last_error_code == "RUN_FAILED"


def test_health_timeout_counter():
    timed = run(status="TIMED_OUT", error_code="RUN_TIMEOUT")
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=timed)
    assert health.timeout_count == 1 and health.failure_count == 0


def test_health_skipped_overlap_counter():
    skipped = run(status="SKIPPED_OVERLAP", started_at=None, completed_at=NOW,
                  duration_ms=None, observation_count=0, evaluation_count=0,
                  anomaly_count=0, active_anomaly_count=0, state_event_count=0)
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=skipped)
    assert health.skipped_overlap_count == 1 and health.run_count == 0


def test_health_duplicate_completion_no_double_count():
    first = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=run())
    second = reduce_health(
        scheduler_state=idle_state(), updated_at=ts(2), previous=first, completed_run=run()
    )
    assert second.run_count == 1 and second.success_count == 1


def test_health_partial_recovery():
    health = reduce_health(
        scheduler_state=idle_state(), updated_at=NOW,
        recovery=RecoveryResult(partial=True, records_read=10),
    )
    assert health.state_recovery_status == "PARTIAL"
    assert health.state_partial_recovery is True
    assert "RECOVERY_PARTIAL" in health.degraded_reasons


def test_health_corruption():
    health = reduce_health(
        scheduler_state=idle_state(), updated_at=NOW,
        recovery=RecoveryResult(corruption_count=1, corrupted=(CorruptRecord(position=0, reason="INVALID_JSON"),)),
    )
    assert health.state_recovery_status == "CORRUPT" and health.state_corruption_count == 1


def test_health_stale_source():
    stale = run(source_freshness="STALE")
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=stale)
    assert health.source_freshness == "STALE" and "SOURCE_STALE" in health.degraded_reasons


def test_health_unavailable_source():
    unavailable = run(source_availability="UNAVAILABLE")
    health = reduce_health(scheduler_state=idle_state(), updated_at=NOW, completed_run=unavailable)
    assert "SOURCE_UNAVAILABLE" in health.degraded_reasons


def test_health_degraded_run_visible():
    partial = run(status="PARTIAL", partial_result=True)
    health = reduce_health(scheduler_state=running_state(), updated_at=NOW, completed_run=partial)
    assert health.last_result_status == "PARTIAL" and "RUN_DEGRADED" in health.degraded_reasons


def test_health_deterministic_output():
    a = reduce_health(scheduler_state=running_state(), updated_at=NOW, completed_run=run())
    b = reduce_health(scheduler_state=running_state(), updated_at=NOW, completed_run=run())
    assert a.stable_json() == b.stable_json()


def test_health_next_run_deterministic():
    from backend.supervisor.monitoring_scheduler_models import SchedulerConfig
    health = reduce_health(
        scheduler_state=idle_state(), updated_at=NOW, config=SchedulerConfig(interval_seconds=30.0),
    )
    assert health.next_run_at == NOW + timedelta(seconds=30)


def test_health_no_update_on_disabled_config():
    health = reduce_health(
        scheduler_state=initial_scheduler_state(), updated_at=NOW,
    )
    assert health.next_run_at is None


def test_health_no_trading_authority_fields():
    for model in (MonitoringHealth, MonitoringRun):
        assert not FORBIDDEN_FIELDS & set(model.model_fields)


def test_health_updated_at_requires_timezone():
    with pytest.raises(ValidationError):
        MonitoringHealth(updated_at=datetime(2026, 9, 28))


# --- Safety boundaries (70-77) --------------------------------------------

MODULES = (models_module, state_module, health_module)
FORBIDDEN_IMPORTS = {
    "os", "socket", "requests", "httpx", "urllib", "aiohttp", "threading", "asyncio",
    "sqlite3", "pathlib", "shutil", "subprocess", "fcntl",
}


def _imports(module):
    from ast import Import, ImportFrom, parse, walk
    names = set()
    for node in walk(parse(inspect.getsource(module))):
        if isinstance(node, Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_filesystem_io():
    for module in MODULES:
        source = inspect.getsource(module)
        assert ".write(" not in source and "open(" not in source
        assert "pathlib" not in source and "shutil" not in source


def test_no_network():
    for module in MODULES:
        assert not _imports(module) & {"socket", "requests", "httpx", "urllib", "aiohttp"}


def test_no_environment_read():
    for module in MODULES:
        source = inspect.getsource(module)
        assert "os.environ" not in source and "getenv" not in source


def test_no_scheduler_task_thread_timer():
    for module in MODULES:
        source = inspect.getsource(module)
        assert "create_task" not in source and "Thread(" not in source
        assert "APScheduler" not in source and "Timer" not in source
        assert "asyncio" not in source and "threading" not in source


def test_no_persistence_write():
    for module in MODULES:
        source = inspect.getsource(module)
        assert ".append(" not in source and ".flush(" not in source and "fsync" not in source


def test_no_notification():
    for module in MODULES:
        source = inspect.getsource(module).lower()
        for marker in ("notify", "deliver", "webhook", "smtp", "slack"):
            assert marker not in source, (module.__name__, marker)


def test_no_runtime_mutation():
    for module in MODULES:
        assert not _imports(module) & {"backend.main", "backend.bot_manager"}


def test_no_production_composition_or_api():
    for module in MODULES:
        source = inspect.getsource(module)
        assert "FastAPI" not in source and "backend.main" not in source
        assert "@app" not in source and "APIRouter" not in source
