"""Pure deterministic scheduler state model and transition engine.

No clock, task, thread, timer, lock, I/O or persistence.  The caller supplies
every timestamp and run identifier explicitly, so identical inputs produce
identical outputs.  This module never maps any state to trading authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .monitoring_models import Contract, Token, aware
from .monitoring_scheduler_models import (
    ALREADY_ENABLED, ALREADY_STARTING, ALREADY_STOPPED, ALREADY_STOPPING,
    CONFIG_VERSION, DISABLED_BY_CONFIG, DUPLICATE_RUN_START, INVALID_TRANSITION,
    RECOVERED, REJECTED_ALREADY_RUNNING, RUN_COMPLETED, RUN_DEGRADED, RUN_FAILED,
    RUN_STARTED_MANUAL, RUN_STARTED_SCHEDULED,
    SHUTDOWN_TIMEOUT, STARTED, STARTUP_FAILURE, START_REQUESTED, STOPPED_CLEAN,
    STOP_REQUESTED, SchedulerState, TriggerType,
)

STATE_SCHEMA_VERSION = "scheduler-state-v1"

SchedulerEvent = Literal[
    "INITIALIZE", "ENABLE_REQUESTED", "STARTUP_COMPLETE", "RUN_START", "RUN_SUCCESS",
    "RUN_PARTIAL", "RUN_FAILURE", "DEGRADED_RECOVERY", "STOP_REQUESTED", "STOP_COMPLETE",
    "STARTUP_FAILURE", "SHUTDOWN_TIMEOUT", "DISABLE",
]

_RUN_ID_STATES = frozenset({"RUNNING", "STOPPING"})


def _aware_optional(value):
    return None if value is None else aware(value)


def _sorted_unique(values):
    return tuple(sorted(set(values)))


class SchedulerStateModel(Contract):
    """Immutable scheduler state with explicit, caller-supplied timestamps."""

    schema_version: Token = STATE_SCHEMA_VERSION
    state: SchedulerState = "DISABLED"
    enabled: bool = False
    reason_codes: tuple[Token, ...] = Field(default=(), max_length=32)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_transition_at: datetime | None = None
    current_run_id: Token | None = None
    state_revision: int = Field(default=0, strict=True, ge=0, le=10**12)
    config_version: Token = CONFIG_VERSION
    degraded_reasons: tuple[Token, ...] = Field(default=(), max_length=32)
    failure_code: Token | None = None

    _aware_fields = field_validator(
        "started_at", "stopped_at", "last_transition_at"
    )(_aware_optional)

    @field_validator("reason_codes", "degraded_reasons")
    @classmethod
    def _sorted(cls, value):
        if len(value) > 32:
            raise ValueError("too many reason codes")
        return _sorted_unique(value)

    @model_validator(mode="after")
    def _coherent(self):
        if self.state == "DISABLED" and self.enabled:
            raise ValueError("DISABLED cannot be enabled")
        if self.state == "RUNNING" and not self.enabled:
            raise ValueError("disabled scheduler cannot be RUNNING")
        if self.state == "RUNNING" and not self.current_run_id:
            raise ValueError("RUNNING requires a current_run_id")
        if self.current_run_id is not None and self.state not in _RUN_ID_STATES:
            raise ValueError("current_run_id is only valid while RUNNING or STOPPING")
        if self.state == "IDLE" and self.current_run_id is not None:
            raise ValueError("IDLE cannot retain a current_run_id")
        if self.state == "FAILED" and not self.failure_code:
            raise ValueError("FAILED requires a failure_code")
        if self.started_at is not None and self.stopped_at is not None:
            if self.stopped_at < self.started_at:
                raise ValueError("stopped_at cannot precede started_at")
        return self


class SchedulerTransition(Contract):
    """An explicit transition command with caller-supplied timestamp and IDs."""

    event: SchedulerEvent
    requested_at: datetime
    run_id: Token | None = None
    trigger_type: TriggerType | None = None
    failure_code: Token | None = None
    reason_codes: tuple[Token, ...] = Field(default=(), max_length=32)
    escalate_failure: bool = False

    _aware = field_validator("requested_at")(aware)

    @field_validator("reason_codes")
    @classmethod
    def _sorted(cls, value):
        return _sorted_unique(value)


class TransitionOutcome(Contract):
    """The resulting state plus an explicit applied/idempotent/invalid verdict."""

    state: SchedulerStateModel
    previous_state: SchedulerState
    applied: bool
    idempotent: bool
    reason_code: Token


def initial_scheduler_state(
    *, config_version: str = CONFIG_VERSION, at: datetime | None = None
) -> SchedulerStateModel:
    """The initial state is always DISABLED; enabling is an explicit event."""

    return SchedulerStateModel(
        state="DISABLED", enabled=False, config_version=config_version,
        last_transition_at=None if at is None else aware(at),
    )


def _outcome(previous, command, *, state, reason, applied, idempotent, **changes):
    if applied:
        fields = dict(
            enabled=previous.enabled, current_run_id=previous.current_run_id,
            failure_code=previous.failure_code, started_at=previous.started_at,
            stopped_at=previous.stopped_at, degraded_reasons=previous.degraded_reasons,
        )
        fields.update(changes)
        payload = previous.model_dump()
        payload.update(
            state=state, reason_codes=(reason,),
            state_revision=previous.state_revision + 1,
            last_transition_at=command.requested_at, **fields,
        )
        new_state = SchedulerStateModel.model_validate(payload)
    else:
        new_state = previous
    return TransitionOutcome(
        state=new_state, previous_state=previous.state, applied=applied,
        idempotent=idempotent, reason_code=reason,
    )


def _invalid(previous, reason=INVALID_TRANSITION):
    return TransitionOutcome(
        state=previous, previous_state=previous.state, applied=False,
        idempotent=False, reason_code=reason,
    )


def _idempotent(previous, reason):
    return TransitionOutcome(
        state=previous, previous_state=previous.state, applied=False,
        idempotent=True, reason_code=reason,
    )


def transition_state(previous: SchedulerStateModel, command: SchedulerTransition) -> TransitionOutcome:
    """Pure deterministic transition.  Performs no work and never mutates input."""

    event = command.event
    state = previous.state

    if event == "INITIALIZE":
        if state == "DISABLED":
            return _idempotent(previous, DISABLED_BY_CONFIG)
        return _invalid(previous)

    if event == "ENABLE_REQUESTED":
        if state == "DISABLED":
            return _outcome(
                previous, command, state="STARTING", reason=START_REQUESTED, applied=True,
                idempotent=False, enabled=True, current_run_id=None, failure_code=None,
                started_at=command.requested_at, stopped_at=None,
            )
        if state == "STOPPED":
            return _outcome(
                previous, command, state="STARTING", reason=START_REQUESTED, applied=True,
                idempotent=False, enabled=True, current_run_id=None, failure_code=None,
                started_at=command.requested_at, stopped_at=None,
            )
        if state == "STARTING":
            return _idempotent(previous, ALREADY_STARTING)
        if state in ("IDLE", "RUNNING", "DEGRADED"):
            return _idempotent(previous, ALREADY_ENABLED)
        return _invalid(previous)

    if event == "STARTUP_COMPLETE":
        if state == "STARTING":
            return _outcome(
                previous, command, state="IDLE", reason=STARTED, applied=True, idempotent=False,
            )
        return _invalid(previous)

    if event == "STARTUP_FAILURE":
        if state != "STARTING":
            return _invalid(previous)
        return _outcome(
            previous, command, state="FAILED",
            reason=command.failure_code or STARTUP_FAILURE, applied=True, idempotent=False,
            failure_code=command.failure_code or STARTUP_FAILURE,
            stopped_at=command.requested_at, current_run_id=None,
        )

    if event == "RUN_START":
        if not command.run_id:
            return _invalid(previous)
        if state == "RUNNING":
            if command.run_id == previous.current_run_id:
                return _idempotent(previous, DUPLICATE_RUN_START)
            return _invalid(previous, REJECTED_ALREADY_RUNNING)
        if state in ("IDLE", "DEGRADED"):
            reason = RUN_STARTED_MANUAL if command.trigger_type == "MANUAL" else RUN_STARTED_SCHEDULED
            return _outcome(
                previous, command, state="RUNNING", reason=reason, applied=True,
                idempotent=False, enabled=True, current_run_id=command.run_id,
                failure_code=None, degraded_reasons=(),
            )
        return _invalid(previous)

    if event == "RUN_SUCCESS":
        if state == "RUNNING":
            return _outcome(
                previous, command, state="IDLE", reason=RUN_COMPLETED, applied=True,
                idempotent=False, current_run_id=None, degraded_reasons=(),
            )
        return _invalid(previous)

    if event == "RUN_PARTIAL":
        if state == "RUNNING":
            reasons = tuple(sorted(set(previous.degraded_reasons) | {"RUN_DEGRADED"}))
            return _outcome(
                previous, command, state="DEGRADED", reason=RUN_DEGRADED, applied=True,
                idempotent=False, current_run_id=None, degraded_reasons=reasons,
            )
        return _invalid(previous)

    if event == "RUN_FAILURE":
        if state != "RUNNING":
            return _invalid(previous)
        if command.escalate_failure:
            return _outcome(
                previous, command, state="FAILED",
                reason=command.failure_code or RUN_FAILED, applied=True, idempotent=False,
                failure_code=command.failure_code or RUN_FAILED, current_run_id=None,
            )
        reasons = tuple(sorted(set(previous.degraded_reasons) | {RUN_FAILED}))
        return _outcome(
            previous, command, state="DEGRADED", reason=RUN_FAILED, applied=True,
            idempotent=False, current_run_id=None, degraded_reasons=reasons,
        )

    if event == "DEGRADED_RECOVERY":
        if state == "DEGRADED":
            return _outcome(
                previous, command, state="IDLE", reason=RECOVERED, applied=True,
                idempotent=False, current_run_id=None, degraded_reasons=(),
            )
        return _invalid(previous)

    if event == "STOP_REQUESTED":
        if state == "STOPPING":
            return _idempotent(previous, ALREADY_STOPPING)
        if state == "STOPPED":
            return _idempotent(previous, ALREADY_STOPPED)
        if state in ("STARTING", "IDLE", "DEGRADED", "RUNNING"):
            return _outcome(
                previous, command, state="STOPPING", reason=STOP_REQUESTED, applied=True,
                idempotent=False,
            )
        return _invalid(previous)

    if event == "STOP_COMPLETE":
        if state == "STOPPING":
            return _outcome(
                previous, command, state="STOPPED", reason=STOPPED_CLEAN, applied=True,
                idempotent=False, enabled=False, current_run_id=None,
                stopped_at=command.requested_at, failure_code=None, degraded_reasons=(),
            )
        return _invalid(previous)

    if event == "SHUTDOWN_TIMEOUT":
        if state == "STOPPING":
            return _outcome(
                previous, command, state="FAILED", reason=SHUTDOWN_TIMEOUT, applied=True,
                idempotent=False, enabled=False, current_run_id=None,
                failure_code=SHUTDOWN_TIMEOUT, stopped_at=command.requested_at,
            )
        return _invalid(previous)

    if event == "DISABLE":
        if state in ("STARTING", "IDLE", "DEGRADED", "STOPPED"):
            return _outcome(
                previous, command, state="DISABLED", reason=DISABLED_BY_CONFIG, applied=True,
                idempotent=False, enabled=False, current_run_id=None, failure_code=None,
                stopped_at=command.requested_at, degraded_reasons=(),
            )
        if state == "DISABLED":
            return _idempotent(previous, DISABLED_BY_CONFIG)
        return _invalid(previous)

    return _invalid(previous)
