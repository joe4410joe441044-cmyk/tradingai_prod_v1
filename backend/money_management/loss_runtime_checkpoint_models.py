"""MM-4D immutable runtime checkpoint contracts."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .loss_runtime_integration_models import SaveTrigger


class CheckpointMode(str, Enum):
    STARTUP_INITIAL_STATE = "STARTUP_INITIAL_STATE"
    RUNTIME_TRANSITION = "RUNTIME_TRANSITION"
    MANUAL = "MANUAL"
    SHUTDOWN = "SHUTDOWN"


class CheckpointStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    IDEMPOTENT = "IDEMPOTENT"
    STALE = "STALE"
    CONFLICT = "CONFLICT"


class CheckpointFailureCode(str, Enum):
    LOSS_CHECKPOINT_REQUEST_INVALID = "LOSS_CHECKPOINT_REQUEST_INVALID"
    LOSS_CHECKPOINT_STORE_NOT_INITIALIZED = "LOSS_CHECKPOINT_STORE_NOT_INITIALIZED"
    LOSS_CHECKPOINT_SNAPSHOT_INVALID = "LOSS_CHECKPOINT_SNAPSHOT_INVALID"
    LOSS_CHECKPOINT_REVISION_MISMATCH = "LOSS_CHECKPOINT_REVISION_MISMATCH"
    LOSS_CHECKPOINT_SEQUENCE_MISMATCH = "LOSS_CHECKPOINT_SEQUENCE_MISMATCH"
    LOSS_CHECKPOINT_STALE = "LOSS_CHECKPOINT_STALE"
    LOSS_CHECKPOINT_SEQUENCE_GAP = "LOSS_CHECKPOINT_SEQUENCE_GAP"
    LOSS_CHECKPOINT_CONFLICT = "LOSS_CHECKPOINT_CONFLICT"
    LOSS_CHECKPOINT_TRIGGER_INVALID = "LOSS_CHECKPOINT_TRIGGER_INVALID"
    LOSS_CHECKPOINT_SAVE_FAILED = "LOSS_CHECKPOINT_SAVE_FAILED"
    LOSS_CHECKPOINT_SAVE_RESULT_INVALID = "LOSS_CHECKPOINT_SAVE_RESULT_INVALID"
    LOSS_CHECKPOINT_INTERNAL_FAILURE = "LOSS_CHECKPOINT_INTERNAL_FAILURE"


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
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class LossLimitRuntimeCheckpointRequest:
    trigger: SaveTrigger
    expected_revision: int
    expected_sequence: int
    requested_at: datetime
    checkpoint_mode: CheckpointMode
    expected_snapshot_fingerprint: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "trigger", SaveTrigger(self.trigger))
        object.__setattr__(
            self, "checkpoint_mode", CheckpointMode(self.checkpoint_mode)
        )
        if (
            type(self.expected_revision) is not int
            or self.expected_revision < 1
            or type(self.expected_sequence) is not int
            or self.expected_sequence < 1
        ):
            raise ValueError("revision and sequence must be positive integers")
        object.__setattr__(self, "requested_at", _datetime(self.requested_at))
        if self.expected_snapshot_fingerprint is not None and (
            not isinstance(self.expected_snapshot_fingerprint, str)
            or not self.expected_snapshot_fingerprint
        ):
            raise ValueError("fingerprint must be a non-empty string")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitRuntimeCheckpointFailure:
    code: CheckpointFailureCode
    safe_message: str

    def __post_init__(self):
        object.__setattr__(self, "code", CheckpointFailureCode(self.code))
        if not isinstance(self.safe_message, str) or not self.safe_message:
            raise ValueError("safe message required")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitRuntimeCheckpointResult:
    status: CheckpointStatus
    saved_revision: Optional[int]
    saved_sequence: Optional[int]
    trigger: Optional[SaveTrigger]
    checkpoint_succeeded: bool
    durability_pending: bool
    failure: Optional[LossLimitRuntimeCheckpointFailure]
    persistence_classification: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "status", CheckpointStatus(self.status))
        if self.trigger is not None:
            object.__setattr__(self, "trigger", SaveTrigger(self.trigger))
        for name in ("checkpoint_succeeded", "durability_pending"):
            if type(getattr(self, name)) is not bool:
                raise TypeError("boolean required")
        if self.status is CheckpointStatus.FAILED and self.failure is None:
            raise ValueError("failed result requires failure")
        if self.status is not CheckpointStatus.FAILED and self.failure is not None:
            raise ValueError("non-failed result cannot contain failure")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}
