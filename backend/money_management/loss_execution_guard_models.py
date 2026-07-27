"""MM-4K immutable execution entry guard contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple

from .loss_governance_projection_models import LossGovernancePublicSnapshot


class LossExecutionOperation(str, Enum):
    NEW_BUY = "NEW_BUY"
    NEW_SELL = "NEW_SELL"
    POSITION_CLOSE = "POSITION_CLOSE"
    REDUCE_ONLY = "REDUCE_ONLY"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    FLATTEN = "FLATTEN"
    EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"
    CANCEL = "CANCEL"

    @property
    def is_new_entry(self):
        return self in (LossExecutionOperation.NEW_BUY, LossExecutionOperation.NEW_SELL)


class LossExecutionEntryDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    UNKNOWN = "UNKNOWN"


class LossExecutionGuardReason(str, Enum):
    ENTRY_ALLOWED = "ENTRY_ALLOWED"
    OPERATION_NOT_GUARDED = "OPERATION_NOT_GUARDED"
    PROJECTION_MISSING = "PROJECTION_MISSING"
    REGISTRATION_UNAVAILABLE = "REGISTRATION_UNAVAILABLE"
    LIFECYCLE_NOT_RUNNING = "LIFECYCLE_NOT_RUNNING"
    PROJECTION_INVALID = "PROJECTION_INVALID"
    PROJECTION_REVISION_MISMATCH = "PROJECTION_REVISION_MISMATCH"
    PROJECTION_TIMESTAMP_INVALID = "PROJECTION_TIMESTAMP_INVALID"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


class LossGovernanceProjectionReadStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REGISTRATION_UNAVAILABLE = "REGISTRATION_UNAVAILABLE"
    LIFECYCLE_NOT_RUNNING = "LIFECYCLE_NOT_RUNNING"
    PROJECTION_MISSING = "PROJECTION_MISSING"
    PROJECTION_INVALID = "PROJECTION_INVALID"


def _datetime(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LossExecutionGuardRequest:
    operation: LossExecutionOperation
    requested_at: datetime
    expected_revision: Optional[int] = None
    expected_sequence: Optional[int] = None
    maximum_projection_age: timedelta = timedelta(seconds=90)

    def __post_init__(self):
        object.__setattr__(
            self, "operation", LossExecutionOperation(self.operation)
        )
        object.__setattr__(
            self, "requested_at", _datetime("requested_at", self.requested_at)
        )
        for name in ("expected_revision", "expected_sequence"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if (self.expected_revision is None) != (self.expected_sequence is None):
            raise ValueError("expected revision and sequence must be paired")
        if (
            not isinstance(self.maximum_projection_age, timedelta)
            or self.maximum_projection_age.total_seconds() <= 0
        ):
            raise ValueError("maximum projection age must be positive")


@dataclass(frozen=True)
class LossGovernanceProjectionReadResult:
    status: LossGovernanceProjectionReadStatus
    public_snapshot: Optional[LossGovernancePublicSnapshot]
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self, "status", LossGovernanceProjectionReadStatus(self.status)
        )
        if self.public_snapshot is not None and not isinstance(
            self.public_snapshot, LossGovernancePublicSnapshot
        ):
            raise TypeError("public projection snapshot invalid")
        if (
            self.status is LossGovernanceProjectionReadStatus.AVAILABLE
        ) != (self.public_snapshot is not None):
            raise ValueError("projection read result mismatch")
        object.__setattr__(
            self, "safe_reasons", tuple(str(item) for item in self.safe_reasons)
        )


@dataclass(frozen=True)
class LossExecutionGuardResult:
    operation: LossExecutionOperation
    decision: LossExecutionEntryDecision
    allowed: bool
    reason: str
    generated_at: datetime
    revision: Optional[int]
    sequence: Optional[int]

    def __post_init__(self):
        object.__setattr__(
            self, "operation", LossExecutionOperation(self.operation)
        )
        object.__setattr__(
            self, "decision", LossExecutionEntryDecision(self.decision)
        )
        if type(self.allowed) is not bool:
            raise TypeError("allowed must be bool")
        if self.allowed != (
            self.decision is LossExecutionEntryDecision.ALLOW
        ):
            raise ValueError("execution decision mismatch")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("guard reason required")
        object.__setattr__(self, "reason", self.reason.strip())
        object.__setattr__(
            self, "generated_at", _datetime("generated_at", self.generated_at)
        )
        for name in ("revision", "sequence"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if (self.revision is None) != (self.sequence is None):
            raise ValueError("revision and sequence availability mismatch")

    def to_dict(self):
        return {
            "operation": self.operation.value,
            "decision": self.decision.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "generatedAt": self.generated_at.isoformat().replace("+00:00", "Z"),
            "revision": self.revision,
            "sequence": self.sequence,
        }
