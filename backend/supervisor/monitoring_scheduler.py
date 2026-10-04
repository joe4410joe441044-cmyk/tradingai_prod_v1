"""Default-OFF Supervisor monitoring scheduler lifecycle.

The scheduler is dormant until explicitly enabled.  When ``enabled`` is false:

- no thread/task/timer is created;
- ``start()`` is a no-op that returns ``False``;
- importing or constructing the scheduler performs no I/O.

When enabled it owns exactly one daemon worker that calls :meth:`tick` at a
bounded interval with bounded jitter and exponential backoff.  The scheduler
reuses the same OS advisory ownership lock as the manual trigger, so scheduled
and manual runs can never execute concurrently; a contended tick is recorded as
``SKIPPED_OVERLAP`` and never invokes the runner.  A failure of one run never
propagates to the application.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Callable, Literal

from pydantic import Field, field_validator

from .monitoring_models import Contract, Count, Token, aware
from .monitoring_scheduler_models import (
    MAX_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    SchedulerConfig,
)
from .monitoring_trigger_ownership import MonitoringTriggerOwnership

SCHEDULER_RUNTIME_SCHEMA_VERSION = "supervisor-monitoring-scheduler-runtime-v1"

SchedulerRuntimeState = Literal[
    "DISABLED", "IDLE", "RUNNING", "DEGRADED", "STOPPED", "FAILED",
]
TickStatus = Literal[
    "DISABLED", "SKIPPED_OVERLAP", "RUNNER_SUCCEEDED", "RUNNER_FAILED", "STOPPED",
]

DEFAULT_MAX_BACKOFF_SECONDS = 300.0
DEFAULT_JITTER_SECONDS = 5.0
_RUNNER_FAILURE_STATUSES = frozenset(
    {"FAILED", "UNAVAILABLE", "INVALID", "DISABLED", "SKIPPED_OVERLAP", "ERROR", "TIMED_OUT"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchedulerTickResult(Contract):
    status: TickStatus
    run_id: Token | None = None
    next_delay_seconds: float = Field(ge=0.0, allow_inf_nan=False)
    ownership_busy: bool = False
    reason_code: Token = "OK"


class SchedulerRuntimeHealth(Contract):
    """Bounded scheduler runtime health.  Secret-free; safe for GET."""

    schema_version: Token = SCHEDULER_RUNTIME_SCHEMA_VERSION
    enabled: bool = False
    state: SchedulerRuntimeState = "DISABLED"
    thread_active: bool = False
    ownership_held: bool = False
    interval_seconds: float = 60.0
    jitter_seconds: float = 0.0
    run_count: Count = 0
    success_count: Count = 0
    failure_count: Count = 0
    skipped_overlap_count: Count = 0
    consecutive_failures: Count = 0
    last_run_id: Token | None = None
    last_status: Token | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    next_run_at: datetime | None = None
    backoff_seconds: float = 0.0
    updated_at: datetime

    _aware = field_validator(
        "last_started_at", "last_finished_at", "next_run_at", "updated_at"
    )(lambda value: None if value is None else aware(value))


class SupervisorMonitoringScheduler:
    """Bounded, default-OFF scheduler over an injected one-shot runner callable."""

    def __init__(
        self,
        *,
        runner: Callable[[], Any],
        ownership: MonitoringTriggerOwnership,
        config: SchedulerConfig | None = None,
        enabled: bool = False,
        operation: str = "SUPERVISOR_MONITORING_SCHEDULED_RUN_ONCE",
        clock: Callable[[], datetime] | None = None,
        jitter_provider: Callable[[float], float] | None = None,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    ) -> None:
        if not callable(runner):
            raise TypeError("an explicit callable runner dependency is required")
        if not isinstance(ownership, MonitoringTriggerOwnership):
            raise TypeError("ownership must be a MonitoringTriggerOwnership")
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        self._runner = runner
        self._ownership = ownership
        self._config = config if config is not None else SchedulerConfig()
        self._enabled = bool(enabled)
        self._operation = operation
        self._clock = clock if clock is not None else _utcnow
        self._jitter_provider = jitter_provider
        self._max_backoff = max(0.0, float(max_backoff_seconds))

        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._state: SchedulerRuntimeState = "DISABLED"
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._skipped_overlap_count = 0
        self._consecutive_failures = 0
        self._generation = 0
        self._last_run_id: str | None = None
        self._last_status: str | None = None
        self._last_started_at: datetime | None = None
        self._last_finished_at: datetime | None = None
        self._next_run_at: datetime | None = None
        self._backoff_seconds = 0.0
        if not self._enabled:
            self._state = "DISABLED"

    # -- lifecycle -----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def interval_seconds(self) -> float:
        return float(self._config.interval_seconds)

    @property
    def jitter_seconds(self) -> float:
        return 0.0 if self._jitter_provider is None else float(self._jitter_provider(0.0))

    def start(self) -> bool:
        """Create exactly one worker iff enabled.  Never creates one when OFF."""

        if not self._enabled:
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event = threading.Event()
            self._state = "IDLE"
            self._thread = threading.Thread(
                target=self._loop, name="supervisor-monitoring-scheduler", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float | None = None) -> bool:
        """Deterministic shutdown.  Returns True when the worker has exited."""

        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
        if thread is None:
            self._state = "DISABLED" if not self._enabled else "STOPPED"
            return True
        if stop_event is not None:
            stop_event.set()
        wait_for = timeout if timeout is not None else self._config.shutdown_timeout_seconds
        thread.join(timeout=wait_for)
        if thread.is_alive():
            self._state = "FAILED"
            return False
        with self._lock:
            self._thread = None
            self._state = "STOPPED"
        return True

    def _loop(self) -> None:
        stop_event = self._stop_event
        while stop_event is not None and not stop_event.is_set():
            result = self.tick()
            if stop_event.is_set():
                break
            delay = max(0.05, float(result.next_delay_seconds))
            if stop_event.wait(delay):
                break

    # -- one tick ------------------------------------------------------------

    def _deterministic_run_id(self, moment: datetime) -> str:
        slot = int(moment.timestamp()) // max(1, int(self.interval_seconds))
        payload = f"{self._operation}:{slot}"
        return "S" + sha256(payload.encode("utf-8")).hexdigest()[:31]

    def tick(self, *, now: datetime | None = None) -> SchedulerTickResult:
        if not self._enabled:
            self._state = "DISABLED"
            return SchedulerTickResult(
                status="DISABLED", next_delay_seconds=self.interval_seconds,
                reason_code="FLAG_OFF",
            )
        if self._stop_event is not None and self._stop_event.is_set():
            self._state = "STOPPED"
            return SchedulerTickResult(
                status="STOPPED", next_delay_seconds=self.interval_seconds,
                reason_code="STOPPED",
            )
        moment = aware(now) if now is not None else aware(self._clock())
        run_id = self._deterministic_run_id(moment)
        self._generation += 1

        lease = self._ownership.acquire(
            run_id, run_id, self._operation, self._generation
        )
        if not lease.acquired:
            self._skipped_overlap_count += 1
            self._state = "DEGRADED"
            self._next_run_at = moment + timedelta(seconds=self.interval_seconds)
            return SchedulerTickResult(
                status="SKIPPED_OVERLAP", next_delay_seconds=self.interval_seconds,
                ownership_busy=True, reason_code="OWNERSHIP_BUSY",
            )

        self._state = "RUNNING"
        started = moment
        success = False
        try:
            outcome = self._runner()
            success = _classify_outcome(outcome)
        except Exception:  # noqa: BLE001 - one failed run must not kill the app
            success = False
        finally:
            try:
                lease.release()
            except Exception:  # noqa: BLE001
                pass

        finished = aware(self._clock())
        self._last_run_id = run_id
        self._last_started_at = started
        self._last_finished_at = finished
        if success:
            self._run_count += 1
            self._success_count += 1
            self._consecutive_failures = 0
            self._backoff_seconds = 0.0
            self._last_status = "SUCCESS"
            self._state = "IDLE"
            delay = self._delay(0)
            status: TickStatus = "RUNNER_SUCCEEDED"
        else:
            self._run_count += 1
            self._failure_count += 1
            self._consecutive_failures += 1
            self._last_status = "FAILED"
            self._state = "DEGRADED"
            delay = self._delay(self._consecutive_failures)
            status = "RUNNER_FAILED"
        self._next_run_at = finished + timedelta(seconds=delay)
        return SchedulerTickResult(
            status=status, run_id=run_id, next_delay_seconds=delay,
            reason_code="OK" if success else "RUN_FAILED",
        )

    def _delay(self, failures: int) -> float:
        interval = self.interval_seconds
        if failures <= 0:
            base = interval
        else:
            base = min(interval * (2 ** min(failures, 8)), max(interval, self._max_backoff))
        jitter = self._jitter_provider(base) if self._jitter_provider is not None else 0.0
        jitter = max(0.0, min(float(jitter), interval))
        return max(MIN_INTERVAL_SECONDS * 0.1, base + jitter)

    # -- health --------------------------------------------------------------

    def health(self, *, now: datetime | None = None) -> SchedulerRuntimeHealth:
        return SchedulerRuntimeHealth(
            enabled=self._enabled,
            state=self._state,
            thread_active=self.running,
            ownership_held=self._ownership.current_status().active,
            interval_seconds=self.interval_seconds,
            jitter_seconds=self.jitter_seconds,
            run_count=self._run_count,
            success_count=self._success_count,
            failure_count=self._failure_count,
            skipped_overlap_count=self._skipped_overlap_count,
            consecutive_failures=self._consecutive_failures,
            last_run_id=self._last_run_id,
            last_status=self._last_status,
            last_started_at=self._last_started_at,
            last_finished_at=self._last_finished_at,
            next_run_at=self._next_run_at,
            backoff_seconds=self._backoff_seconds,
            updated_at=aware(now) if now is not None else aware(self._clock()),
        )


def _classify_outcome(outcome: Any) -> bool:
    if outcome is None:
        return True
    status = None
    if isinstance(outcome, dict):
        status = outcome.get("status")
    else:
        status = getattr(outcome, "status", None)
        if status is None:
            status = getattr(outcome, "outcome", None)
    if status is None:
        return True
    return str(status).upper() not in _RUNNER_FAILURE_STATUSES


__all__ = [
    "DEFAULT_JITTER_SECONDS",
    "DEFAULT_MAX_BACKOFF_SECONDS",
    "SchedulerRuntimeHealth",
    "SchedulerRuntimeState",
    "SchedulerTickResult",
    "SupervisorMonitoringScheduler",
    "TickStatus",
]
