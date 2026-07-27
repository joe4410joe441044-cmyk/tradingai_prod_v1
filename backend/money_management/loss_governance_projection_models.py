"""MM-4J immutable governance projection boundary contracts."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple, Union

from .enums import RiskState
from .loss_reason_models import (
    BlockReason,
    DiagnosticReason,
    HoldReason,
    LossReasonContract,
)
from .loss_runtime_integration_models import GovernanceProjection


class LossEntryPermission(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    UNKNOWN = "UNKNOWN"


class LossGovernanceBoundaryReason(str, Enum):
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    UNKNOWN_STATE = "UNKNOWN_STATE"


LossGovernanceBlockReason = Union[
    BlockReason,
    HoldReason,
    LossGovernanceBoundaryReason,
]


class LossGovernanceProjectionDispatchStatus(str, Enum):
    PROJECTED = "PROJECTED"
    IDEMPOTENT = "IDEMPOTENT"
    FAIL_CLOSED = "FAIL_CLOSED"


def _datetime(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
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
class LossGovernanceProjection:
    entry_permission: LossEntryPermission
    new_entry_allowed: bool
    block_reason: Optional[LossGovernanceBlockReason]
    risk_state: Optional[RiskState]
    loss_state: Optional[GovernanceProjection]
    recovery_required: bool
    diagnostic_reasons: Tuple[DiagnosticReason, ...]
    generated_at: datetime

    def __post_init__(self):
        object.__setattr__(
            self, "entry_permission", LossEntryPermission(self.entry_permission)
        )
        if type(self.new_entry_allowed) is not bool:
            raise TypeError("new_entry_allowed must be bool")
        if self.block_reason is not None and not isinstance(
            self.block_reason,
            (BlockReason, HoldReason, LossGovernanceBoundaryReason),
        ):
            raise TypeError("block_reason invalid")
        if self.risk_state is not None:
            object.__setattr__(self, "risk_state", RiskState(self.risk_state))
        if self.loss_state is not None:
            object.__setattr__(
                self, "loss_state", GovernanceProjection(self.loss_state)
            )
        if type(self.recovery_required) is not bool:
            raise TypeError("recovery_required must be bool")
        diagnostics = tuple(
            DiagnosticReason(item) for item in self.diagnostic_reasons
        )
        if len(diagnostics) != len(set(diagnostics)):
            raise ValueError("duplicate diagnostic reason")
        object.__setattr__(self, "diagnostic_reasons", diagnostics)
        object.__setattr__(
            self, "generated_at", _datetime("generated_at", self.generated_at)
        )

        if self.new_entry_allowed != (
            self.entry_permission is LossEntryPermission.ALLOW
        ):
            raise ValueError("entry permission mismatch")
        if self.entry_permission is LossEntryPermission.ALLOW:
            if (
                self.block_reason is not None
                or self.recovery_required
                or self.loss_state is not GovernanceProjection.CONTINUE
            ):
                raise ValueError("allow projection invalid")
        elif self.block_reason is None:
            raise ValueError("restrictive projection requires block reason")
        if self.entry_permission is LossEntryPermission.RECOVERY_REQUIRED:
            if (
                not self.recovery_required
                or self.block_reason
                is not LossGovernanceBoundaryReason.RECOVERY_REQUIRED
                or self.loss_state is not GovernanceProjection.RECOVERY_REQUIRED
            ):
                raise ValueError("recovery projection invalid")
        elif self.recovery_required:
            raise ValueError("recovery flag requires recovery permission")
        if self.entry_permission is LossEntryPermission.UNKNOWN and (
            self.block_reason is not LossGovernanceBoundaryReason.UNKNOWN_STATE
            or self.risk_state is not None
            or self.loss_state is not None
        ):
            raise ValueError("unknown projection invalid")
        if (
            self.risk_state is RiskState.LOCKED
            and self.entry_permission is LossEntryPermission.ALLOW
        ):
            raise ValueError("locked state cannot allow entries")

    def to_dict(self):
        return {
            "entryPermission": self.entry_permission.value,
            "newEntryAllowed": self.new_entry_allowed,
            "blockReason": _serialize(self.block_reason),
            "riskState": _serialize(self.risk_state),
            "lossState": _serialize(self.loss_state),
            "recoveryRequired": self.recovery_required,
            "diagnosticReasons": _serialize(self.diagnostic_reasons),
            "generatedAt": _serialize(self.generated_at),
        }


@dataclass(frozen=True)
class LossGovernanceProjectionBuildInput:
    decision: Optional[LossReasonContract]
    loss_state: Optional[GovernanceProjection]
    recovery_required: bool
    generated_at: datetime

    def __post_init__(self):
        if self.decision is not None and not isinstance(
            self.decision, LossReasonContract
        ):
            raise TypeError("loss decision invalid")
        if self.loss_state is not None:
            object.__setattr__(
                self, "loss_state", GovernanceProjection(self.loss_state)
            )
        if type(self.recovery_required) is not bool:
            raise TypeError("recovery_required must be bool")
        object.__setattr__(
            self, "generated_at", _datetime("generated_at", self.generated_at)
        )


@dataclass(frozen=True)
class LossGovernancePublicSnapshot:
    projection: LossGovernanceProjection
    revision: Optional[int]
    sequence: Optional[int]
    generated_at: datetime

    def __post_init__(self):
        if not isinstance(self.projection, LossGovernanceProjection):
            raise TypeError("governance projection required")
        for name in ("revision", "sequence"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if (self.revision is None) != (self.sequence is None):
            raise ValueError("revision and sequence availability mismatch")
        object.__setattr__(
            self, "generated_at", _datetime("generated_at", self.generated_at)
        )
        if self.generated_at != self.projection.generated_at:
            raise ValueError("snapshot timestamp mismatch")

    def to_dict(self):
        return {
            "projection": self.projection.to_dict(),
            "revision": self.revision,
            "sequence": self.sequence,
            "generatedAt": _serialize(self.generated_at),
        }


@dataclass(frozen=True)
class LossGovernanceProjectionDispatchResult:
    status: LossGovernanceProjectionDispatchStatus
    public_snapshot: LossGovernancePublicSnapshot
    updated: bool
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self,
            "status",
            LossGovernanceProjectionDispatchStatus(self.status),
        )
        if not isinstance(self.public_snapshot, LossGovernancePublicSnapshot):
            raise TypeError("public snapshot required")
        if type(self.updated) is not bool:
            raise TypeError("updated must be bool")
        object.__setattr__(
            self, "safe_reasons", tuple(str(item) for item in self.safe_reasons)
        )
        if (
            self.status is LossGovernanceProjectionDispatchStatus.IDEMPOTENT
        ) == self.updated:
            raise ValueError("dispatch update status mismatch")

    def to_dict(self):
        return {
            "status": self.status.value,
            "publicSnapshot": self.public_snapshot.to_dict(),
            "updated": self.updated,
            "safeReasons": list(self.safe_reasons),
        }
