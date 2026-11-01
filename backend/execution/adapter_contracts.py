"""Side-effect-free adapter contracts.

This module defines boundaries only.  It never creates a venue client, reads
credentials, opens a connection, writes a file, or registers an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Protocol, Tuple

from backend.accounts.models import (
    AccountId,
    AccountIdentity,
    ExecutionMode,
    ExecutionVenue,
    ensure_account_match,
)
from backend.prop_trading.contracts import PropRuleDefinition


class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class AdapterResultStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class AdapterErrorCode(str, Enum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VENUE_REJECTED = "VENUE_REJECTED"
    STATE_UNKNOWN = "STATE_UNKNOWN"


_ADAPTER_SAFE_MESSAGES = {
    AdapterErrorCode.AUTHENTICATION_FAILED: "adapter authentication failed",
    AdapterErrorCode.PERMISSION_DENIED: "adapter permission denied",
    AdapterErrorCode.RATE_LIMITED: "adapter rate limited",
    AdapterErrorCode.TIMEOUT: "adapter request timed out",
    AdapterErrorCode.UNSUPPORTED_CAPABILITY: "adapter capability unsupported",
    AdapterErrorCode.CAPABILITY_UNKNOWN: "adapter capability unknown",
    AdapterErrorCode.VALIDATION_FAILED: "adapter request validation failed",
    AdapterErrorCode.VENUE_REJECTED: "adapter request rejected",
    AdapterErrorCode.STATE_UNKNOWN: "adapter state unknown",
}


class ExecutionOperation(str, Enum):
    ENTRY = "ENTRY"
    CANCEL = "CANCEL"
    PROTECTIVE = "PROTECTIVE"
    REDUCE_OR_CLOSE = "REDUCE_OR_CLOSE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _enum(enum_type, name: str, value: object):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _decimal(name: str, value: object, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


@dataclass(frozen=True)
class AdapterCapabilities:
    account_read: CapabilityState = CapabilityState.UNKNOWN
    positions_read: CapabilityState = CapabilityState.UNKNOWN
    orders_read: CapabilityState = CapabilityState.UNKNOWN
    fills_read: CapabilityState = CapabilityState.UNKNOWN
    order_submit: CapabilityState = CapabilityState.UNKNOWN
    order_cancel: CapabilityState = CapabilityState.UNKNOWN
    reduce_only: CapabilityState = CapabilityState.UNKNOWN
    stop_order: CapabilityState = CapabilityState.UNKNOWN
    client_order_id_lookup: CapabilityState = CapabilityState.UNKNOWN
    idempotent_submit: CapabilityState = CapabilityState.UNKNOWN
    instrument_rules: CapabilityState = CapabilityState.UNKNOWN
    server_time: CapabilityState = CapabilityState.UNKNOWN
    rule_snapshot_read: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            try:
                normalized = value if isinstance(value, CapabilityState) else CapabilityState(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown capability state for {name}") from exc
            object.__setattr__(self, name, normalized)

    def require(self, name: str) -> None:
        if name not in self.__dataclass_fields__:
            raise ValueError(f"unknown capability: {name}")
        state = getattr(self, name)
        if state is CapabilityState.UNSUPPORTED:
            raise RuntimeError(AdapterErrorCode.UNSUPPORTED_CAPABILITY.value)
        if state is CapabilityState.UNKNOWN:
            raise RuntimeError(AdapterErrorCode.CAPABILITY_UNKNOWN.value)


@dataclass(frozen=True)
class AdapterBinding:
    identity: AccountIdentity
    credential_ref: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AccountIdentity):
            raise TypeError("identity must be AccountIdentity")
        if self.identity.execution_mode is ExecutionMode.PAPER:
            if self.credential_ref is not None:
                raise ValueError("PAPER binding must not contain a credential reference")
        elif not isinstance(self.credential_ref, str) or not self.credential_ref.strip():
            raise ValueError("external adapter binding requires an opaque credential reference")


@dataclass(frozen=True)
class InstrumentSpec:
    execution_venue: ExecutionVenue
    instrument_id: str
    price_increment: Decimal
    quantity_increment: Decimal
    minimum_quantity: Decimal
    minimum_notional: Optional[Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue))
        object.__setattr__(self, "instrument_id", _text("instrument_id", self.instrument_id))
        for name in ("price_increment", "quantity_increment", "minimum_quantity"):
            _decimal(name, getattr(self, name), positive=True)
        if self.minimum_notional is not None:
            _decimal("minimum_notional", self.minimum_notional, positive=True)


@dataclass(frozen=True)
class QuoteSnapshot:
    execution_venue: ExecutionVenue
    instrument_id: str
    observed_at: datetime
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    last: Optional[Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue))
        object.__setattr__(self, "instrument_id", _text("instrument_id", self.instrument_id))
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))
        for name in ("bid", "ask", "last"):
            value = getattr(self, name)
            if value is not None:
                _decimal(name, value, positive=True)
        if self.bid is None and self.ask is None and self.last is None:
            raise ValueError("quote must contain at least one observed price")


@dataclass(frozen=True)
class AdapterAccountSnapshot:
    account_id: AccountId
    observed_at: datetime
    source: str
    currency: str
    balance: Optional[Decimal]
    equity: Optional[Decimal]
    available_balance: Optional[Decimal]
    open_position_count: Optional[int]
    open_order_count: Optional[int]
    missing_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))
        object.__setattr__(self, "source", _text("source", self.source))
        object.__setattr__(self, "currency", _text("currency", self.currency).upper())
        for name in ("balance", "equity", "available_balance"):
            value = getattr(self, name)
            if value is not None:
                _decimal(name, value)
        for name in ("open_position_count", "open_order_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        missing = tuple(_text("missing_field", item) for item in self.missing_fields)
        if len(set(missing)) != len(missing):
            raise ValueError("missing_fields must not contain duplicates")
        object.__setattr__(self, "missing_fields", missing)


@dataclass(frozen=True)
class AdapterFailure:
    code: AdapterErrorCode
    safe_message: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            code = AdapterErrorCode(self.code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown adapter error code") from exc
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "safe_message", _ADAPTER_SAFE_MESSAGES[code])


@dataclass(frozen=True)
class AccountReadResult:
    account_id: AccountId
    status: AdapterResultStatus
    snapshot: Optional[AdapterAccountSnapshot]
    failure: Optional[AdapterFailure]

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "status", _enum(AdapterResultStatus, "result status", self.status))
        if self.snapshot is not None:
            if not isinstance(self.snapshot, AdapterAccountSnapshot):
                raise TypeError("snapshot must be AdapterAccountSnapshot")
            ensure_account_match(self.account_id, self.snapshot.account_id, label="adapter snapshot")
        if self.status is AdapterResultStatus.SUCCEEDED:
            if self.snapshot is None or self.failure is not None:
                raise ValueError("successful read requires snapshot and no failure")
        elif self.failure is None or self.snapshot is not None:
            raise ValueError("non-successful read requires failure and no snapshot")


@dataclass(frozen=True)
class PropRuleReadResult:
    account_id: AccountId
    status: AdapterResultStatus
    rule_definition: Optional[PropRuleDefinition]
    failure: Optional[AdapterFailure]

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "status", _enum(AdapterResultStatus, "result status", self.status))
        if self.rule_definition is not None and not isinstance(self.rule_definition, PropRuleDefinition):
            raise TypeError("rule_definition must be PropRuleDefinition")
        if self.status is AdapterResultStatus.SUCCEEDED:
            if self.rule_definition is None or self.failure is not None:
                raise ValueError("successful rule read requires a definition and no failure")
        elif self.rule_definition is not None or self.failure is None:
            raise ValueError("non-successful rule read requires failure and no definition")


@dataclass(frozen=True)
class ExecutionIntent:
    account_id: AccountId
    client_order_id: str
    operation: ExecutionOperation
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reduce_only: bool
    created_at: datetime
    limit_price: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "client_order_id", _text("client_order_id", self.client_order_id))
        object.__setattr__(self, "instrument_id", _text("instrument_id", self.instrument_id))
        object.__setattr__(self, "operation", _enum(ExecutionOperation, "operation", self.operation))
        object.__setattr__(self, "side", _enum(OrderSide, "side", self.side))
        object.__setattr__(self, "order_type", _enum(OrderType, "order_type", self.order_type))
        _decimal("quantity", self.quantity, positive=True)
        if type(self.reduce_only) is not bool:
            raise TypeError("reduce_only must be bool")
        object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if self.limit_price is not None:
            _decimal("limit_price", self.limit_price, positive=True)
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT intent requires limit_price")
        if self.operation is ExecutionOperation.ENTRY and self.reduce_only:
            raise ValueError("ENTRY intent cannot be reduce_only")
        if self.operation is ExecutionOperation.REDUCE_OR_CLOSE and not self.reduce_only:
            raise ValueError("REDUCE_OR_CLOSE intent must be reduce_only")


@dataclass(frozen=True)
class CancelIntent:
    account_id: AccountId
    client_order_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "client_order_id", _text("client_order_id", self.client_order_id))
        object.__setattr__(self, "requested_at", _utc("requested_at", self.requested_at))


@dataclass(frozen=True)
class OrderSubmissionResult:
    account_id: AccountId
    client_order_id: str
    status: AdapterResultStatus
    observed_at: datetime
    venue_order_id: Optional[str] = None
    failure: Optional[AdapterFailure] = None

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "client_order_id", _text("client_order_id", self.client_order_id))
        object.__setattr__(self, "status", _enum(AdapterResultStatus, "result status", self.status))
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))
        if self.venue_order_id is not None:
            object.__setattr__(self, "venue_order_id", _text("venue_order_id", self.venue_order_id))
        if self.status is AdapterResultStatus.SUCCEEDED:
            if self.venue_order_id is None or self.failure is not None:
                raise ValueError("successful submission requires venue_order_id and no failure")
        elif self.failure is None:
            raise ValueError("non-successful submission requires a failure")


@dataclass(frozen=True)
class BoundExecutionRequest:
    binding: AdapterBinding
    intent: ExecutionIntent

    def __post_init__(self) -> None:
        if not isinstance(self.binding, AdapterBinding):
            raise TypeError("binding must be AdapterBinding")
        if not isinstance(self.intent, ExecutionIntent):
            raise TypeError("intent must be ExecutionIntent")
        ensure_account_match(self.binding.identity.account_id, self.intent.account_id, label="execution binding")


@dataclass(frozen=True)
class BoundCancelRequest:
    binding: AdapterBinding
    intent: CancelIntent

    def __post_init__(self) -> None:
        if not isinstance(self.binding, AdapterBinding):
            raise TypeError("binding must be AdapterBinding")
        if not isinstance(self.intent, CancelIntent):
            raise TypeError("intent must be CancelIntent")
        ensure_account_match(self.binding.identity.account_id, self.intent.account_id, label="cancel binding")


@dataclass(frozen=True)
class BoundExecutionResult:
    request: BoundExecutionRequest
    result: OrderSubmissionResult

    def __post_init__(self) -> None:
        if not isinstance(self.request, BoundExecutionRequest):
            raise TypeError("request must be BoundExecutionRequest")
        if not isinstance(self.result, OrderSubmissionResult):
            raise TypeError("result must be OrderSubmissionResult")
        ensure_account_match(self.request.intent.account_id, self.result.account_id, label="submission result")
        if self.request.intent.client_order_id != self.result.client_order_id:
            raise ValueError("submission result client_order_id mismatch")


@dataclass(frozen=True)
class BoundCancelResult:
    request: BoundCancelRequest
    result: OrderSubmissionResult

    def __post_init__(self) -> None:
        if not isinstance(self.request, BoundCancelRequest):
            raise TypeError("request must be BoundCancelRequest")
        if not isinstance(self.result, OrderSubmissionResult):
            raise TypeError("result must be OrderSubmissionResult")
        ensure_account_match(self.request.intent.account_id, self.result.account_id, label="cancel result")
        if self.request.intent.client_order_id != self.result.client_order_id:
            raise ValueError("cancel result client_order_id mismatch")


class AccountReadAdapter(Protocol):
    @property
    def binding(self) -> AdapterBinding: ...

    @property
    def capabilities(self) -> AdapterCapabilities: ...

    def get_account_snapshot(self) -> AccountReadResult: ...

    def find_order_by_client_id(self, client_order_id: str) -> OrderSubmissionResult: ...


class PublicMarketDataAdapter(Protocol):
    @property
    def execution_venue(self) -> ExecutionVenue: ...

    def get_quote(self, instrument_id: str) -> QuoteSnapshot: ...


class InstrumentCatalogAdapter(Protocol):
    @property
    def execution_venue(self) -> ExecutionVenue: ...

    def resolve_instrument(self, canonical_symbol: str) -> InstrumentSpec: ...


class PropRuleReadAdapter(Protocol):
    @property
    def binding(self) -> AdapterBinding: ...

    @property
    def capabilities(self) -> AdapterCapabilities: ...

    def get_rule_snapshot(self, as_of: datetime) -> PropRuleReadResult: ...


class ExecutionAdapter(Protocol):
    @property
    def binding(self) -> AdapterBinding: ...

    @property
    def capabilities(self) -> AdapterCapabilities: ...

    def submit_order(self, request: BoundExecutionRequest) -> BoundExecutionResult: ...

    def cancel_order(self, request: BoundCancelRequest) -> BoundCancelResult: ...
