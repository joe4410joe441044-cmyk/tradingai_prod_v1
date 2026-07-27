"""MM-4F immutable application composition and lifecycle contracts."""
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from .loss_persistence_models import PeriodCode, PersistedLossState
from .loss_runtime_checkpoint_models import CheckpointStatus
from .loss_runtime_coordination_models import LossLimitRuntimeCoordinationResult
from .loss_runtime_integration_models import RuntimeLifecycle


class CompositionReadinessStatus(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    COMPOSITION_FAILED = "COMPOSITION_FAILED"


class ApplicationLifecycleState(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class LifecycleOperationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    IDEMPOTENT = "IDEMPOTENT"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ApplicationFailureCode(str, Enum):
    LOSS_APPLICATION_CONFIGURATION_INVALID = "LOSS_APPLICATION_CONFIGURATION_INVALID"
    LOSS_APPLICATION_PERSISTENCE_UNAVAILABLE = "LOSS_APPLICATION_PERSISTENCE_UNAVAILABLE"
    LOSS_APPLICATION_METADATA_INVALID = "LOSS_APPLICATION_METADATA_INVALID"
    LOSS_APPLICATION_COMPOSITION_FAILED = "LOSS_APPLICATION_COMPOSITION_FAILED"
    LOSS_APPLICATION_LIFECYCLE_INVALID = "LOSS_APPLICATION_LIFECYCLE_INVALID"
    LOSS_APPLICATION_CHILD_RESULT_INVALID = "LOSS_APPLICATION_CHILD_RESULT_INVALID"
    LOSS_APPLICATION_OPERATION_FAILED = "LOSS_APPLICATION_OPERATION_FAILED"


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
class LossLimitCheckpointMetadata:
    last_persisted_revision: int = 0
    last_persisted_sequence: int = 0
    last_persisted_fingerprint: Optional[str] = field(default=None, repr=False)
    initialized: bool = True

    def __post_init__(self):
        if (
            type(self.last_persisted_revision) is not int
            or self.last_persisted_revision < 0
            or type(self.last_persisted_sequence) is not int
            or self.last_persisted_sequence < 0
        ):
            raise ValueError("invalid checkpoint metadata")
        if type(self.initialized) is not bool or not self.initialized:
            raise ValueError("checkpoint metadata must be initialized")
        empty = self.last_persisted_revision == self.last_persisted_sequence == 0
        populated = (
            self.last_persisted_revision > 0 and self.last_persisted_sequence > 0
        )
        if not (empty or populated):
            raise ValueError("inconsistent checkpoint metadata")
        if empty and self.last_persisted_fingerprint is not None:
            raise ValueError("empty metadata cannot have fingerprint")
        if populated and (
            not isinstance(self.last_persisted_fingerprint, str)
            or len(self.last_persisted_fingerprint) != 64
            or any(
                char not in "0123456789abcdef"
                for char in self.last_persisted_fingerprint
            )
        ):
            raise ValueError("invalid checkpoint fingerprint")

    def to_dict(self):
        # Fingerprints are deliberately not exposed at the application boundary.
        return {
            "last_persisted_revision": self.last_persisted_revision,
            "last_persisted_sequence": self.last_persisted_sequence,
            "initialized": self.initialized,
            "fingerprint_configured": self.last_persisted_fingerprint is not None,
        }


@dataclass(frozen=True)
class LossLimitApplicationConfiguration:
    enabled: bool = False
    persistence_enabled: bool = False
    persistence_path: Optional[Path] = field(default=None, repr=False)
    initial_period_code: Optional[PeriodCode] = None
    initial_state: Optional[PersistedLossState] = field(default=None, repr=False)
    startup_occurred_at: Optional[datetime] = None
    checkpoint_metadata: Optional[LossLimitCheckpointMetadata] = field(
        default=None, repr=False
    )
    instance_id: Optional[str] = None

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.persistence_enabled) is not bool:
            raise TypeError("enabled flags must be bool")
        if self.persistence_path is not None and (
            not isinstance(self.persistence_path, Path)
            or not self.persistence_path.is_absolute()
        ):
            raise ValueError("persistence path must be an absolute Path")
        if self.initial_period_code is not None:
            object.__setattr__(
                self, "initial_period_code", PeriodCode(self.initial_period_code)
            )
        if self.initial_state is not None and not isinstance(
            self.initial_state, PersistedLossState
        ):
            raise TypeError("initial state invalid")
        if self.startup_occurred_at is not None:
            value = self.startup_occurred_at
            if value.tzinfo is None or value.utcoffset() is None:
                raise TypeError("startup timestamp must be timezone-aware")
            object.__setattr__(
                self, "startup_occurred_at", value.astimezone(timezone.utc)
            )
        if self.checkpoint_metadata is not None and not isinstance(
            self.checkpoint_metadata, LossLimitCheckpointMetadata
        ):
            raise TypeError("checkpoint metadata invalid")
        if self.instance_id is not None and (
            not isinstance(self.instance_id, str) or not self.instance_id
        ):
            raise ValueError("instance id invalid")

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "persistence_enabled": self.persistence_enabled,
            "persistence_path_configured": self.persistence_path is not None,
            "initial_period_code": _serialize(self.initial_period_code),
            "initial_state_configured": self.initial_state is not None,
            "startup_occurred_at": _serialize(self.startup_occurred_at),
            "checkpoint_metadata": _serialize(self.checkpoint_metadata),
            "instance_id": self.instance_id,
        }


@dataclass(frozen=True)
class LossLimitApplicationFailure:
    code: ApplicationFailureCode
    safe_message: str

    def __post_init__(self):
        object.__setattr__(self, "code", ApplicationFailureCode(self.code))
        if not isinstance(self.safe_message, str) or not self.safe_message:
            raise ValueError("safe message required")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitCompositionReadiness:
    status: CompositionReadinessStatus
    enabled: bool
    composition_available: bool
    startup_allowed: bool
    runtime_update_allowed: bool
    shutdown_allowed: bool
    recovery_required: bool
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "status", CompositionReadinessStatus(self.status))
        for name in (
            "enabled",
            "composition_available",
            "startup_allowed",
            "runtime_update_allowed",
            "shutdown_allowed",
            "recovery_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError("boolean required")
        object.__setattr__(
            self, "safe_reasons", tuple(str(reason) for reason in self.safe_reasons)
        )
        if self.recovery_required and self.runtime_update_allowed:
            raise ValueError("recovery readiness cannot allow runtime updates")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossLimitApplicationCompositionResult:
    status: CompositionReadinessStatus
    readiness: LossLimitCompositionReadiness
    lifecycle_adapter: Optional[object] = field(repr=False)
    failure: Optional[LossLimitApplicationFailure]

    def __post_init__(self):
        object.__setattr__(self, "status", CompositionReadinessStatus(self.status))
        if not isinstance(self.readiness, LossLimitCompositionReadiness):
            raise TypeError("readiness required")
        success = self.status is CompositionReadinessStatus.READY
        if success != (self.lifecycle_adapter is not None):
            raise ValueError("lifecycle adapter availability mismatch")
        failed = self.status in (
            CompositionReadinessStatus.CONFIGURATION_INVALID,
            CompositionReadinessStatus.PERSISTENCE_UNAVAILABLE,
            CompositionReadinessStatus.COMPOSITION_FAILED,
            CompositionReadinessStatus.RECOVERY_REQUIRED,
        )
        if failed != (self.failure is not None):
            raise ValueError("composition failure mismatch")

    def to_dict(self):
        return {
            "status": self.status.value,
            "readiness": self.readiness.to_dict(),
            "lifecycle_adapter_available": self.lifecycle_adapter is not None,
            "failure": self.failure.to_dict() if self.failure else None,
        }


@dataclass(frozen=True)
class LossLimitLifecycleOperationResult:
    status: LifecycleOperationStatus
    lifecycle_state: ApplicationLifecycleState
    coordination_result: Optional[LossLimitRuntimeCoordinationResult] = field(
        repr=False
    )
    failure: Optional[LossLimitApplicationFailure]

    def __post_init__(self):
        object.__setattr__(self, "status", LifecycleOperationStatus(self.status))
        object.__setattr__(
            self, "lifecycle_state", ApplicationLifecycleState(self.lifecycle_state)
        )
        if self.coordination_result is not None and not isinstance(
            self.coordination_result, LossLimitRuntimeCoordinationResult
        ):
            raise TypeError("coordination result invalid")
        failed = self.status in (
            LifecycleOperationStatus.FAILED,
            LifecycleOperationStatus.REJECTED,
        )
        if failed != (self.failure is not None):
            raise ValueError("lifecycle failure mismatch")

    def to_dict(self):
        coordination = self.coordination_result
        return {
            "status": self.status.value,
            "lifecycle_state": self.lifecycle_state.value,
            "coordination": None
            if coordination is None
            else {
                "status": coordination.status.value,
                "operation_type": coordination.operation_type.value,
                "runtime_succeeded": coordination.runtime_succeeded,
                "checkpoint_attempted": coordination.checkpoint_attempted,
                "checkpoint_succeeded": coordination.checkpoint_succeeded,
                "durability_pending": coordination.durability_pending,
                "recovery_required": coordination.recovery_required,
                "new_entry_allowed": coordination.new_entry_allowed,
                "checkpoint_result_status": _serialize(
                    coordination.checkpoint_result_status
                ),
            },
            "failure": self.failure.to_dict() if self.failure else None,
        }


@dataclass(frozen=True)
class LossLimitApplicationStatus:
    lifecycle_state: ApplicationLifecycleState
    composition_status: CompositionReadinessStatus
    runtime_available: bool
    runtime_state: Optional[RuntimeLifecycle]
    new_entry_allowed: bool
    recovery_required: bool
    durability_pending: bool
    revision: Optional[int]
    sequence: Optional[int]
    last_operation_status: Optional[str]
    last_checkpoint_status: Optional[CheckpointStatus]

    def __post_init__(self):
        object.__setattr__(
            self, "lifecycle_state", ApplicationLifecycleState(self.lifecycle_state)
        )
        object.__setattr__(
            self, "composition_status", CompositionReadinessStatus(self.composition_status)
        )
        if self.runtime_state is not None:
            object.__setattr__(self, "runtime_state", RuntimeLifecycle(self.runtime_state))
        if self.last_checkpoint_status is not None:
            object.__setattr__(
                self, "last_checkpoint_status", CheckpointStatus(self.last_checkpoint_status)
            )
        for name in (
            "runtime_available",
            "new_entry_allowed",
            "recovery_required",
            "durability_pending",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError("boolean required")
        if not self.runtime_available and self.new_entry_allowed:
            raise ValueError("unavailable runtime cannot allow entries")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}
