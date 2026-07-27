"""MM-4E immutable runtime coordination contracts."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

from .loss_runtime_checkpoint_models import CheckpointStatus
from .loss_runtime_integration_models import SaveTrigger
from .loss_runtime_store_models import LossLimitRuntimeSnapshot


class RuntimeCoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    IDEMPOTENT = "IDEMPOTENT"
    PARTIAL = "PARTIAL"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    DURABILITY_PENDING = "DURABILITY_PENDING"


class RuntimeOperationType(str, Enum):
    STARTUP = "STARTUP"
    UPDATE = "UPDATE"
    STOP = "STOP"
    MANUAL_CHECKPOINT = "MANUAL_CHECKPOINT"


class RuntimeCoordinationFailureCode(str, Enum):
    LOSS_RUNTIME_COORDINATION_REQUEST_INVALID = "LOSS_RUNTIME_COORDINATION_REQUEST_INVALID"
    LOSS_RUNTIME_COORDINATION_STARTUP_FAILED = "LOSS_RUNTIME_COORDINATION_STARTUP_FAILED"
    LOSS_RUNTIME_COORDINATION_UPDATE_FAILED = "LOSS_RUNTIME_COORDINATION_UPDATE_FAILED"
    LOSS_RUNTIME_COORDINATION_STOP_FAILED = "LOSS_RUNTIME_COORDINATION_STOP_FAILED"
    LOSS_RUNTIME_COORDINATION_CHECKPOINT_POLICY_INVALID = (
        "LOSS_RUNTIME_COORDINATION_CHECKPOINT_POLICY_INVALID"
    )
    LOSS_RUNTIME_COORDINATION_CHECKPOINT_FAILED = (
        "LOSS_RUNTIME_COORDINATION_CHECKPOINT_FAILED"
    )
    LOSS_RUNTIME_COORDINATION_RESULT_INVALID = (
        "LOSS_RUNTIME_COORDINATION_RESULT_INVALID"
    )
    LOSS_RUNTIME_COORDINATION_INTERNAL_FAILURE = (
        "LOSS_RUNTIME_COORDINATION_INTERNAL_FAILURE"
    )


def _datetime(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class LossLimitRuntimeStopRequest:
    expected_revision: int
    expected_sequence: int
    occurred_at: datetime
    requested_at: datetime

    def __post_init__(self):
        if (
            type(self.expected_revision) is not int
            or self.expected_revision < 1
            or type(self.expected_sequence) is not int
            or self.expected_sequence < 1
        ):
            raise ValueError("revision and sequence must be positive integers")
        object.__setattr__(self, "occurred_at", _datetime(self.occurred_at))
        object.__setattr__(self, "requested_at", _datetime(self.requested_at))

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitCheckpointPolicyDecision:
    required: bool
    trigger: Optional[SaveTrigger]
    mandatory: bool
    allowed: bool
    failure: Optional[str] = None

    def __post_init__(self):
        for name in ("required", "mandatory", "allowed"):
            if type(getattr(self, name)) is not bool:
                raise TypeError("boolean required")
        if self.trigger is not None:
            object.__setattr__(self, "trigger", SaveTrigger(self.trigger))
        if self.required and (not self.allowed or self.trigger is None):
            raise ValueError("required checkpoint must be allowed and have a trigger")
        if self.failure is not None and (
            not isinstance(self.failure, str) or not self.failure
        ):
            raise ValueError("invalid policy failure")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitRuntimeCoordinationFailure:
    code: RuntimeCoordinationFailureCode
    safe_message: str

    def __post_init__(self):
        object.__setattr__(self, "code", RuntimeCoordinationFailureCode(self.code))
        if not isinstance(self.safe_message, str) or not self.safe_message:
            raise ValueError("safe message required")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitRuntimeCoordinationResult:
    status: RuntimeCoordinationStatus
    operation_type: RuntimeOperationType
    runtime_result_status: Optional[str]
    checkpoint_result_status: Optional[CheckpointStatus]
    snapshot: Optional[LossLimitRuntimeSnapshot]
    runtime_succeeded: bool
    checkpoint_required: bool
    checkpoint_attempted: bool
    checkpoint_succeeded: bool
    durability_pending: bool
    recovery_required: bool
    new_entry_allowed: bool
    failure: Optional[LossLimitRuntimeCoordinationFailure]
    save_triggers: Tuple[SaveTrigger, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "status", RuntimeCoordinationStatus(self.status))
        object.__setattr__(
            self, "operation_type", RuntimeOperationType(self.operation_type)
        )
        if self.checkpoint_result_status is not None:
            object.__setattr__(
                self,
                "checkpoint_result_status",
                CheckpointStatus(self.checkpoint_result_status),
            )
        if self.snapshot is not None and not isinstance(
            self.snapshot, LossLimitRuntimeSnapshot
        ):
            raise TypeError("snapshot invalid")
        object.__setattr__(
            self, "save_triggers", tuple(SaveTrigger(item) for item in self.save_triggers)
        )
        for name in (
            "runtime_succeeded",
            "checkpoint_required",
            "checkpoint_attempted",
            "checkpoint_succeeded",
            "durability_pending",
            "recovery_required",
            "new_entry_allowed",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError("boolean required")
        failure_statuses = (
            RuntimeCoordinationStatus.FAILED,
            RuntimeCoordinationStatus.PARTIAL,
            RuntimeCoordinationStatus.DURABILITY_PENDING,
        )
        if self.status in failure_statuses and self.failure is None:
            raise ValueError("failed or partial coordination requires failure")
        if self.status not in failure_statuses and self.failure is not None:
            raise ValueError("successful coordination cannot contain failure")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}
