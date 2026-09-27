"""Phase 3A scheduler state model and pure transition engine tests."""
from datetime import datetime, timedelta, timezone
import inspect
import pytest
from pydantic import ValidationError

from backend.supervisor import monitoring_scheduler_state as state_module
from backend.supervisor.monitoring_scheduler_state import (
    SchedulerStateModel, SchedulerTransition, initial_scheduler_state, transition_state,
)

NOW = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)


def ts(minutes=0):
    return NOW + timedelta(minutes=minutes)


def cmd(event, minutes=0, **over):
    data = dict(event=event, requested_at=ts(minutes))
    data.update(over)
    return SchedulerTransition(**data)


def to_idle():
    s = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED")).state
    return transition_state(s, cmd("STARTUP_COMPLETE")).state


def to_running():
    return transition_state(to_idle(), cmd("RUN_START", run_id="run-1")).state


# --- States (11-22) --------------------------------------------------------

def test_state_initial_disabled():
    s = initial_scheduler_state()
    assert s.state == "DISABLED" and s.enabled is False and s.state_revision == 0


def test_state_starting():
    assert transition_state(
        initial_scheduler_state(), cmd("ENABLE_REQUESTED")
    ).state.state == "STARTING"


def test_state_idle():
    assert to_idle().state == "IDLE"


def test_state_running():
    s = to_running()
    assert s.state == "RUNNING" and s.current_run_id == "run-1"


def test_state_degraded():
    s = transition_state(to_running(), cmd("RUN_PARTIAL")).state
    assert s.state == "DEGRADED" and "RUN_DEGRADED" in s.degraded_reasons


def test_state_stopping():
    assert transition_state(to_idle(), cmd("STOP_REQUESTED")).state.state == "STOPPING"


def test_state_stopped():
    stopping = transition_state(to_idle(), cmd("STOP_REQUESTED")).state
    stopped = transition_state(stopping, cmd("STOP_COMPLETE", minutes=1)).state
    assert stopped.state == "STOPPED" and stopped.enabled is False


def test_state_failed():
    starting = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED")).state
    failed = transition_state(starting, cmd("STARTUP_FAILURE")).state
    assert failed.state == "FAILED" and failed.failure_code == "STARTUP_FAILURE"


def test_state_disabled_cannot_be_enabled():
    with pytest.raises(ValidationError):
        SchedulerStateModel(state="DISABLED", enabled=True)


def test_state_disabled_cannot_be_running():
    with pytest.raises(ValidationError):
        SchedulerStateModel(state="RUNNING", enabled=False, current_run_id="run-1")


def test_state_running_requires_run_id():
    with pytest.raises(ValidationError):
        SchedulerStateModel(state="RUNNING", enabled=True)


def test_state_failed_requires_code():
    with pytest.raises(ValidationError):
        SchedulerStateModel(state="FAILED", enabled=True)


def test_state_idle_cannot_retain_run_id():
    with pytest.raises(ValidationError):
        SchedulerStateModel(state="IDLE", enabled=True, current_run_id="run-1")


def test_state_stopped_before_start_rejected():
    with pytest.raises(ValidationError):
        SchedulerStateModel(
            state="STOPPED", enabled=False, started_at=ts(5), stopped_at=ts(1)
        )


def test_state_stable_reason_ordering():
    s = SchedulerStateModel(reason_codes=("B", "A"), degraded_reasons=("Z", "A"))
    assert s.reason_codes == ("A", "B") and s.degraded_reasons == ("A", "Z")


# --- Transitions (23-37) ---------------------------------------------------

def test_transition_disabled_initialization():
    outcome = transition_state(initial_scheduler_state(), cmd("INITIALIZE"))
    assert outcome.state.state == "DISABLED" and outcome.idempotent is True


def test_transition_start_request():
    outcome = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED"))
    assert outcome.applied is True and outcome.state.state == "STARTING"
    assert outcome.state.started_at == NOW and outcome.state.state_revision == 1


def test_transition_startup_complete():
    starting = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED")).state
    outcome = transition_state(starting, cmd("STARTUP_COMPLETE"))
    assert outcome.state.state == "IDLE" and outcome.reason_code == "STARTED"


def test_transition_run_start():
    outcome = transition_state(to_idle(), cmd("RUN_START", run_id="run-1"))
    assert outcome.state.state == "RUNNING" and outcome.reason_code == "RUN_STARTED_SCHEDULED"
    manual = transition_state(to_idle(), cmd("RUN_START", run_id="m1", trigger_type="MANUAL"))
    assert manual.reason_code == "RUN_STARTED_MANUAL"


def test_transition_run_success():
    outcome = transition_state(to_running(), cmd("RUN_SUCCESS"))
    assert outcome.state.state == "IDLE" and outcome.state.current_run_id is None


def test_transition_run_partial_then_recovery():
    degraded = transition_state(to_running(), cmd("RUN_PARTIAL"))
    assert degraded.state.state == "DEGRADED"
    recovered = transition_state(degraded.state, cmd("DEGRADED_RECOVERY"))
    assert recovered.state.state == "IDLE" and recovered.state.degraded_reasons == ()


def test_transition_run_failure_policy():
    degraded = transition_state(to_running(), cmd("RUN_FAILURE"))
    assert degraded.state.state == "DEGRADED"
    failed = transition_state(to_running(), cmd("RUN_FAILURE", escalate_failure=True))
    assert failed.state.state == "FAILED" and failed.state.failure_code


def test_transition_stop_request():
    outcome = transition_state(to_running(), cmd("STOP_REQUESTED"))
    assert outcome.state.state == "STOPPING" and outcome.state.current_run_id == "run-1"


def test_transition_stop_complete():
    stopping = transition_state(to_idle(), cmd("STOP_REQUESTED")).state
    outcome = transition_state(stopping, cmd("STOP_COMPLETE", minutes=1))
    assert outcome.state.state == "STOPPED" and outcome.state.stopped_at == ts(1)


def test_transition_startup_failure():
    starting = transition_state(initial_scheduler_state(), cmd("ENABLE_REQUESTED")).state
    outcome = transition_state(starting, cmd("STARTUP_FAILURE", failure_code="OWNERSHIP_UNAVAILABLE"))
    assert outcome.state.state == "FAILED"
    assert outcome.state.failure_code == "OWNERSHIP_UNAVAILABLE"


def test_transition_shutdown_timeout():
    stopping = transition_state(to_idle(), cmd("STOP_REQUESTED")).state
    outcome = transition_state(stopping, cmd("SHUTDOWN_TIMEOUT", minutes=1))
    assert outcome.state.state == "FAILED"
    assert outcome.state.failure_code == "SHUTDOWN_TIMEOUT"


def test_transition_invalid():
    outcome = transition_state(initial_scheduler_state(), cmd("RUN_START", run_id="r"))
    assert outcome.applied is False and outcome.idempotent is False
    assert outcome.reason_code == "INVALID_TRANSITION"
    assert outcome.state.state == "DISABLED"


def test_transition_duplicate_run_start_idempotent():
    running = to_running()
    outcome = transition_state(running, cmd("RUN_START", run_id="run-1"))
    assert outcome.idempotent is True and outcome.reason_code == "DUPLICATE_RUN_START"
    assert outcome.state.state_revision == running.state_revision

    conflicting = transition_state(running, cmd("RUN_START", run_id="run-2"))
    assert conflicting.applied is False and conflicting.reason_code == "REJECTED_ALREADY_RUNNING"


def test_transition_enable_idempotent():
    idle = to_idle()
    outcome = transition_state(idle, cmd("ENABLE_REQUESTED"))
    assert outcome.idempotent is True and outcome.reason_code == "ALREADY_ENABLED"


def test_transition_does_not_mutate_input():
    idle = to_idle()
    before = idle.model_dump()
    transition_state(idle, cmd("RUN_START", run_id="run-1"))
    assert idle.model_dump() == before
    assert idle.model_config["frozen"] is True


def test_transition_revision_monotonic():
    s = initial_scheduler_state()
    for event in ("ENABLE_REQUESTED", "STARTUP_COMPLETE", "RUN_START"):
        kwargs = {"run_id": "run-1"} if event == "RUN_START" else {}
        s = transition_state(s, cmd(event, **kwargs)).state
    assert s.state_revision == 3


def test_state_module_has_no_io_or_tasks():
    source = inspect.getsource(state_module)
    for forbidden in ("import os", "asyncio", "threading", "create_task", "Thread(", "open("):
        assert forbidden not in source
