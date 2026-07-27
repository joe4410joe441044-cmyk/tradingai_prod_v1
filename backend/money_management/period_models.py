"""Strict immutable contracts for MM-2A period PnL aggregation."""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import _dec, _dt, _serialize

PERIOD_SCHEMA_VERSION = "money-management-period/v1"
PERIOD_TIMEZONE = "UTC"
SETTLEMENT_CURRENCY = "USDT"
MAX_EVENT_ID_LENGTH = 128
MAX_PROCESSED_EVENT_IDS = 10000


class PeriodType(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class PnlEventType(str, Enum):
    REALIZED_PNL = "REALIZED_PNL"


class PnlEventSource(str, Enum):
    EXECUTION_NORMALIZED = "EXECUTION_NORMALIZED"


class EquitySource(str, Enum):
    NORMALIZED_EQUITY = "NORMALIZED_EQUITY"


def _exact_enum(enum_type, value):
    if not isinstance(value, enum_type):
        raise TypeError(f"{enum_type.__name__} required")
    return value


def validate_timezone_name(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("timezone required")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid IANA timezone") from exc
    if value != PERIOD_TIMEZONE:
        raise ValueError("only UTC is supported by period contract v1")
    return value


def _identifier(name: str, value: Optional[str], required: bool = False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_EVENT_ID_LENGTH:
        raise ValueError(f"{name} must be a bounded non-empty string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _currency(value: str) -> str:
    if value != SETTLEMENT_CURRENCY:
        raise ValueError("unsupported settlement currency")
    return value


def _schema(value: str) -> str:
    if value != PERIOD_SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    return value


@dataclass(frozen=True)
class MoneyManagementPnlEvent:
    schema_version: str
    event_id: str
    occurred_at: datetime
    recorded_at: datetime
    event_type: PnlEventType
    symbol: str
    gross_realized_pnl: Decimal
    fees: Decimal
    funding: Decimal
    currency: str
    source: PnlEventSource
    sequence: int
    position_id: Optional[str] = None
    order_id: Optional[str] = None
    trade_id: Optional[str] = None

    def __post_init__(self):
        _schema(self.schema_version)
        _identifier("event_id", self.event_id, required=True)
        _identifier("symbol", self.symbol, required=True)
        for name in ("position_id", "order_id", "trade_id"):
            _identifier(name, getattr(self, name))
        object.__setattr__(self, "occurred_at", _dt("occurred_at", self.occurred_at))
        object.__setattr__(self, "recorded_at", _dt("recorded_at", self.recorded_at))
        object.__setattr__(
            self, "event_type", _exact_enum(PnlEventType, self.event_type)
        )
        object.__setattr__(self, "source", _exact_enum(PnlEventSource, self.source))
        _dec("gross_realized_pnl", self.gross_realized_pnl)
        _dec("fees", self.fees, nonnegative=True)
        _dec("funding", self.funding)
        _currency(self.currency)
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be strict integer")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")

    @property
    def net_realized_pnl(self) -> Decimal:
        return self.gross_realized_pnl - self.fees + self.funding

    def to_dict(self):
        return _serialize(self)


@dataclass(frozen=True)
class MoneyManagementPeriod:
    schema_version: str
    period_type: PeriodType
    period_key: str
    timezone_name: str
    start_at: datetime
    end_at: datetime

    def __post_init__(self):
        _schema(self.schema_version)
        object.__setattr__(
            self, "period_type", _exact_enum(PeriodType, self.period_type)
        )
        _identifier("period_key", self.period_key, required=True)
        validate_timezone_name(self.timezone_name)
        object.__setattr__(self, "start_at", _dt("start_at", self.start_at))
        object.__setattr__(self, "end_at", _dt("end_at", self.end_at))
        if self.start_at >= self.end_at:
            raise ValueError("period start must precede end")
        midnight = self.start_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.period_type is PeriodType.DAILY:
            expected_start = midnight
            expected_end = expected_start + timedelta(days=1)
            expected_key = expected_start.strftime("%Y-%m-%d")
        elif self.period_type is PeriodType.WEEKLY:
            expected_start = midnight - timedelta(days=midnight.weekday())
            expected_end = expected_start + timedelta(days=7)
            iso_year, iso_week, _ = expected_start.isocalendar()
            expected_key = f"{iso_year}-W{iso_week:02d}"
        else:
            expected_start = midnight.replace(day=1)
            expected_end = (
                expected_start.replace(year=expected_start.year + 1, month=1)
                if expected_start.month == 12
                else expected_start.replace(month=expected_start.month + 1)
            )
            expected_key = expected_start.strftime("%Y-%m")
        if (
            self.start_at != expected_start
            or self.end_at != expected_end
            or self.period_key != expected_key
        ):
            raise ValueError("period key or boundary mismatch")

    def contains(self, occurred_at: datetime) -> bool:
        value = _dt("occurred_at", occurred_at)
        return self.start_at <= value < self.end_at

    def to_dict(self):
        return _serialize(self)


@dataclass(frozen=True)
class MoneyManagementPeriodAggregate:
    schema_version: str
    period: MoneyManagementPeriod
    currency: str
    event_count: int
    gross_realized_pnl: Decimal
    fees: Decimal
    funding: Decimal
    net_realized_pnl: Decimal
    profit_total: Decimal
    loss_total: Decimal
    winning_event_count: int
    losing_event_count: int
    first_event_at: Optional[datetime]
    last_event_at: Optional[datetime]
    last_sequence: Optional[int]
    processed_event_ids: Tuple[str, ...]
    updated_at: Optional[datetime]

    def __post_init__(self):
        _schema(self.schema_version)
        if not isinstance(self.period, MoneyManagementPeriod):
            raise TypeError("period required")
        _currency(self.currency)
        for name in ("event_count", "winning_event_count", "losing_event_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.winning_event_count + self.losing_event_count > self.event_count:
            raise ValueError("win/loss counts exceed event count")
        for name in (
            "gross_realized_pnl",
            "fees",
            "funding",
            "net_realized_pnl",
            "profit_total",
            "loss_total",
        ):
            _dec(
                name,
                getattr(self, name),
                nonnegative=name in {"fees", "profit_total", "loss_total"},
            )
        if self.gross_realized_pnl - self.fees + self.funding != self.net_realized_pnl:
            raise ValueError("aggregate net PnL formula mismatch")
        if self.profit_total - self.loss_total != self.net_realized_pnl:
            raise ValueError("profit/loss totals mismatch")
        if len(self.processed_event_ids) != self.event_count:
            raise ValueError("event identity count mismatch")
        if len(set(self.processed_event_ids)) != len(self.processed_event_ids):
            raise ValueError("duplicate processed event ID")
        if len(self.processed_event_ids) > MAX_PROCESSED_EVENT_IDS:
            raise ValueError("processed event identity limit exceeded")
        for value in self.processed_event_ids:
            _identifier("processed_event_id", value, required=True)
        for name in ("first_event_at", "last_event_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _dt(name, value))
        if self.event_count == 0:
            if any(
                value is not None
                for value in (
                    self.first_event_at,
                    self.last_event_at,
                    self.last_sequence,
                    self.updated_at,
                )
            ):
                raise ValueError("empty aggregate cannot have event metadata")
        else:
            if (
                self.first_event_at is None
                or self.last_event_at is None
                or self.updated_at is None
            ):
                raise ValueError("non-empty aggregate requires event metadata")
            if self.first_event_at > self.last_event_at:
                raise ValueError("event timestamp range invalid")
            if not self.period.contains(
                self.first_event_at
            ) or not self.period.contains(self.last_event_at):
                raise ValueError("event timestamps outside period")
            if isinstance(self.last_sequence, bool) or not isinstance(
                self.last_sequence, int
            ):
                raise TypeError("last_sequence must be strict integer")

    @property
    def net_loss_amount(self) -> Decimal:
        return max(Decimal("0"), -self.net_realized_pnl)

    def to_dict(self):
        return _serialize(self)

    @classmethod
    def empty(cls, period: MoneyManagementPeriod, currency: str = SETTLEMENT_CURRENCY):
        zero = Decimal("0")
        return cls(
            PERIOD_SCHEMA_VERSION,
            period,
            currency,
            0,
            zero,
            zero,
            zero,
            zero,
            zero,
            zero,
            0,
            0,
            None,
            None,
            None,
            (),
            None,
        )


@dataclass(frozen=True)
class MoneyManagementEquitySnapshot:
    schema_version: str
    captured_at: datetime
    currency: str
    starting_equity: Decimal
    current_equity: Decimal
    peak_equity: Decimal
    drawdown_amount: Decimal
    drawdown_percent: Optional[Decimal]
    source: EquitySource

    def __post_init__(self):
        _schema(self.schema_version)
        object.__setattr__(self, "captured_at", _dt("captured_at", self.captured_at))
        _currency(self.currency)
        object.__setattr__(self, "source", _exact_enum(EquitySource, self.source))
        for name in ("starting_equity", "peak_equity", "drawdown_amount"):
            _dec(name, getattr(self, name), nonnegative=True)
        _dec("current_equity", self.current_equity)
        if self.peak_equity < self.current_equity:
            raise ValueError("peak equity cannot be below current equity")
        expected_amount = max(Decimal("0"), self.peak_equity - self.current_equity)
        if self.drawdown_amount != expected_amount:
            raise ValueError("drawdown amount mismatch")
        if self.peak_equity == 0:
            if self.drawdown_percent is not None:
                raise ValueError("zero peak requires unknown drawdown percent")
        else:
            if self.drawdown_percent is None:
                raise ValueError("positive peak requires drawdown percent")
            _dec("drawdown_percent", self.drawdown_percent, nonnegative=True)
            expected_percent = self.drawdown_amount / self.peak_equity * Decimal("100")
            if self.drawdown_percent != expected_percent:
                raise ValueError("drawdown percent mismatch")

    def to_dict(self):
        return _serialize(self)


def from_dict(model_type, payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be dict")
    allowed = {field.name for field in fields(model_type)}
    if set(payload) != allowed:
        raise ValueError("payload fields do not match contract")
    values = dict(payload)
    datetime_fields = {
        "occurred_at",
        "recorded_at",
        "start_at",
        "end_at",
        "first_event_at",
        "last_event_at",
        "updated_at",
        "captured_at",
    }
    decimal_fields = {
        "gross_realized_pnl",
        "fees",
        "funding",
        "net_realized_pnl",
        "profit_total",
        "loss_total",
        "starting_equity",
        "current_equity",
        "peak_equity",
        "drawdown_amount",
        "drawdown_percent",
    }
    enum_fields = {
        "period_type": PeriodType,
        "event_type": PnlEventType,
        "source": (
            PnlEventSource if model_type is MoneyManagementPnlEvent else EquitySource
        ),
    }
    for name in datetime_fields & values.keys():
        if values[name] is not None:
            text = values[name]
            if not isinstance(text, str):
                raise TypeError(f"{name} must be serialized string")
            values[name] = datetime.fromisoformat(text.replace("Z", "+00:00"))
    for name in decimal_fields & values.keys():
        if values[name] is not None:
            if not isinstance(values[name], str):
                raise TypeError(f"{name} must be serialized decimal string")
            values[name] = Decimal(values[name])
    for name, enum_type in enum_fields.items():
        if name in values:
            values[name] = enum_type(values[name])
    if model_type is MoneyManagementPeriodAggregate:
        values["period"] = from_dict(MoneyManagementPeriod, values["period"])
        values["processed_event_ids"] = tuple(values["processed_event_ids"])
    return model_type(**values)
