"""Normalized read-only observation contracts with explicit data quality.

The values here are snapshots of a single endpoint response (or a fully
paginated endpoint traversal).  They deliberately keep account-wide USD values
and coin-level values separate, preserve ``Decimal`` precision, and never turn
missing, unsupported, stale or partial data into zero or an empty success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Tuple

from backend.accounts.models import AccountId
from backend.execution.adapter_contracts import OrderSide
from backend.execution.read_only_adapter_contracts import EndpointProfile


class ReadDataQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    STALE = "STALE"


class ReadEndpoint(str, Enum):
    ACCOUNT_SUMMARY = "ACCOUNT_SUMMARY"
    POSITIONS = "POSITIONS"
    OPEN_ORDERS = "OPEN_ORDERS"


class ReadErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_BINDING = "INVALID_BINDING"
    STALE_BINDING = "STALE_BINDING"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    CLOCK_SKEW = "CLOCK_SKEW"
    VENUE_REJECTED = "VENUE_REJECTED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    PAGINATION_INCOMPLETE = "PAGINATION_INCOMPLETE"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    PARTIAL_DATA = "PARTIAL_DATA"
    STALE_DATA = "STALE_DATA"
    STATE_UNKNOWN = "STATE_UNKNOWN"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"


_SAFE_MESSAGES = {
    ReadErrorCode.INVALID_REQUEST: "read request is invalid",
    ReadErrorCode.INVALID_BINDING: "read binding is invalid",
    ReadErrorCode.STALE_BINDING: "read binding is no longer current",
    ReadErrorCode.UNSUPPORTED_CAPABILITY: "read capability is unsupported",
    ReadErrorCode.CAPABILITY_UNKNOWN: "read capability is unknown",
    ReadErrorCode.TRANSPORT_FAILURE: "read transport failed",
    ReadErrorCode.TIMEOUT: "read request timed out",
    ReadErrorCode.RATE_LIMITED: "read request was rate limited",
    ReadErrorCode.AUTHENTICATION_FAILED: "read authentication failed",
    ReadErrorCode.PERMISSION_DENIED: "read permission denied",
    ReadErrorCode.ENVIRONMENT_MISMATCH: "read environment does not match",
    ReadErrorCode.CLOCK_SKEW: "venue and local clocks disagree",
    ReadErrorCode.VENUE_REJECTED: "venue rejected the read request",
    ReadErrorCode.MALFORMED_RESPONSE: "venue response was malformed",
    ReadErrorCode.PAGINATION_INCOMPLETE: "pagination did not complete",
    ReadErrorCode.DUPLICATE_RECORD: "venue returned duplicate or contradictory records",
    ReadErrorCode.PARTIAL_DATA: "only part of the endpoint data was obtained",
    ReadErrorCode.STALE_DATA: "endpoint data is stale",
    ReadErrorCode.STATE_UNKNOWN: "read state is unknown",
    ReadErrorCode.PURPOSE_MISMATCH: "read purpose does not permit this operation",
}

_RETRYABLE = frozenset(
    {
        ReadErrorCode.TRANSPORT_FAILURE,
        ReadErrorCode.TIMEOUT,
        ReadErrorCode.RATE_LIMITED,
        ReadErrorCode.STATE_UNKNOWN,
    }
)

_OPAQUE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")


def _exact_enum(enum_type, name: str, value: object) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")


def _opaque(name: str, value: object, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded opaque identifier")
    if any(char not in _OPAQUE for char in value):
        raise ValueError(f"{name} must be a bounded opaque identifier")
    return value


def _nonnegative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _decimal_value(name: str, value: object, *, allow_none: bool = True) -> Decimal | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} is required")
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _missing(name: str, values: Tuple[str, ...]) -> Tuple[str, ...]:
    seen = tuple(values)
    if len(set(seen)) != len(seen):
        raise ValueError(f"{name} must not contain duplicates")
    return seen


@dataclass(frozen=True)
class ReadFailure:
    """A stable, redacted read failure.  Raw venue text is never retained."""

    code: ReadErrorCode
    venue_ret_code: int | None = None
    venue_safe_code: str | None = None

    def __post_init__(self) -> None:
        try:
            code = self.code if isinstance(self.code, ReadErrorCode) else ReadErrorCode(self.code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown read error code") from exc
        object.__setattr__(self, "code", code)
        if self.venue_ret_code is not None:
            if isinstance(self.venue_ret_code, bool) or not isinstance(self.venue_ret_code, int):
                raise TypeError("venue_ret_code must be an integer or None")
        if self.venue_safe_code is not None:
            object.__setattr__(
                self, "venue_safe_code", _opaque("venue_safe_code", self.venue_safe_code, maximum=64)
            )

    @property
    def safe_message(self) -> str:
        return _SAFE_MESSAGES[self.code]

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE


@dataclass(frozen=True)
class CoinBalance:
    coin: str
    equity: Decimal | None
    usd_value: Decimal | None
    wallet_balance: Decimal | None
    locked: Decimal | None
    unrealised_pnl: Decimal | None
    cum_realised_pnl: Decimal | None
    missing_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "coin", _opaque("coin", self.coin, maximum=32).upper())
        for name in ("equity", "usd_value", "wallet_balance", "locked", "unrealised_pnl", "cum_realised_pnl"):
            _decimal_value(name, getattr(self, name))
        object.__setattr__(self, "missing_fields", _missing("missing_fields", self.missing_fields))


@dataclass(frozen=True)
class WalletBalanceObservation:
    account_type: str
    total_equity_usd: Decimal | None
    total_wallet_balance_usd: Decimal | None
    total_margin_balance_usd: Decimal | None
    total_available_balance_usd: Decimal | None
    total_perp_upl_usd: Decimal | None
    coins: Tuple[CoinBalance, ...]
    missing_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_type", _opaque("account_type", self.account_type, maximum=32).upper())
        if self.account_type != "UNIFIED":
            raise ValueError("only UNIFIED wallet observations are supported")
        for name in (
            "total_equity_usd",
            "total_wallet_balance_usd",
            "total_margin_balance_usd",
            "total_available_balance_usd",
            "total_perp_upl_usd",
        ):
            _decimal_value(name, getattr(self, name))
        if not isinstance(self.coins, tuple) or not all(isinstance(item, CoinBalance) for item in self.coins):
            raise TypeError("coins must be a tuple of CoinBalance")
        names = [item.coin for item in self.coins]
        if len(set(names)) != len(names):
            raise ValueError("coins must not contain duplicate coin entries")
        object.__setattr__(self, "missing_fields", _missing("missing_fields", self.missing_fields))


@dataclass(frozen=True)
class PositionObservation:
    category: str
    symbol: str
    position_idx: int
    side: OrderSide | None
    size: Decimal
    avg_price: Decimal | None
    mark_price: Decimal | None
    unrealised_pnl: Decimal | None
    position_value: Decimal | None
    leverage: Decimal | None
    missing_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _opaque("category", self.category, maximum=16).lower())
        object.__setattr__(self, "symbol", _opaque("symbol", self.symbol, maximum=64).upper())
        if isinstance(self.position_idx, bool) or not isinstance(self.position_idx, int):
            raise TypeError("position_idx must be an integer")
        if self.position_idx not in (0, 1, 2):
            raise ValueError("position_idx must be 0, 1 or 2")
        if self.side is not None:
            _exact_enum(OrderSide, "side", self.side)
        if not isinstance(self.size, Decimal) or not self.size.is_finite():
            raise ValueError("size must be a finite Decimal")
        if self.size < 0:
            raise ValueError("size must not be negative")
        if self.side is None and self.size != 0:
            raise ValueError("an empty position side requires size 0")
        if self.side is not None and self.size == 0:
            raise ValueError("a non-empty position side requires positive size")
        for name in ("avg_price", "mark_price", "unrealised_pnl", "position_value", "leverage"):
            _decimal_value(name, getattr(self, name))
        object.__setattr__(self, "missing_fields", _missing("missing_fields", self.missing_fields))


_OPEN_ORDER_STATUSES = frozenset({"New", "PartiallyFilled", "Untriggered"})


@dataclass(frozen=True)
class OpenOrderObservation:
    category: str
    order_id: str
    client_order_id: str | None
    symbol: str
    side: OrderSide
    order_type: str | None
    order_status: str
    price: Decimal | None
    qty: Decimal
    leaves_qty: Decimal | None
    cum_exec_qty: Decimal | None
    cum_exec_value: Decimal | None
    avg_price: Decimal | None
    reduce_only: bool | None
    position_idx: int | None
    created_at: datetime | None
    updated_at: datetime | None
    missing_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _opaque("category", self.category, maximum=16).lower())
        object.__setattr__(self, "order_id", _opaque("order_id", self.order_id, maximum=128))
        if self.client_order_id is not None:
            object.__setattr__(
                self, "client_order_id", _opaque("client_order_id", self.client_order_id, maximum=128)
            )
        object.__setattr__(self, "symbol", _opaque("symbol", self.symbol, maximum=64).upper())
        _exact_enum(OrderSide, "side", self.side)
        if self.order_type is not None:
            object.__setattr__(self, "order_type", _opaque("order_type", self.order_type, maximum=32))
        status = _opaque("order_status", self.order_status, maximum=32)
        if status not in _OPEN_ORDER_STATUSES:
            raise ValueError("only open order statuses may appear in an open order observation")
        object.__setattr__(self, "order_status", status)
        for name in ("price", "leaves_qty", "cum_exec_qty", "cum_exec_value", "avg_price"):
            _decimal_value(name, getattr(self, name))
        if not isinstance(self.qty, Decimal) or not self.qty.is_finite() or self.qty <= 0:
            raise ValueError("qty must be a finite positive Decimal")
        for name in ("leaves_qty", "cum_exec_qty"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.reduce_only is not None and type(self.reduce_only) is not bool:
            raise TypeError("reduce_only must be bool or None")
        if self.position_idx is not None and (
            isinstance(self.position_idx, bool)
            or not isinstance(self.position_idx, int)
            or self.position_idx not in (0, 1, 2)
        ):
            raise ValueError("position_idx must be 0, 1, 2 or None")
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _utc("updated_at", self.updated_at))
        object.__setattr__(self, "missing_fields", _missing("missing_fields", self.missing_fields))


@dataclass(frozen=True)
class ReadMetadata:
    account_id: AccountId
    registry_revision: int
    record_revision: int
    endpoint: ReadEndpoint
    endpoint_profile: EndpointProfile
    read_started_at: datetime
    read_completed_at: datetime
    source_timestamp: datetime | None
    source_timestamp_available: bool
    pages_fetched: int
    data_quality: ReadDataQuality
    failure: ReadFailure | None
    missing_fields: Tuple[str, ...] = ()
    oldest_source_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("registry_revision", self.registry_revision)
        _positive_int("record_revision", self.record_revision)
        _exact_enum(ReadEndpoint, "endpoint", self.endpoint)
        _exact_enum(EndpointProfile, "endpoint_profile", self.endpoint_profile)
        started = _utc("read_started_at", self.read_started_at)
        completed = _utc("read_completed_at", self.read_completed_at)
        if completed < started:
            raise ValueError("read_completed_at must not precede read_started_at")
        object.__setattr__(self, "read_started_at", started)
        object.__setattr__(self, "read_completed_at", completed)
        if self.source_timestamp is not None:
            object.__setattr__(self, "source_timestamp", _utc("source_timestamp", self.source_timestamp))
        if type(self.source_timestamp_available) is not bool:
            raise TypeError("source_timestamp_available must be bool")
        if self.source_timestamp_available is not (self.source_timestamp is not None):
            raise ValueError("source_timestamp_available must match source_timestamp presence")
        if self.oldest_source_timestamp is not None:
            oldest = _utc("oldest_source_timestamp", self.oldest_source_timestamp)
            if self.source_timestamp is None:
                raise ValueError("oldest_source_timestamp requires source_timestamp")
            if oldest > self.source_timestamp:
                raise ValueError("oldest_source_timestamp must not exceed source_timestamp")
            object.__setattr__(self, "oldest_source_timestamp", oldest)
        _nonnegative_int("pages_fetched", self.pages_fetched)
        _exact_enum(ReadDataQuality, "data_quality", self.data_quality)
        if self.failure is not None and not isinstance(self.failure, ReadFailure):
            raise TypeError("failure must be ReadFailure or None")
        if self.data_quality is ReadDataQuality.COMPLETE and self.failure is not None:
            raise ValueError("COMPLETE data must not carry a failure")
        if self.data_quality is not ReadDataQuality.COMPLETE and self.failure is None:
            raise ValueError("non-COMPLETE data requires a failure")
        object.__setattr__(self, "missing_fields", _missing("missing_fields", self.missing_fields))


def _validate_result(metadata: ReadMetadata, endpoint: ReadEndpoint, has_data: bool, *, data_required: bool) -> None:
    if not isinstance(metadata, ReadMetadata):
        raise TypeError("metadata must be ReadMetadata")
    if metadata.endpoint is not endpoint:
        raise ValueError("result metadata endpoint does not match the result type")
    if metadata.data_quality is ReadDataQuality.FAILED:
        if has_data:
            raise ValueError("FAILED result must not carry observed data")
    elif data_required and not has_data:
        raise ValueError("non-FAILED endpoint result requires observed data")


@dataclass(frozen=True)
class AccountSummaryReadResult:
    metadata: ReadMetadata
    summary: WalletBalanceObservation | None

    def __post_init__(self) -> None:
        _validate_result(
            self.metadata, ReadEndpoint.ACCOUNT_SUMMARY, self.summary is not None, data_required=True
        )
        if self.summary is not None and not isinstance(self.summary, WalletBalanceObservation):
            raise TypeError("summary must be WalletBalanceObservation or None")


@dataclass(frozen=True)
class PositionsReadResult:
    metadata: ReadMetadata
    positions: Tuple[PositionObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.positions, tuple) or not all(
            isinstance(item, PositionObservation) for item in self.positions
        ):
            raise TypeError("positions must be a tuple of PositionObservation")
        _validate_result(self.metadata, ReadEndpoint.POSITIONS, bool(self.positions), data_required=False)
        if self.metadata.data_quality is ReadDataQuality.COMPLETE and self.metadata.pages_fetched < 1:
            raise ValueError("a COMPLETE position result requires at least one fetched page")


@dataclass(frozen=True)
class OpenOrdersReadResult:
    metadata: ReadMetadata
    orders: Tuple[OpenOrderObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.orders, tuple) or not all(
            isinstance(item, OpenOrderObservation) for item in self.orders
        ):
            raise TypeError("orders must be a tuple of OpenOrderObservation")
        _validate_result(self.metadata, ReadEndpoint.OPEN_ORDERS, bool(self.orders), data_required=False)
        if self.metadata.data_quality is ReadDataQuality.COMPLETE and self.metadata.pages_fetched < 1:
            raise ValueError("a COMPLETE order result requires at least one fetched page")


def aggregate_quality(qualities: Tuple[ReadDataQuality, ...]) -> ReadDataQuality:
    if not qualities:
        raise ValueError("at least one endpoint quality is required")
    for quality in qualities:
        _exact_enum(ReadDataQuality, "data quality", quality)
    if all(quality is ReadDataQuality.FAILED for quality in qualities):
        return ReadDataQuality.FAILED
    if any(quality in (ReadDataQuality.FAILED, ReadDataQuality.PARTIAL) for quality in qualities):
        return ReadDataQuality.PARTIAL
    if any(quality is ReadDataQuality.STALE for quality in qualities):
        return ReadDataQuality.STALE
    return ReadDataQuality.COMPLETE


@dataclass(frozen=True)
class AccountObservationResult:
    """Non-atomic envelope over independently timed endpoint observations."""

    account_id: AccountId
    registry_revision: int
    record_revision: int
    endpoint_profile: EndpointProfile
    started_at: datetime
    completed_at: datetime
    summary: AccountSummaryReadResult
    positions: PositionsReadResult
    open_orders: OpenOrdersReadResult
    overall_quality: ReadDataQuality
    atomic_snapshot: bool = False
    post_read_binding_failure: ReadFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("registry_revision", self.registry_revision)
        _positive_int("record_revision", self.record_revision)
        _exact_enum(EndpointProfile, "endpoint_profile", self.endpoint_profile)
        started = _utc("started_at", self.started_at)
        completed = _utc("completed_at", self.completed_at)
        if completed < started:
            raise ValueError("completed_at must not precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "completed_at", completed)
        for name in ("summary", "positions", "open_orders"):
            value = getattr(self, name)
            if not isinstance(
                value,
                (AccountSummaryReadResult, PositionsReadResult, OpenOrdersReadResult),
            ):
                raise TypeError(f"{name} has an invalid read result type")
        for result in (self.summary, self.positions, self.open_orders):
            if result.metadata.account_id != self.account_id:
                raise ValueError("endpoint result account scope does not match the observation")
            if (
                result.metadata.registry_revision != self.registry_revision
                or result.metadata.record_revision != self.record_revision
                or result.metadata.endpoint_profile is not self.endpoint_profile
            ):
                raise ValueError("endpoint result binding scope does not match the observation")
        _exact_enum(ReadDataQuality, "overall_quality", self.overall_quality)
        if self.post_read_binding_failure is not None and not isinstance(
            self.post_read_binding_failure, ReadFailure
        ):
            raise TypeError("post_read_binding_failure must be ReadFailure or None")
        expected = aggregate_quality(
            (
                self.summary.metadata.data_quality,
                self.positions.metadata.data_quality,
                self.open_orders.metadata.data_quality,
            )
        )
        if self.post_read_binding_failure is not None and expected is ReadDataQuality.COMPLETE:
            expected = ReadDataQuality.PARTIAL
        if self.overall_quality is not expected:
            raise ValueError("overall_quality does not match the endpoint qualities")
        if self.atomic_snapshot is not False:
            raise ValueError("an endpoint envelope is not an atomic account snapshot")
