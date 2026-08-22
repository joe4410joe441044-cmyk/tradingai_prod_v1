"""MM-4I immutable bot-runtime metrics boundary contracts."""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple, Union


class LossRuntimeDataQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    INCONSISTENT = "INCONSISTENT"


class LossRuntimeMetricsReadStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    INCONSISTENT = "INCONSISTENT"
    FAILED = "FAILED"


def _datetime(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(name, value, *, optional=False, nonnegative=False, maximum=None):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} exceeds maximum")
    return value


def _count(name, value, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _text(name, value, *, optional=False):
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
    return value


@dataclass(frozen=True)
class LossRuntimeMetrics:
    captured_at: datetime
    source_revision: Union[str, int]
    equity: Optional[Decimal]
    balance: Optional[Decimal]
    available_balance: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    unrealized_pnl: Optional[Decimal]
    daily_pnl: Optional[Decimal]
    weekly_pnl: Optional[Decimal]
    monthly_pnl: Optional[Decimal]
    peak_equity: Optional[Decimal]
    drawdown: Optional[Decimal]
    open_exposure: Optional[Decimal]
    position_count: Optional[int]
    trade_count: Optional[int]
    source_state: str
    pending_order_count: Optional[int] = None
    margin_used: Optional[Decimal] = None
    cash_flow_state: Optional[str] = None
    trade_count_daily: Optional[int] = None
    trade_count_weekly: Optional[int] = None
    trade_count_monthly: Optional[int] = None
    runtime_instance_id: Optional[str] = None
    session_id: Optional[int] = None
    metrics_revision: Optional[int] = None
    data_quality: LossRuntimeDataQuality = LossRuntimeDataQuality.COMPLETE
    position_side: Optional[str] = None
    current_risk_amount: Optional[Decimal] = None
    reserved_risk_amount: Optional[Decimal] = None
    session_trade_count: Optional[int] = None
    trade_count_authority_scope: Optional[str] = None
    trade_count_authority_session_id: Optional[int] = None

    def __post_init__(self):
        object.__setattr__(
            self, "captured_at", _datetime("captured_at", self.captured_at)
        )
        revision = self.source_revision
        if isinstance(revision, bool) or not isinstance(revision, (str, int)):
            raise TypeError("source_revision must be str or int")
        if isinstance(revision, int):
            if revision < 0:
                raise ValueError("source_revision must be nonnegative")
        elif not revision.strip():
            raise ValueError("source_revision required")
        object.__setattr__(
            self, "source_revision", revision.strip() if isinstance(revision, str) else revision
        )
        for name in (
            "equity",
            "balance",
            "available_balance",
            "peak_equity",
            "open_exposure",
            "margin_used",
            "current_risk_amount",
            "reserved_risk_amount",
        ):
            _decimal(name, getattr(self, name), optional=True, nonnegative=True)
        for name in (
            "realized_pnl",
            "unrealized_pnl",
            "daily_pnl",
            "weekly_pnl",
            "monthly_pnl",
        ):
            _decimal(name, getattr(self, name), optional=True)
        _decimal(
            "drawdown",
            self.drawdown,
            optional=True,
            nonnegative=True,
            maximum=Decimal("100"),
        )
        for name in (
            "position_count",
            "trade_count",
            "pending_order_count",
            "trade_count_daily",
            "trade_count_weekly",
            "trade_count_monthly",
            "session_id",
            "metrics_revision",
            "session_trade_count",
            "trade_count_authority_session_id",
        ):
            _count(name, getattr(self, name), optional=True)
        object.__setattr__(
            self,
            "runtime_instance_id",
            _text(
                "runtime_instance_id",
                self.runtime_instance_id,
                optional=True,
            ),
        )
        object.__setattr__(
            self, "source_state", _text("source_state", self.source_state)
        )
        if self.position_side not in (None, "LONG", "SHORT", "OPEN"):
            raise ValueError("position_side invalid")
        object.__setattr__(
            self,
            "cash_flow_state",
            _text("cash_flow_state", self.cash_flow_state, optional=True),
        )
        object.__setattr__(
            self, "data_quality", LossRuntimeDataQuality(self.data_quality)
        )
        if self.trade_count_authority_scope not in (None, "RUNTIME_SESSION"):
            raise ValueError("trade_count_authority_scope invalid")
        session_authoritative = (
            self.trade_count_authority_scope == "RUNTIME_SESSION"
        )
        if session_authoritative != (
            self.session_trade_count is not None
            and self.trade_count_authority_session_id is not None
        ):
            raise ValueError("session trade count authority incomplete")

    def to_dict(self):
        return {
            field.name: _serialize(getattr(self, field.name))
            for field in fields(self)
        }


@dataclass(frozen=True)
class LossRuntimeMetricsReadRequest:
    source: str
    requested_at: datetime
    maximum_age: timedelta

    def __post_init__(self):
        object.__setattr__(self, "source", _text("source", self.source))
        object.__setattr__(
            self, "requested_at", _datetime("requested_at", self.requested_at)
        )
        if not isinstance(self.maximum_age, timedelta) or self.maximum_age.total_seconds() <= 0:
            raise ValueError("maximum_age must be a positive timedelta")


@dataclass(frozen=True)
class LossRuntimeMetricsReadResult:
    status: LossRuntimeMetricsReadStatus
    metrics: Optional[LossRuntimeMetrics]
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self, "status", LossRuntimeMetricsReadStatus(self.status)
        )
        if self.metrics is not None and not isinstance(
            self.metrics, LossRuntimeMetrics
        ):
            raise TypeError("metrics invalid")
        reasons = tuple(_text("safe_reason", item) for item in self.safe_reasons)
        object.__setattr__(self, "safe_reasons", reasons)
        available = self.status is LossRuntimeMetricsReadStatus.AVAILABLE
        if available and (
            self.metrics is None
            or self.metrics.data_quality is not LossRuntimeDataQuality.COMPLETE
        ):
            raise ValueError("available result requires complete metrics")
        expected_quality = {
            LossRuntimeMetricsReadStatus.PARTIAL: LossRuntimeDataQuality.PARTIAL,
            LossRuntimeMetricsReadStatus.STALE: LossRuntimeDataQuality.STALE,
            LossRuntimeMetricsReadStatus.INCONSISTENT: LossRuntimeDataQuality.INCONSISTENT,
        }.get(self.status)
        if expected_quality is not None and self.metrics is not None and (
            self.metrics.data_quality is not expected_quality
        ):
            raise ValueError("metrics result quality mismatch")
        if self.status in (
            LossRuntimeMetricsReadStatus.PARTIAL,
            LossRuntimeMetricsReadStatus.STALE,
        ) and self.metrics is None:
            raise ValueError("metrics result requires metrics")
        if self.status in (
            LossRuntimeMetricsReadStatus.UNAVAILABLE,
            LossRuntimeMetricsReadStatus.FAILED,
        ) and self.metrics is not None:
            raise ValueError("unavailable result cannot expose metrics")

    def to_dict(self):
        return {
            "status": self.status.value,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "safe_reasons": list(self.safe_reasons),
        }
