"""Default-OFF Supervisor monitoring scheduler lifecycle tests.

Temporary lock paths only.  No Production path, no Production database and no
scheduler activation in Production.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

from backend.supervisor import monitoring_scheduler as scheduler_module
from backend.supervisor.monitoring_control_flags import (
    MONITORING_SCHEDULER_FLAG,
    resolve_control_flags,
)
from backend.supervisor.monitoring_scheduler import SupervisorMonitoringScheduler
from backend.supervisor.monitoring_trigger_ownership import MonitoringTriggerOwnership

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INSTANCE = "I" + "a" * 16


def make_ownership(tmp_path):
    return MonitoringTriggerOwnership(
        tmp_path / "trigger.lock", instance_id=INSTANCE, clock=lambda: NOW
    )


def make_scheduler(tmp_path, *, runner=None, enabled=True, max_backoff=8.0):
    return SupervisorMonitoringScheduler(
        runner=runner or (lambda: {"status": "SUCCESS"}),
        ownership=make_ownership(tmp_path),
        enabled=enabled,
        clock=lambda: NOW,
        max_backoff_seconds=max_backoff,
    )


def test_off_creates_no_task(tmp_path):
    calls = []
    scheduler = make_scheduler(tmp_path, runner=lambda: calls.append(1), enabled=False)
    assert scheduler.start() is False
    assert scheduler.running is False
    result = scheduler.tick(now=NOW)
    assert result.status == "DISABLED"
    assert calls == []
    assert scheduler.health(now=NOW).thread_active is False


def test_malformed_flag_creates_no_task(tmp_path):
    flags = resolve_control_flags({MONITORING_SCHEDULER_FLAG: "definitely-not-a-flag"})
    assert flags.scheduler_enabled is False
    scheduler = make_scheduler(tmp_path, enabled=flags.scheduler_enabled)
    assert scheduler.start() is False
    assert scheduler.running is False


def test_on_starts_exactly_one_task_and_stops(tmp_path):
    scheduler = make_scheduler(tmp_path)
    assert scheduler.start() is True
    assert scheduler.running is True
    assert scheduler.start() is False  # idempotent: only one worker
    assert scheduler.stop(timeout=5) is True
    assert scheduler.running is False


def test_manual_overlap_skips_runner(tmp_path):
    calls = []
    scheduler = make_scheduler(tmp_path, runner=lambda: calls.append(1))
    held = scheduler._ownership.acquire("manual", None, "SUPERVISOR_MONITORING_RUN_ONCE", 1)
    assert held.acquired
    try:
        result = scheduler.tick(now=NOW)
    finally:
        held.release()
    assert result.status == "SKIPPED_OVERLAP"
    assert result.ownership_busy is True
    assert calls == []


def test_scheduler_holds_lock_blocks_manual(tmp_path):
    observed = {}

    def runner():
        inner = scheduler_ref["scheduler"]._ownership.acquire(
            "manual-race", None, "SUPERVISOR_MONITORING_RUN_ONCE", 1
        )
        observed["inner_acquired"] = inner.acquired
        return {"status": "SUCCESS"}

    scheduler_ref = {"scheduler": make_scheduler(tmp_path, runner=runner)}
    result = scheduler_ref["scheduler"].tick(now=NOW)
    assert result.status == "RUNNER_SUCCEEDED"
    assert observed["inner_acquired"] is False


def test_failure_isolation_and_backoff(tmp_path):
    def boom():
        raise RuntimeError("scheduler run failed")

    scheduler = make_scheduler(tmp_path, runner=boom, max_backoff=600.0)
    first = scheduler.tick(now=NOW)
    second = scheduler.tick(now=NOW)
    assert first.status == "RUNNER_FAILED"
    assert second.status == "RUNNER_FAILED"
    health = scheduler.health(now=NOW)
    assert health.failure_count == 2
    assert health.consecutive_failures == 2
    assert health.state == "DEGRADED"
    assert first.next_delay_seconds <= 600.0
    assert second.next_delay_seconds >= first.next_delay_seconds


def test_success_resets_backoff(tmp_path):
    outcomes = iter([{"status": "FAILED"}, {"status": "SUCCESS"}, {"status": "SUCCESS"}])
    scheduler = make_scheduler(tmp_path, runner=lambda: next(outcomes))
    scheduler.tick(now=NOW)
    after_failure = scheduler.health(now=NOW)
    assert after_failure.consecutive_failures == 1
    scheduler.tick(now=NOW)
    assert scheduler.health(now=NOW).consecutive_failures == 0


def test_health_reflects_last_and_next_run(tmp_path):
    scheduler = make_scheduler(tmp_path)
    scheduler.tick(now=NOW)
    health = scheduler.health(now=NOW)
    assert health.run_count == 1
    assert health.success_count == 1
    assert health.last_run_id is not None
    assert health.last_status == "SUCCESS"
    assert health.next_run_at is not None
    assert health.ownership_held is False


def test_restart_creates_clean_scheduler(tmp_path):
    first = make_scheduler(tmp_path)
    assert first.start() is True
    assert first.stop(timeout=5) is True
    # A fresh scheduler over the same lock path starts cleanly (no duplicate worker).
    second = make_scheduler(tmp_path)
    assert second.health(now=NOW).run_count == 0
    assert second._ownership.current_status().active is False


def test_no_production_path_in_source():
    source = inspect.getsource(scheduler_module)
    assert "logs/runtime" not in source
    assert "supervisor_monitoring_trigger.lock" not in source
