"""MM-4H immutable runtime event boundary contracts."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from .loss_persistence_models import PersistedLossState
from .loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    SaveTrigger,
)
from .loss_runtime_store_models import LossLimitRuntimeUpdate


class LossRuntimeEventType(str, Enum):
    STARTUP = "STARTUP"
    TRADE_OPEN = "TRADE_OPEN"
    TRADE_CLOSE = "TRADE_CLOSE"
    POSITION_UPDATE = "POSITION_UPDATE"
    BALANCE_UPDATE = "BALANCE_UPDATE"
    EQUITY_UPDATE = "EQUITY_UPDATE"
    CHECKPOINT = "CHECKPOINT"
    SHUTDOWN = "SHUTDOWN"


class LossRuntimeEventAdapterStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    IDEMPOTENT = "IDEMPOTENT"
    FAILED = "FAILED"


class LossRuntimeEventFailureCode(str, Enum):
    LOSS_RUNTIME_EVENT_INVALID = "LOSS_RUNTIME_EVENT_INVALID"
    LOSS_RUNTIME_EVENT_CONTEXT_INVALID = "LOSS_RUNTIME_EVENT_CONTEXT_INVALID"
    LOSS_RUNTIME_EVENT_STALE = "LOSS_RUNTIME_EVENT_STALE"
    LOSS_RUNTIME_EVENT_SEQUENCE_GAP = "LOSS_RUNTIME_EVENT_SEQUENCE_GAP"
    LOSS_RUNTIME_EVENT_CONFLICT = "LOSS_RUNTIME_EVENT_CONFLICT"
    LOSS_RUNTIME_EVENT_TIMESTAMP_INVALID = "LOSS_RUNTIME_EVENT_TIMESTAMP_INVALID"
    LOSS_RUNTIME_EVENT_INTERNAL_FAILURE = "LOSS_RUNTIME_EVENT_INTERNAL_FAILURE"


def _datetime(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _decimal(name, value, nonnegative=False, maximum=None):
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} exceeds maximum")
    return value


def _text(name, value, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} required")
    return value.strip()


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class LossRuntimeEvent:
    event_id: str
    sequence: int
    occurred_at: datetime
    event_type: LossRuntimeEventType
    equity: Decimal
    balance: Decimal
    available_balance: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_pnl: Decimal
    weekly_pnl: Decimal
    monthly_pnl: Decimal
    peak_equity: Decimal
    drawdown: Decimal
    open_exposure: Decimal
    position_count: int
    trade_count: int
    source: str
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    account_id: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "event_id", _text("event_id", self.event_id))
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        object.__setattr__(self, "occurred_at", _datetime(self.occurred_at))
        object.__setattr__(
            self, "event_type", LossRuntimeEventType(self.event_type)
        )
        for name in ("equity", "balance", "available_balance", "peak_equity"):
            _decimal(name, getattr(self, name), nonnegative=True)
        for name in (
            "realized_pnl",
            "unrealized_pnl",
            "daily_pnl",
            "weekly_pnl",
            "monthly_pnl",
        ):
            _decimal(name, getattr(self, name))
        _decimal("drawdown", self.drawdown, nonnegative=True, maximum=Decimal("100"))
        _decimal("open_exposure", self.open_exposure, nonnegative=True)
        if self.peak_equity < self.equity:
            raise ValueError("peak equity must not be below equity")
        if self.available_balance > self.balance:
            raise ValueError("available balance must not exceed balance")
        for name in ("position_count", "trade_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        object.__setattr__(self, "source", _text("source", self.source))
        for name in ("symbol", "exchange", "account_id"):
            object.__setattr__(
                self, name, _text(name, getattr(self, name), optional=True)
            )

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossRuntimeEventSnapshotProjection:
    sequence: int
    occurred_at: datetime
    event_type: LossRuntimeEventType
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_pnl: Decimal
    weekly_pnl: Decimal
    monthly_pnl: Decimal
    peak_equity: Decimal
    drawdown: Decimal
    open_exposure: Decimal
    position_count: int
    trade_count: int
    source: str

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossRuntimeUpdateBuildContext:
    event_id: str
    next_state: PersistedLossState
    governance_projection: GovernanceProjection
    recovery_requirement: LossLimitRecoveryRequirement
    save_triggers: Tuple[SaveTrigger, ...]
    transition_reason: str

    def __post_init__(self):
        object.__setattr__(self, "event_id", _text("event_id", self.event_id))
        if not isinstance(self.next_state, PersistedLossState):
            raise TypeError("next state required")
        object.__setattr__(
            self,
            "governance_projection",
            GovernanceProjection(self.governance_projection),
        )
        if not isinstance(self.recovery_requirement, LossLimitRecoveryRequirement):
            raise TypeError("recovery requirement required")
        triggers = tuple(SaveTrigger(item) for item in self.save_triggers)
        if len(triggers) != len(set(triggers)):
            raise ValueError("duplicate save trigger")
        object.__setattr__(self, "save_triggers", triggers)
        object.__setattr__(
            self,
            "transition_reason",
            _text("transition_reason", self.transition_reason),
        )

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossRuntimeEventFailure:
    code: LossRuntimeEventFailureCode
    safe_message: str

    def __post_init__(self):
        object.__setattr__(self, "code", LossRuntimeEventFailureCode(self.code))
        if not isinstance(self.safe_message, str) or not self.safe_message:
            raise ValueError("safe message required")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class LossRuntimeEventAdapterResult:
    status: LossRuntimeEventAdapterStatus
    update_request: Optional[LossLimitRuntimeUpdate]
    snapshot_projection: Optional[LossRuntimeEventSnapshotProjection]
    event_accepted: bool
    failure: Optional[LossRuntimeEventFailure]

    def __post_init__(self):
        object.__setattr__(self, "status", LossRuntimeEventAdapterStatus(self.status))
        if self.update_request is not None and not isinstance(
            self.update_request, LossLimitRuntimeUpdate
        ):
            raise TypeError("update request invalid")
        if self.snapshot_projection is not None and not isinstance(
            self.snapshot_projection, LossRuntimeEventSnapshotProjection
        ):
            raise TypeError("snapshot projection invalid")
        if type(self.event_accepted) is not bool:
            raise TypeError("event_accepted must be bool")
        if self.status is LossRuntimeEventAdapterStatus.FAILED:
            if self.failure is None or self.event_accepted:
                raise ValueError("failed result invalid")
        elif self.failure is not None or not self.event_accepted:
            raise ValueError("successful result invalid")

    def to_dict(self):
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}
