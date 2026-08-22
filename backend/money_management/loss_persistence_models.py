"""MM-3A immutable persistence contracts for loss-limit state."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple, Any

from .loss_reason_models import LossReasonContract
from .enums import RiskState

PERSISTENCE_SCHEMA_VERSION = "money-management-loss-state/v1"
CONFIG_SCHEMA_VERSION = "money-management-config/v1"

class PeriodCode(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"

class CashFlowType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"

class FreshnessStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    CORRUPT = "CORRUPT"

class MissingStateStatus(str, Enum):
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"
    INCOMPATIBLE_VERSION = "INCOMPATIBLE_VERSION"
    VALID = "VALID"

class LossBaselineType(str, Enum):
    PERIOD_BOUNDARY_BASELINE = "PERIOD_BOUNDARY_BASELINE"
    ACCOUNTING_REBASE_BASELINE = "ACCOUNTING_REBASE_BASELINE"

class AccountingRebaseAuthoritySource(str, Enum):
    PAPER_RUNTIME_EQUITY = "PAPER_RUNTIME_EQUITY"

class AccountingRebaseReason(str, Enum):
    HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE = "HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE"

class AccountingContinuityStatus(str, Enum):
    UNAVAILABLE_REBASED = "UNAVAILABLE_REBASED"

class AccountingRebaseAuthorizationState(str, Enum):
    EXPLICITLY_AUTHORIZED = "EXPLICITLY_AUTHORIZED"

class AccountingRebaseAuditMarker(str, Enum):
    DURABLE_CHECKPOINT_REQUIRED = "DURABLE_CHECKPOINT_REQUIRED"

def _decimal(name: str, value: Decimal, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value

def _time(name: str, value: Optional[datetime], required: bool = True) -> Optional[datetime]:
    if value is None and not required:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)

def _enum(name: str, cls, value):
    if not isinstance(value, cls):
        raise TypeError(f"{name} must be {cls.__name__}")
    return value

def _ser(value: Any):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_ser(x) for x in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value

@dataclass(frozen=True)
class PersistedLossPeriodState:
    period_code: PeriodCode
    period_id: str
    period_start: datetime
    period_end: datetime
    starting_equity: Decimal
    net_realized_pnl: Decimal
    net_loss: Decimal
    loss_percent: Decimal
    cash_flow_amount: Decimal
    last_updated_at: datetime
    baseline_type: LossBaselineType = LossBaselineType.PERIOD_BOUNDARY_BASELINE
    baseline_observed_at: Optional[datetime] = None

    def __post_init__(self):
        _enum("period_code", PeriodCode, self.period_code)
        if not isinstance(self.period_id, str) or not self.period_id:
            raise ValueError("period_id required")
        start, end = _time("period_start", self.period_start), _time("period_end", self.period_end)
        if start >= end:
            raise ValueError("period_start must be before period_end")
        object.__setattr__(self, "period_start", start)
        object.__setattr__(self, "period_end", end)
        object.__setattr__(self, "last_updated_at", _time("last_updated_at", self.last_updated_at))
        object.__setattr__(self, "baseline_type", LossBaselineType(self.baseline_type))
        observed = self.baseline_observed_at
        if observed is None:
            observed = self.period_start
        object.__setattr__(self, "baseline_observed_at", _time("baseline_observed_at", observed))
        if self.baseline_type is LossBaselineType.PERIOD_BOUNDARY_BASELINE and observed != start:
            raise ValueError("period boundary baseline must be observed at period start")
        if self.baseline_type is LossBaselineType.ACCOUNTING_REBASE_BASELINE and not (start <= observed <= end):
            raise ValueError("accounting rebase observation must be within period")
        _decimal("starting_equity", self.starting_equity, positive=True)
        _decimal("net_realized_pnl", self.net_realized_pnl)
        _decimal("net_loss", self.net_loss, nonnegative=True)
        _decimal("loss_percent", self.loss_percent, nonnegative=True)
        _decimal("cash_flow_amount", self.cash_flow_amount)
        if self.net_loss != max(Decimal("0"), -self.net_realized_pnl):
            raise ValueError("net_loss does not match net_realized_pnl")
        expected = self.net_loss / self.starting_equity * Decimal("100")
        if self.loss_percent != expected:
            raise ValueError("loss_percent does not match net_loss and starting_equity")
        if self.last_updated_at > self.period_end:
            raise ValueError("last_updated_at must not exceed period_end")

    def to_dict(self):
        return {f.name: _ser(getattr(self, f.name)) for f in fields(self)}

@dataclass(frozen=True)
class PersistedAccountingRebaseRecord:
    rebase_id: str
    observed_at: datetime
    authoritative_equity: Decimal
    authority_source: AccountingRebaseAuthoritySource
    account_scope: str
    runtime_instance_id: str
    affected_periods: Tuple[PeriodCode, ...]
    previous_period_ids: Tuple[str, ...]
    new_period_ids: Tuple[str, ...]
    observed_period_pnl: Tuple[Decimal, ...]
    reason: AccountingRebaseReason
    continuity_status: AccountingContinuityStatus
    authorization_state: AccountingRebaseAuthorizationState
    audit_marker: AccountingRebaseAuditMarker

    def __post_init__(self):
        for name in ("rebase_id", "account_scope", "runtime_instance_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} required")
        object.__setattr__(self, "observed_at", _time("observed_at", self.observed_at))
        _decimal("authoritative_equity", self.authoritative_equity, positive=True)
        object.__setattr__(self, "authority_source", AccountingRebaseAuthoritySource(self.authority_source))
        periods = tuple(PeriodCode(item) for item in self.affected_periods)
        if not periods or len(periods) != len(set(periods)):
            raise ValueError("affected periods invalid")
        if len(periods) != len(self.previous_period_ids) or len(periods) != len(self.new_period_ids):
            raise ValueError("period audit mapping incomplete")
        if len(periods) != len(self.observed_period_pnl):
            raise ValueError("period PnL baseline mapping incomplete")
        for value in self.observed_period_pnl:
            _decimal("observed_period_pnl", value)
        object.__setattr__(self, "affected_periods", periods)
        object.__setattr__(self, "previous_period_ids", tuple(self.previous_period_ids))
        object.__setattr__(self, "new_period_ids", tuple(self.new_period_ids))
        object.__setattr__(self, "observed_period_pnl", tuple(self.observed_period_pnl))
        object.__setattr__(self, "reason", AccountingRebaseReason(self.reason))
        object.__setattr__(self, "continuity_status", AccountingContinuityStatus(self.continuity_status))
        object.__setattr__(self, "authorization_state", AccountingRebaseAuthorizationState(self.authorization_state))
        object.__setattr__(self, "audit_marker", AccountingRebaseAuditMarker(self.audit_marker))

    def to_dict(self):
        return {f.name: _ser(getattr(self, f.name)) for f in fields(self)}

@dataclass(frozen=True)
class PersistedDrawdownState:
    high_water_mark: Decimal
    current_equity: Decimal
    drawdown_amount: Decimal
    drawdown_percent: Decimal
    last_updated_at: datetime

    def __post_init__(self):
        _decimal("high_water_mark", self.high_water_mark, positive=True)
        _decimal("current_equity", self.current_equity)
        _decimal("drawdown_amount", self.drawdown_amount, nonnegative=True)
        _decimal("drawdown_percent", self.drawdown_percent, nonnegative=True)
        if self.current_equity < 0:
            raise ValueError("negative current_equity is invalid persisted state")
        if self.high_water_mark < self.current_equity:
            raise ValueError("high_water_mark must be >= current_equity")
        if self.drawdown_amount != self.high_water_mark - self.current_equity:
            raise ValueError("drawdown_amount mismatch")
        expected = self.drawdown_amount / self.high_water_mark * Decimal("100")
        if self.drawdown_percent != expected:
            raise ValueError("drawdown_percent mismatch")
        object.__setattr__(self, "last_updated_at", _time("last_updated_at", self.last_updated_at))

    def to_dict(self):
        return {f.name: _ser(getattr(self, f.name)) for f in fields(self)}

@dataclass(frozen=True)
class PersistedCashFlowState:
    has_unresolved_cash_flow: bool
    cash_flow_types: Tuple[CashFlowType, ...]
    net_cash_flow_amount: Decimal
    last_cash_flow_at: Optional[datetime] = None

    def __post_init__(self):
        if type(self.has_unresolved_cash_flow) is not bool:
            raise TypeError("has_unresolved_cash_flow must be bool")
        vals = tuple(sorted((_enum("cash_flow_types", CashFlowType, x) for x in self.cash_flow_types), key=lambda x: x.value))
        if len(vals) != len(set(vals)):
            raise ValueError("cash_flow_types must be unique")
        object.__setattr__(self, "cash_flow_types", vals)
        _decimal("net_cash_flow_amount", self.net_cash_flow_amount)
        object.__setattr__(self, "last_cash_flow_at", _time("last_cash_flow_at", self.last_cash_flow_at, False))
        if self.has_unresolved_cash_flow and not vals:
            raise ValueError("unresolved cash flow requires a type")
        if not self.has_unresolved_cash_flow and vals:
            raise ValueError("resolved cash flow cannot retain types")

    def to_dict(self):
        return {f.name: _ser(getattr(self, f.name)) for f in fields(self)}

@dataclass(frozen=True)
class PersistedLossState:
    schema_version: str
    account_scope: str
    valuation_currency: str
    daily_state: PersistedLossPeriodState
    weekly_state: PersistedLossPeriodState
    monthly_state: PersistedLossPeriodState
    drawdown_state: PersistedDrawdownState
    cash_flow_state: PersistedCashFlowState
    last_decision: LossReasonContract
    captured_at: datetime
    config_schema_version: str = CONFIG_SCHEMA_VERSION
    freshness: FreshnessStatus = FreshnessStatus.VALID
    accounting_rebases: Tuple[PersistedAccountingRebaseRecord, ...] = ()

    def __post_init__(self):
        if self.schema_version != PERSISTENCE_SCHEMA_VERSION:
            raise ValueError("unsupported persistence schema")
        if self.config_schema_version != CONFIG_SCHEMA_VERSION:
            raise ValueError("unsupported config schema")
        if not isinstance(self.account_scope, str) or not self.account_scope.strip():
            raise ValueError("account_scope required")
        if self.valuation_currency != "USDT":
            raise ValueError("unsupported valuation currency")
        for name in ("daily_state", "weekly_state", "monthly_state", "drawdown_state", "cash_flow_state", "last_decision"):
            if not hasattr(getattr(self, name), "to_dict"):
                raise TypeError(f"{name} typed contract required")
        if self.daily_state.period_code is not PeriodCode.DAILY or self.weekly_state.period_code is not PeriodCode.WEEKLY or self.monthly_state.period_code is not PeriodCode.MONTHLY:
            raise ValueError("period code mismatch")
        captured = _time("captured_at", self.captured_at)
        object.__setattr__(self, "captured_at", captured)
        for name in ("daily_state", "weekly_state", "monthly_state"):
            if getattr(self, name).last_updated_at > captured:
                raise ValueError(f"{name}.last_updated_at exceeds captured_at")
        if self.drawdown_state.last_updated_at > captured:
            raise ValueError("drawdown last_updated_at exceeds captured_at")
        if self.cash_flow_state.last_cash_flow_at is not None and self.cash_flow_state.last_cash_flow_at > captured:
            raise ValueError("cash flow timestamp exceeds captured_at")
        if self.last_decision.evaluated_at > captured:
            raise ValueError("last decision timestamp exceeds captured_at")
        _enum("freshness", FreshnessStatus, self.freshness)
        rebases = tuple(self.accounting_rebases)
        if any(not isinstance(item, PersistedAccountingRebaseRecord) for item in rebases):
            raise TypeError("accounting_rebases typed contracts required")
        if len({item.rebase_id for item in rebases}) != len(rebases):
            raise ValueError("duplicate accounting rebase ID")
        if any(item.observed_at > captured for item in rebases):
            raise ValueError("accounting rebase timestamp exceeds captured_at")
        object.__setattr__(self, "accounting_rebases", rebases)

    def to_dict(self):
        return {f.name: _ser(getattr(self, f.name)) for f in fields(self)}

    @property
    def risk_state(self) -> RiskState:
        return self.last_decision.decision_state
