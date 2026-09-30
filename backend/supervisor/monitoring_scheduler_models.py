"""Pure Phase 3A scheduler configuration, feature-flag and run/overlap models.

No clock, environment, file/socket/database I/O, provider or trading authority.
Every timestamp is supplied explicitly by the caller.  The models are frozen and
reject unknown fields, so serialization is deterministic and invalid input fails
closed.  Enabling the scheduler grants no trading authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .monitoring_models import Availability, Contract, Count, Freshness, Token, aware

CONFIG_VERSION = "scheduler-config-v1"
RUN_SCHEMA_VERSION = "scheduler-run-v1"

# One canonical truthy vocabulary shared with the existing feature flags.
TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
FALSY_VALUES = frozenset({"0", "false", "no", "off"})

FeatureFlagSource = Literal["ENV", "DEFAULT_OFF", "INVALID"]
SchedulerState = Literal[
    "DISABLED", "STARTING", "IDLE", "RUNNING", "DEGRADED", "STOPPING", "STOPPED", "FAILED",
]
TriggerType = Literal["SCHEDULED", "MANUAL"]
RunStatus = Literal[
    "REQUESTED", "RUNNING", "SUCCESS", "PARTIAL", "DEGRADED", "TIMED_OUT", "CANCELLED",
    "FAILED", "SKIPPED_OVERLAP",
]
TerminalRunStatus = frozenset(
    {"SUCCESS", "PARTIAL", "DEGRADED", "TIMED_OUT", "CANCELLED", "FAILED", "SKIPPED_OVERLAP"}
)
FailureRunStatus = frozenset({"TIMED_OUT", "CANCELLED", "FAILED"})
OverlapDecision = Literal[
    "ACCEPT", "REJECT_OVERLAP", "REPLAY_EXISTING", "DISABLED", "INVALID",
]
StateRecoveryStatus = Literal["OK", "PARTIAL", "CORRUPT", "UNAVAILABLE", "NOT_ATTEMPTED"]

# Feature-flag reason codes.
FLAG_OFF = "FLAG_OFF"
FLAG_INVALID = "FLAG_INVALID"

# Overlap decision reason codes.
ACCEPTED = "ACCEPTED"
IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
ACTIVE_RUN_IN_PROGRESS = "ACTIVE_RUN_IN_PROGRESS"
SCHEDULER_DISABLED = "SCHEDULER_DISABLED"
SCHEDULER_STOPPED = "SCHEDULER_STOPPED"
SCHEDULER_STOPPING = "SCHEDULER_STOPPING"
SCHEDULER_FAILED = "SCHEDULER_FAILED"
INVALID_REPLAY_REFERENCE = "INVALID_REPLAY_REFERENCE"

# Scheduler state / transition reason codes.
START_REQUESTED = "START_REQUESTED"
STARTED = "STARTED"
RUN_STARTED_SCHEDULED = "RUN_STARTED_SCHEDULED"
RUN_STARTED_MANUAL = "RUN_STARTED_MANUAL"
RUN_COMPLETED = "RUN_COMPLETED"
RUN_DEGRADED = "RUN_DEGRADED"
RUN_FAILED = "RUN_FAILED"
RECOVERED = "RECOVERED"
STOP_REQUESTED = "STOP_REQUESTED"
STOPPED_CLEAN = "STOPPED_CLEAN"
STARTUP_FAILURE = "STARTUP_FAILURE"
SHUTDOWN_TIMEOUT = "SHUTDOWN_TIMEOUT"
DISABLED_BY_CONFIG = "DISABLED_BY_CONFIG"
INVALID_TRANSITION = "INVALID_TRANSITION"
ALREADY_STARTING = "ALREADY_STARTING"
ALREADY_ENABLED = "ALREADY_ENABLED"
ALREADY_STOPPING = "ALREADY_STOPPING"
ALREADY_STOPPED = "ALREADY_STOPPED"
DUPLICATE_RUN_START = "DUPLICATE_RUN_START"
REJECTED_ALREADY_RUNNING = "REJECTED_ALREADY_RUNNING"

# Configuration bounds (single source of truth for the validated model).
MIN_INTERVAL_SECONDS = 15.0
MAX_INTERVAL_SECONDS = 3600.0
MIN_STARTUP_DELAY_SECONDS = 0.0
MAX_STARTUP_DELAY_SECONDS = 600.0
MIN_RUN_TIMEOUT_SECONDS = 1.0
MAX_RUN_TIMEOUT_SECONDS = 60.0
MIN_SOURCE_TIMEOUT_SECONDS = 0.1
MAX_SOURCE_TIMEOUT_SECONDS = 10.0
MIN_SHUTDOWN_TIMEOUT_SECONDS = 0.5
MAX_SHUTDOWN_TIMEOUT_SECONDS = 30.0
MAX_PAGES_BOUND = 16
MAX_PAGE_ITEMS_BOUND = 200
MAX_QUERY_BUDGET = 800
MIN_SCAN_BYTES = 64 * 1024
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_SCAN_LINES = 500000
MIN_RECORD_BYTES = 1024
MAX_RECORD_BYTES = 10 * 1024 * 1024
MAX_OBSERVATIONS = 800
MAX_STATE_EVENTS = 5000
MAX_RECOVERY_RECORDS = 500000
MAX_RECOVERY_BYTES = 256 * 1024 * 1024


def _sorted_unique(values):
    if len({v for v in values}) != len(values):
        values = tuple(sorted(set(values)))
    else:
        values = tuple(sorted(values))
    return values


def _path(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("state_journal_path must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise ValueError("state_journal_path must be a single line")
    if len(value) > 1024:
        raise ValueError("state_journal_path is too long")
    return value


class SchedulerConfig(Contract):
    """Validated, immutable, secret-free scheduler configuration.

    Defaults to ``enabled=False``; no environment is read here.  An explicit
    ``state_journal_path`` is required only when enabled or when persistence is
    explicitly requested.
    """

    config_version: Token = CONFIG_VERSION
    enabled: bool = False
    interval_seconds: float = Field(default=60.0, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS)
    startup_delay_seconds: float = Field(
        default=30.0, ge=MIN_STARTUP_DELAY_SECONDS, le=MAX_STARTUP_DELAY_SECONDS
    )
    run_timeout_seconds: float = Field(
        default=10.0, ge=MIN_RUN_TIMEOUT_SECONDS, le=MAX_RUN_TIMEOUT_SECONDS
    )
    source_timeout_seconds: float = Field(
        default=2.0, ge=MIN_SOURCE_TIMEOUT_SECONDS, le=MAX_SOURCE_TIMEOUT_SECONDS
    )
    shutdown_timeout_seconds: float = Field(
        default=5.0, ge=MIN_SHUTDOWN_TIMEOUT_SECONDS, le=MAX_SHUTDOWN_TIMEOUT_SECONDS
    )
    max_pages: int = Field(default=4, strict=True, ge=1, le=MAX_PAGES_BOUND)
    max_page_items: int = Field(default=200, strict=True, ge=1, le=MAX_PAGE_ITEMS_BOUND)
    query_budget: int = Field(default=800, strict=True, ge=1, le=MAX_QUERY_BUDGET)
    max_scan_bytes: int = Field(default=8 * 1024 * 1024, strict=True, ge=MIN_SCAN_BYTES, le=MAX_SCAN_BYTES)
    max_scan_lines: int = Field(default=50000, strict=True, ge=1, le=MAX_SCAN_LINES)
    max_record_bytes: int = Field(default=256 * 1024, strict=True, ge=MIN_RECORD_BYTES, le=MAX_RECORD_BYTES)
    max_observations: int = Field(default=128, strict=True, ge=1, le=MAX_OBSERVATIONS)
    max_state_events: int = Field(default=256, strict=True, ge=1, le=MAX_STATE_EVENTS)
    recovery_max_records: int = Field(
        default=50000, strict=True, ge=1, le=MAX_RECOVERY_RECORDS
    )
    recovery_max_bytes: int = Field(
        default=8 * 1024 * 1024, strict=True, ge=1, le=MAX_RECOVERY_BYTES
    )
    state_journal_path: str | None = None
    persistence_requested: bool = False

    _path_validator = field_validator("state_journal_path")(_path)

    @model_validator(mode="after")
    def _cross_field(self):
        if self.source_timeout_seconds >= self.run_timeout_seconds:
            raise ValueError("source_timeout_seconds must be less than run_timeout_seconds")
        if self.query_budget > self.max_pages * self.max_page_items:
            raise ValueError("query_budget exceeds max_pages * max_page_items")
        if (self.enabled or self.persistence_requested) and not self.state_journal_path:
            raise ValueError(
                "state_journal_path is required when enabled or persistence_requested"
            )
        return self

    def next_run_at(self, reference: datetime) -> datetime:
        """Deterministic next scheduled time from an explicit reference."""

        return aware(reference) + timedelta(seconds=self.interval_seconds)


class FeatureFlagStatus(Contract):
    """Pure representation of the scheduler feature flag.  No environment access."""

    enabled: bool = False
    source: FeatureFlagSource = "DEFAULT_OFF"
    raw_value_present: bool = False
    valid: bool = True
    reason_code: Token | None = FLAG_OFF


def resolve_feature_flag_status(raw_value: str | None) -> FeatureFlagStatus:
    """Resolve an already-read raw value; never reads the environment."""

    if raw_value is None or str(raw_value).strip() == "":
        return FeatureFlagStatus(
            enabled=False, source="DEFAULT_OFF", raw_value_present=False,
            valid=True, reason_code=FLAG_OFF,
        )
    token = str(raw_value).strip().lower()
    if token in TRUTHY_VALUES:
        return FeatureFlagStatus(
            enabled=True, source="ENV", raw_value_present=True, valid=True, reason_code=None,
        )
    if token in FALSY_VALUES:
        return FeatureFlagStatus(
            enabled=False, source="ENV", raw_value_present=True, valid=True, reason_code=FLAG_OFF,
        )
    return FeatureFlagStatus(
        enabled=False, source="INVALID", raw_value_present=True, valid=False,
        reason_code=FLAG_INVALID,
    )


class MonitoringRun(Contract):
    """A bounded run lifecycle record.  Contains no raw evidence or stack trace."""

    schema_version: Token = RUN_SCHEMA_VERSION
    run_id: Token
    trigger_type: TriggerType
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: RunStatus = "REQUESTED"
    timeout_seconds: float = Field(
        default=10.0, ge=MIN_RUN_TIMEOUT_SECONDS, le=MAX_RUN_TIMEOUT_SECONDS
    )
    duration_ms: Count | None = None
    observation_count: Count = 0
    evaluation_count: Count = 0
    anomaly_count: Count = 0
    active_anomaly_count: Count = 0
    eligible_notification_count: Count = 0
    state_event_count: Count = 0
    source_freshness: Freshness | None = None
    source_availability: Availability | None = None
    partial_result: bool = False
    warnings: tuple[Token, ...] = Field(default=(), max_length=32)
    error_code: Token | None = None
    error_summary: Token | None = None

    _aware_fields = field_validator("requested_at", "started_at", "completed_at")(
        lambda value: None if value is None else aware(value)
    )

    @field_validator("warnings")
    @classmethod
    def _warnings(cls, value):
        if len(value) > 32:
            raise ValueError("too many warnings")
        return _sorted_unique(value)

    @model_validator(mode="after")
    def _coherent(self):
        times = [t for t in (self.requested_at, self.started_at, self.completed_at) if t is not None]
        if times != sorted(times):
            raise ValueError("timestamps must be non-decreasing")
        if self.started_at is None and self.completed_at is not None and self.status != "SKIPPED_OVERLAP":
            raise ValueError("completed_at requires started_at")
        if self.duration_ms is not None:
            if self.started_at is None or self.completed_at is None:
                raise ValueError("duration_ms requires started and completed timestamps")
            expected = int((self.completed_at - self.started_at).total_seconds() * 1000)
            if self.duration_ms != expected:
                raise ValueError("duration_ms inconsistent with timestamps")
        if self.evaluation_count > self.observation_count:
            raise ValueError("evaluation_count exceeds observation_count")
        if self.anomaly_count > self.evaluation_count:
            raise ValueError("anomaly_count exceeds evaluation_count")
        if self.eligible_notification_count > self.anomaly_count:
            raise ValueError("eligible_notification_count exceeds anomaly_count")
        if self.status in FailureRunStatus and not self.error_code:
            raise ValueError("failure/timeout/cancel status requires an error_code")
        if self.status == "SUCCESS" and self.error_code is not None:
            raise ValueError("SUCCESS must not carry an error_code")
        if self.status == "REQUESTED" and self.started_at is not None:
            raise ValueError("REQUESTED must not have started")
        if self.status == "RUNNING" and self.completed_at is not None:
            raise ValueError("RUNNING must not be completed")
        if self.status in TerminalRunStatus and self.status != "SKIPPED_OVERLAP":
            if self.started_at is None or self.completed_at is None:
                raise ValueError("terminal status requires started_at and completed_at")
        if self.status == "SKIPPED_OVERLAP":
            if self.started_at is not None:
                raise ValueError("SKIPPED_OVERLAP must not have started")
            if self.completed_at is None:
                raise ValueError("SKIPPED_OVERLAP requires completed_at")
        return self


class OverlapResult(Contract):
    """Pure non-overlap decision output.  No lock or task is implemented."""

    decision: OverlapDecision
    reason_code: Token
    request_id: Token
    trigger_type: TriggerType
    active_run_id: Token | None = None
    replay_run_id: Token | None = None


def decide_overlap(
    *,
    scheduler_state: SchedulerState,
    trigger_type: TriggerType,
    request_id: str,
    active_run_id: str | None = None,
    replay_of_run_id: str | None = None,
) -> OverlapResult:
    """Deterministic overlap decision; performs no locking and starts no work.

    Cross-process safety is NOT provided by this decision.  It only models
    process-local overlap intent.
    """

    def result(decision: OverlapDecision, reason: str) -> OverlapResult:
        return OverlapResult(
            decision=decision, reason_code=reason, request_id=request_id,
            trigger_type=trigger_type, active_run_id=active_run_id,
            replay_run_id=replay_of_run_id,
        )

    if scheduler_state == "DISABLED":
        return result("DISABLED", SCHEDULER_DISABLED)
    if scheduler_state == "STOPPED":
        return result("DISABLED", SCHEDULER_STOPPED)
    if scheduler_state == "STOPPING":
        return result("REJECT_OVERLAP", SCHEDULER_STOPPING)
    if scheduler_state == "FAILED":
        return result("DISABLED", SCHEDULER_FAILED)

    if replay_of_run_id is not None and active_run_id is not None and replay_of_run_id != active_run_id:
        return result("INVALID", INVALID_REPLAY_REFERENCE)

    if active_run_id is not None:
        if request_id == active_run_id or replay_of_run_id == active_run_id:
            return result("REPLAY_EXISTING", IDEMPOTENT_REPLAY)
        return result("REJECT_OVERLAP", ACTIVE_RUN_IN_PROGRESS)

    if replay_of_run_id is not None:
        return result("REPLAY_EXISTING", IDEMPOTENT_REPLAY)
    return result("ACCEPT", ACCEPTED)
