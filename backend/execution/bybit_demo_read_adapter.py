"""Offline-capable Bybit Demo V5 read-only adapter.

The adapter only composes allowlisted GET requests and normalizes injected fake
responses.  It contains no HTTP client, no signing, no credential resolution and
no order path.  A transport and a clock must be injected explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Optional, Tuple

from backend.accounts.models import AccountLifecycleState, AccountType, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import AccountRegistrySnapshot
from backend.execution.adapter_contracts import CapabilityState, OrderSide
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadBindingCurrentness,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
    evaluate_read_binding,
)
from backend.execution.read_only_observations import (
    AccountObservationResult,
    AccountSummaryReadResult,
    CoinBalance,
    OpenOrderObservation,
    OpenOrdersReadResult,
    PositionObservation,
    PositionsReadResult,
    ReadDataQuality,
    ReadEndpoint,
    ReadErrorCode,
    ReadFailure,
    ReadMetadata,
    WalletBalanceObservation,
    aggregate_quality,
)
from backend.execution.read_only_transport import (
    ReadOnlyClock,
    ReadOnlyRequest,
    ReadOnlyResponse,
    ReadOnlyTransport,
    ReadTransportError,
    ReadTransportFailureKind,
)


BYBIT_DEMO_REST_BASE = "https://api-demo.bybit.com"
BYBIT_DEMO_V5_CATEGORY = "linear"
BYBIT_DEMO_V5_DEFAULT_SETTLE_COIN = "USDT"

ACCOUNT_SUMMARY_PATH = "/v5/account/wallet-balance"
POSITIONS_PATH = "/v5/position/list"
OPEN_ORDERS_PATH = "/v5/order/realtime"

_ENDPOINT_ALLOWLIST = frozenset({ACCOUNT_SUMMARY_PATH, POSITIONS_PATH, OPEN_ORDERS_PATH})
_POSITION_PAGE_LIMIT = 200
_ORDER_PAGE_LIMIT = 50

_OPEN_ORDER_STATUSES = frozenset({"New", "PartiallyFilled", "Untriggered"})

_VENUE_ERROR_CODES = {
    10002: ReadErrorCode.CLOCK_SKEW,
    10003: ReadErrorCode.AUTHENTICATION_FAILED,
    10004: ReadErrorCode.AUTHENTICATION_FAILED,
    10005: ReadErrorCode.PERMISSION_DENIED,
    10006: ReadErrorCode.RATE_LIMITED,
    10007: ReadErrorCode.AUTHENTICATION_FAILED,
    10010: ReadErrorCode.PERMISSION_DENIED,
    10016: ReadErrorCode.TRANSPORT_FAILURE,
    10018: ReadErrorCode.RATE_LIMITED,
    429: ReadErrorCode.RATE_LIMITED,
}

_PARTIAL_CODES = frozenset(
    {
        ReadErrorCode.PARTIAL_DATA,
        ReadErrorCode.PAGINATION_INCOMPLETE,
        ReadErrorCode.DUPLICATE_RECORD,
    }
)
_STALE_CODES = frozenset({ReadErrorCode.STALE_DATA, ReadErrorCode.CLOCK_SKEW})

_REQUIRED_WALLET_ACCOUNT_FIELDS = (
    "totalEquity",
    "totalWalletBalance",
    "totalMarginBalance",
    "totalAvailableBalance",
)

_PURPOSE_BY_ENDPOINT = {
    ReadEndpoint.ACCOUNT_SUMMARY: frozenset({ReadPurpose.ACCOUNT_OBSERVATION}),
    ReadEndpoint.POSITIONS: frozenset(
        {ReadPurpose.ACCOUNT_OBSERVATION, ReadPurpose.POSITIONS_READ}
    ),
    ReadEndpoint.OPEN_ORDERS: frozenset(
        {ReadPurpose.ACCOUNT_OBSERVATION, ReadPurpose.ORDERS_READ}
    ),
}


class _MalformedResponse(Exception):
    """Internal marker; never exposed with response content."""


def _now_utc(clock: ReadOnlyClock) -> datetime:
    value = clock.now()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _http_failure(status_code: int) -> ReadFailure:
    if status_code == 401:
        return ReadFailure(ReadErrorCode.AUTHENTICATION_FAILED)
    if status_code == 403:
        return ReadFailure(ReadErrorCode.PERMISSION_DENIED)
    if status_code == 429:
        return ReadFailure(ReadErrorCode.RATE_LIMITED)
    if 500 <= status_code <= 599:
        return ReadFailure(ReadErrorCode.TRANSPORT_FAILURE)
    return ReadFailure(ReadErrorCode.VENUE_REJECTED)


_TRANSPORT_FAILURE_CODES = {
    ReadTransportFailureKind.TIMEOUT: ReadErrorCode.TIMEOUT,
    ReadTransportFailureKind.INVALID_RESPONSE: ReadErrorCode.MALFORMED_RESPONSE,
    ReadTransportFailureKind.RESPONSE_TOO_LARGE: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.REDIRECT_REJECTED: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.POLICY_REJECTED: ReadErrorCode.INVALID_REQUEST,
    ReadTransportFailureKind.CREDENTIAL_REJECTED: ReadErrorCode.AUTHENTICATION_FAILED,
    ReadTransportFailureKind.READINESS_REJECTED: ReadErrorCode.STALE_BINDING,
    ReadTransportFailureKind.CLOCK_REJECTED: ReadErrorCode.CLOCK_SKEW,
    ReadTransportFailureKind.CONNECTION_FAILED: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.STATE_UNKNOWN: ReadErrorCode.STATE_UNKNOWN,
}


def _transport_failure(error: ReadTransportError) -> ReadFailure:
    return ReadFailure(
        _TRANSPORT_FAILURE_CODES.get(error.kind, ReadErrorCode.TRANSPORT_FAILURE)
    )


def _venue_failure(ret_code: int) -> ReadFailure:
    code = _VENUE_ERROR_CODES.get(ret_code, ReadErrorCode.VENUE_REJECTED)
    return ReadFailure(code, venue_ret_code=ret_code)


def _failure_for_quality(failure: Optional[ReadFailure], has_data: bool) -> ReadDataQuality:
    if failure is None:
        return ReadDataQuality.COMPLETE
    if failure.code in _STALE_CODES:
        return ReadDataQuality.STALE if has_data else ReadDataQuality.FAILED
    if failure.code in _PARTIAL_CODES:
        return ReadDataQuality.PARTIAL
    return ReadDataQuality.PARTIAL if has_data else ReadDataQuality.FAILED


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _MalformedResponse()
    return value


def _require_list(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise _MalformedResponse()
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _MalformedResponse()
    text = value.strip()
    if any(ord(char) < 32 for char in text):
        raise _MalformedResponse()
    return text


def _optional_text(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MalformedResponse()
    text = value.strip()
    if not text:
        return None
    if any(ord(char) < 32 for char in text):
        raise _MalformedResponse()
    return text


def _required_decimal(value: Any, name: str) -> Decimal:
    parsed = _optional_decimal(value, name)
    if parsed is None:
        raise _MalformedResponse()
    return parsed


def _optional_decimal(value: Any, name: str) -> Optional[Decimal]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MalformedResponse()
    text = value.strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise _MalformedResponse() from exc
    if not parsed.is_finite():
        raise _MalformedResponse()
    return parsed


def _required_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _MalformedResponse()
    return value


def _optional_int(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    return _required_int(value, name)


def _optional_bool(value: Any, name: str) -> Optional[bool]:
    if value is None:
        return None
    if type(value) is not bool:
        raise _MalformedResponse()
    return value


def _optional_ms(value: Any, name: str) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _MalformedResponse()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not text.isdigit():
            raise _MalformedResponse()
        milliseconds = int(text)
    elif isinstance(value, int):
        milliseconds = value
    else:
        raise _MalformedResponse()
    if milliseconds < 0:
        raise _MalformedResponse()
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise _MalformedResponse() from exc


def _parse_envelope(body: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Optional[datetime]]:
    if not isinstance(body, Mapping):
        raise _MalformedResponse()
    if "retCode" not in body:
        raise _MalformedResponse()
    ret_code = body["retCode"]
    if isinstance(ret_code, bool) or not isinstance(ret_code, int):
        raise _MalformedResponse()
    if not isinstance(body.get("retMsg"), str):
        raise _MalformedResponse()
    if ret_code != 0:
        raise _VenueEnvelopeError(ret_code)
    source_timestamp = _optional_ms(body.get("time"), "time")
    result = body.get("result")
    if not isinstance(result, Mapping):
        raise _MalformedResponse()
    return result, source_timestamp


class _VenueEnvelopeError(Exception):
    def __init__(self, ret_code: int) -> None:
        self.ret_code = ret_code
        super().__init__("venue envelope rejected the read request")


def _normalize_side(value: str, *, allow_empty: bool = False) -> Optional[OrderSide]:
    if value == "Buy":
        return OrderSide.BUY
    if value == "Sell":
        return OrderSide.SELL
    if allow_empty and value == "":
        return None
    raise _MalformedResponse()


def _side_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _MalformedResponse()
    text = value.strip()
    if not text and not allow_empty:
        raise _MalformedResponse()
    if any(ord(char) < 32 for char in text):
        raise _MalformedResponse()
    return text


def _parse_wallet_balance(result: Mapping[str, Any]) -> WalletBalanceObservation:
    items = _require_list(result.get("list"), "list")
    if len(items) != 1:
        raise _MalformedResponse()
    item = _require_mapping(items[0], "list item")
    account_type = _require_text(item.get("accountType"), "accountType")
    if account_type != "UNIFIED":
        raise _MalformedResponse()
    missing: list[str] = []

    def optional(name: str) -> Optional[Decimal]:
        parsed = _optional_decimal(item.get(name), name)
        if parsed is None:
            missing.append(name)
        return parsed

    account_values = {
        "total_equity_usd": optional("totalEquity"),
        "total_wallet_balance_usd": optional("totalWalletBalance"),
        "total_margin_balance_usd": optional("totalMarginBalance"),
        "total_available_balance_usd": optional("totalAvailableBalance"),
        "total_perp_upl_usd": optional("totalPerpUPL"),
    }
    if any(name in missing for name in _REQUIRED_WALLET_ACCOUNT_FIELDS):
        raise _MalformedResponse()
    if "coin" not in item:
        raise _MalformedResponse()
    coins_raw = _require_list(item.get("coin"), "coin")
    coins: list[CoinBalance] = []
    seen: set[str] = set()
    for raw in coins_raw:
        coin_item = _require_mapping(raw, "coin item")
        coin = _require_text(coin_item.get("coin"), "coin")
        if coin in seen:
            raise _MalformedResponse()
        seen.add(coin)
        coin_missing: list[str] = []

        def coin_optional(name: str) -> Optional[Decimal]:
            parsed = _optional_decimal(coin_item.get(name), name)
            if parsed is None:
                coin_missing.append(name)
            return parsed

        coins.append(
            CoinBalance(
                coin=coin,
                equity=coin_optional("equity"),
                usd_value=coin_optional("usdValue"),
                wallet_balance=coin_optional("walletBalance"),
                locked=coin_optional("locked"),
                unrealised_pnl=coin_optional("unrealisedPnl"),
                cum_realised_pnl=coin_optional("cumRealisedPnl"),
                missing_fields=tuple(coin_missing),
            )
        )
    return WalletBalanceObservation(
        account_type=account_type,
        total_equity_usd=account_values["total_equity_usd"],
        total_wallet_balance_usd=account_values["total_wallet_balance_usd"],
        total_margin_balance_usd=account_values["total_margin_balance_usd"],
        total_available_balance_usd=account_values["total_available_balance_usd"],
        total_perp_upl_usd=account_values["total_perp_upl_usd"],
        coins=tuple(coins),
        missing_fields=tuple(missing),
    )


def _parse_positions_page(result: Mapping[str, Any]) -> Tuple[list[PositionObservation], Optional[str]]:
    category = _require_text(result.get("category"), "category")
    if category != BYBIT_DEMO_V5_CATEGORY:
        raise _MalformedResponse()
    items = _require_list(result.get("list"), "list")
    if "nextPageCursor" not in result:
        raise _MalformedResponse()
    next_cursor = _optional_text(result.get("nextPageCursor"), "nextPageCursor")
    positions: list[PositionObservation] = []
    for raw in items:
        item = _require_mapping(raw, "position item")
        missing: list[str] = []

        def optional(name: str) -> Optional[Decimal]:
            parsed = _optional_decimal(item.get(name), name)
            if parsed is None:
                missing.append(name)
            return parsed

        symbol = _require_text(item.get("symbol"), "symbol")
        position_idx = _required_int(item.get("positionIdx"), "positionIdx")
        side = _normalize_side(_side_text(item.get("side"), "side", allow_empty=True), allow_empty=True)
        size = _required_decimal(item.get("size"), "size")
        if size < 0:
            raise _MalformedResponse()
        position = PositionObservation(
            category=category,
            symbol=symbol,
            position_idx=position_idx,
            side=side,
            size=size,
            avg_price=optional("avgPrice"),
            mark_price=optional("markPrice"),
            unrealised_pnl=optional("unrealisedPnl"),
            position_value=optional("positionValue"),
            leverage=optional("leverage"),
            missing_fields=tuple(missing),
        )
        positions.append(position)
    return positions, next_cursor


def _parse_open_orders_page(result: Mapping[str, Any]) -> Tuple[list[OpenOrderObservation], Optional[str]]:
    category = _require_text(result.get("category"), "category")
    if category != BYBIT_DEMO_V5_CATEGORY:
        raise _MalformedResponse()
    items = _require_list(result.get("list"), "list")
    if "nextPageCursor" not in result:
        raise _MalformedResponse()
    next_cursor = _optional_text(result.get("nextPageCursor"), "nextPageCursor")
    orders: list[OpenOrderObservation] = []
    for raw in items:
        item = _require_mapping(raw, "order item")
        missing: list[str] = []
        order_status = _require_text(item.get("orderStatus"), "orderStatus")
        if order_status not in _OPEN_ORDER_STATUSES:
            raise _MalformedResponse()
        side = _normalize_side(_require_text(item.get("side"), "side"))
        qty = _required_decimal(item.get("qty"), "qty")
        if qty <= 0:
            raise _MalformedResponse()
        price = _optional_decimal(item.get("price"), "price")
        if price is None:
            missing.append("price")
        client_order_id = _optional_text(item.get("orderLinkId"), "orderLinkId")
        if client_order_id is None:
            missing.append("orderLinkId")
        order_type = _optional_text(item.get("orderType"), "orderType")
        if order_type is None:
            missing.append("orderType")
        leaves_qty = _optional_decimal(item.get("leavesQty"), "leavesQty")
        if leaves_qty is None:
            missing.append("leavesQty")
        cum_exec_qty = _optional_decimal(item.get("cumExecQty"), "cumExecQty")
        if cum_exec_qty is None:
            missing.append("cumExecQty")
        cum_exec_value = _optional_decimal(item.get("cumExecValue"), "cumExecValue")
        if cum_exec_value is None:
            missing.append("cumExecValue")
        avg_price = _optional_decimal(item.get("avgPrice"), "avgPrice")
        if avg_price is None:
            missing.append("avgPrice")
        reduce_only = _optional_bool(item.get("reduceOnly"), "reduceOnly")
        if reduce_only is None:
            missing.append("reduceOnly")
        position_idx = _optional_int(item.get("positionIdx"), "positionIdx")
        if position_idx is None:
            missing.append("positionIdx")
        created_at = _optional_ms(item.get("createdTime"), "createdTime")
        if created_at is None:
            missing.append("createdTime")
        updated_at = _optional_ms(item.get("updatedTime"), "updatedTime")
        if updated_at is None:
            missing.append("updatedTime")
        orders.append(
            OpenOrderObservation(
                category=category,
                order_id=_require_text(item.get("orderId"), "orderId"),
                client_order_id=client_order_id,
                symbol=_require_text(item.get("symbol"), "symbol"),
                side=side,
                order_type=order_type,
                order_status=order_status,
                price=price,
                qty=qty,
                leaves_qty=leaves_qty,
                cum_exec_qty=cum_exec_qty,
                cum_exec_value=cum_exec_value,
                avg_price=avg_price,
                reduce_only=reduce_only,
                position_idx=position_idx,
                created_at=created_at,
                updated_at=updated_at,
                missing_fields=tuple(missing),
            )
        )
    return orders, next_cursor


class BybitDemoReadAdapter:
    """Read-only adapter for a fixed Bybit Demo V5 linear/USDT profile.

    ``transport`` and ``clock`` are mandatory.  ``snapshot_source`` is an
    optional injected callable returning an immutable registry snapshot; the
    adapter never reads a registry path itself.
    """

    def __init__(
        self,
        binding: ReadOnlyAdapterConfiguration,
        transport: ReadOnlyTransport,
        clock: ReadOnlyClock,
        *,
        stale_after: timedelta = timedelta(seconds=30),
        future_skew_tolerance: timedelta = timedelta(seconds=60),
        max_pages: int = 10,
        snapshot_source: Optional[Callable[[], Optional[AccountRegistrySnapshot]]] = None,
    ) -> None:
        if not isinstance(binding, ReadOnlyAdapterConfiguration):
            raise TypeError("binding must be ReadOnlyAdapterConfiguration")
        if binding.account_type is not AccountType.PROP:
            raise ValueError("Bybit Demo read adapter only supports PROP accounts")
        if binding.execution_mode is not ExecutionMode.EXTERNAL_SIMULATION:
            raise ValueError("Bybit Demo read adapter requires EXTERNAL_SIMULATION")
        if binding.execution_venue is not ExecutionVenue.BYBIT_DEMO:
            raise ValueError("Bybit Demo read adapter requires BYBIT_DEMO")
        if binding.endpoint_profile is not EndpointProfile.BYBIT_DEMO_V5:
            raise ValueError("Bybit Demo read adapter requires the BYBIT_DEMO_V5 profile")
        if binding.record_lifecycle is not AccountLifecycleState.REGISTERED:
            raise ValueError("Bybit Demo read adapter requires a REGISTERED account")
        if transport is None or not callable(getattr(transport, "send", None)):
            raise TypeError("an explicit read-only transport is required")
        if clock is None or not callable(getattr(clock, "now", None)):
            raise TypeError("an explicit clock is required")
        if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
            raise ValueError("stale_after must be a positive timedelta")
        if not isinstance(future_skew_tolerance, timedelta) or future_skew_tolerance < timedelta(0):
            raise ValueError("future_skew_tolerance must be a nonnegative timedelta")
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if snapshot_source is not None and not callable(snapshot_source):
            raise TypeError("snapshot_source must be callable or None")
        self._binding = binding
        self._transport = transport
        self._clock = clock
        self._stale_after = stale_after
        self._future_skew_tolerance = future_skew_tolerance
        self._max_pages = max_pages
        self._snapshot_source = snapshot_source

    @property
    def binding(self) -> ReadOnlyAdapterConfiguration:
        return self._binding

    @property
    def capabilities(self):
        return self._binding.capabilities

    @property
    def endpoint_base(self) -> str:
        return BYBIT_DEMO_REST_BASE

    def _binding_failure(self) -> Optional[ReadFailure]:
        if self._snapshot_source is None:
            return None
        try:
            snapshot = self._snapshot_source()
        except Exception:
            # A registry source failure must stay inside the typed result
            # boundary; the exception text is deliberately discarded.
            return ReadFailure(ReadErrorCode.STATE_UNKNOWN)
        if not isinstance(snapshot, AccountRegistrySnapshot):
            return ReadFailure(ReadErrorCode.INVALID_BINDING)
        try:
            evaluation = evaluate_read_binding(self._binding, snapshot)
        except Exception:
            return ReadFailure(ReadErrorCode.STATE_UNKNOWN)
        if evaluation.is_current:
            return None
        code = (
            ReadErrorCode.INVALID_BINDING
            if evaluation.currentness is ReadBindingCurrentness.SCOPE_MISMATCH
            else ReadErrorCode.STALE_BINDING
        )
        return ReadFailure(code, venue_safe_code=evaluation.currentness.value)

    def _capability_failure(self, name: str) -> Optional[ReadFailure]:
        state = getattr(self._binding.capabilities, name)
        if state is CapabilityState.UNSUPPORTED:
            return ReadFailure(ReadErrorCode.UNSUPPORTED_CAPABILITY)
        if state is CapabilityState.UNKNOWN:
            return ReadFailure(ReadErrorCode.CAPABILITY_UNKNOWN)
        return None

    def _purpose_failure(self, endpoint: ReadEndpoint) -> Optional[ReadFailure]:
        if self._binding.read_purpose not in _PURPOSE_BY_ENDPOINT[endpoint]:
            return ReadFailure(ReadErrorCode.PURPOSE_MISMATCH)
        return None

    def _request(self, path: str, query: Tuple[Tuple[str, str], ...]) -> ReadOnlyRequest:
        if path not in _ENDPOINT_ALLOWLIST:
            raise ValueError("read path is not allowlisted")
        return ReadOnlyRequest(method="GET", path=path, query=query)

    def _freshness_failure(
        self,
        oldest_source_timestamp: Optional[datetime],
        latest_source_timestamp: Optional[datetime],
        completed_at: datetime,
    ) -> Optional[ReadFailure]:
        newest = latest_source_timestamp if latest_source_timestamp is not None else oldest_source_timestamp
        oldest = oldest_source_timestamp if oldest_source_timestamp is not None else latest_source_timestamp
        if newest is None:
            return None
        if newest > completed_at + self._future_skew_tolerance:
            return ReadFailure(ReadErrorCode.CLOCK_SKEW)
        if completed_at - oldest > self._stale_after:
            return ReadFailure(ReadErrorCode.STALE_DATA)
        return None

    def _metadata(
        self,
        endpoint: ReadEndpoint,
        started_at: datetime,
        completed_at: datetime,
        source_timestamp: Optional[datetime],
        pages_fetched: int,
        failure: Optional[ReadFailure],
        has_data: bool,
        oldest_source_timestamp: Optional[datetime] = None,
    ) -> ReadMetadata:
        return ReadMetadata(
            account_id=self._binding.account_id,
            registry_revision=self._binding.registry_revision,
            record_revision=self._binding.record_revision,
            endpoint=endpoint,
            endpoint_profile=self._binding.endpoint_profile,
            read_started_at=started_at,
            read_completed_at=completed_at,
            source_timestamp=source_timestamp,
            source_timestamp_available=source_timestamp is not None,
            pages_fetched=pages_fetched,
            data_quality=_failure_for_quality(failure, has_data),
            failure=failure,
            missing_fields=() if source_timestamp is not None else ("source_timestamp",),
            oldest_source_timestamp=oldest_source_timestamp,
        )

    def get_account_summary(self) -> AccountSummaryReadResult:
        started_at = _now_utc(self._clock)
        failure = (
            self._binding_failure()
            or self._capability_failure("account_read")
            or self._purpose_failure(ReadEndpoint.ACCOUNT_SUMMARY)
        )
        if failure is not None:
            completed_at = _now_utc(self._clock)
            return AccountSummaryReadResult(
                metadata=self._metadata(ReadEndpoint.ACCOUNT_SUMMARY, started_at, completed_at, None, 0, failure, False),
                summary=None,
            )
        try:
            request = self._request(ACCOUNT_SUMMARY_PATH, (("accountType", "UNIFIED"),))
        except ValueError:
            completed_at = _now_utc(self._clock)
            return AccountSummaryReadResult(
                metadata=self._metadata(
                    ReadEndpoint.ACCOUNT_SUMMARY,
                    started_at,
                    completed_at,
                    None,
                    0,
                    ReadFailure(ReadErrorCode.INVALID_REQUEST),
                    False,
                ),
                summary=None,
            )
        summary = None
        source_timestamp = None
        try:
            response = self._send(request)
            result, source_timestamp = self._successful_result(response)
            summary = _parse_wallet_balance(result)
        except _HttpEnvelopeError as exc:
            failure = _http_failure(exc.status_code)
        except _VenueEnvelopeError as exc:
            failure = _venue_failure(exc.ret_code)
        except _MalformedResponse:
            failure = ReadFailure(ReadErrorCode.MALFORMED_RESPONSE)
        except (ValueError, TypeError):
            failure = ReadFailure(ReadErrorCode.MALFORMED_RESPONSE)
        except ReadTransportError as exc:
            failure = _transport_failure(exc)
        except Exception:
            failure = ReadFailure(ReadErrorCode.STATE_UNKNOWN)
        completed_at = _now_utc(self._clock)
        if summary is not None and failure is None:
            failure = self._binding_failure()
        if summary is not None and failure is None:
            failure = self._freshness_failure(source_timestamp, source_timestamp, completed_at)
        return AccountSummaryReadResult(
            metadata=self._metadata(
                ReadEndpoint.ACCOUNT_SUMMARY,
                started_at,
                completed_at,
                source_timestamp,
                1 if summary is not None else 0,
                failure,
                summary is not None,
                oldest_source_timestamp=source_timestamp,
            ),
            summary=summary,
        )

    def list_positions(
        self, *, symbol: Optional[str] = None, settle_coin: Optional[str] = None
    ) -> PositionsReadResult:
        return self._read_positions(symbol=symbol, settle_coin=settle_coin)

    def list_open_orders(
        self, *, symbol: Optional[str] = None, settle_coin: Optional[str] = None
    ) -> OpenOrdersReadResult:
        return self._read_open_orders(symbol=symbol, settle_coin=settle_coin)

    def observe_account(self) -> AccountObservationResult:
        started_at = _now_utc(self._clock)
        summary = self.get_account_summary()
        positions = self.list_positions()
        orders = self.list_open_orders()
        completed_at = _now_utc(self._clock)
        # The envelope is a non-atomic historical snapshot. A registry change
        # that lands after the final endpoint read is surfaced explicitly
        # instead of being silently folded into a COMPLETE envelope.
        late_binding_failure = self._binding_failure()
        overall = aggregate_quality(
            (
                summary.metadata.data_quality,
                positions.metadata.data_quality,
                orders.metadata.data_quality,
            )
        )
        if late_binding_failure is not None and overall is ReadDataQuality.COMPLETE:
            overall = ReadDataQuality.PARTIAL
        return AccountObservationResult(
            account_id=self._binding.account_id,
            registry_revision=self._binding.registry_revision,
            record_revision=self._binding.record_revision,
            endpoint_profile=self._binding.endpoint_profile,
            started_at=started_at,
            completed_at=completed_at,
            summary=summary,
            positions=positions,
            open_orders=orders,
            overall_quality=overall,
            post_read_binding_failure=late_binding_failure,
        )

    def _send(self, request: ReadOnlyRequest) -> ReadOnlyResponse:
        if request.path not in _ENDPOINT_ALLOWLIST or request.method != "GET":
            raise ValueError("read request is not allowlisted")
        response = self._transport.send(request)
        if not isinstance(response, ReadOnlyResponse):
            raise _MalformedResponse()
        return response

    def _successful_result(self, response: ReadOnlyResponse) -> Tuple[Mapping[str, Any], Optional[datetime]]:
        if response.status_code != 200:
            raise _HttpEnvelopeError(response.status_code)
        result, source_timestamp = _parse_envelope(response.body)
        if self._binding.capabilities.server_time is not CapabilityState.SUPPORTED:
            # An unsupported or unknown server_time capability means the venue
            # timestamp must not be used as a freshness source.
            source_timestamp = None
        return result, source_timestamp

    def _read_positions(
        self, *, symbol: Optional[str], settle_coin: Optional[str]
    ) -> PositionsReadResult:
        started_at = _now_utc(self._clock)
        failure = (
            self._binding_failure()
            or self._capability_failure("positions_read")
            or self._purpose_failure(ReadEndpoint.POSITIONS)
        )
        if failure is not None:
            completed_at = _now_utc(self._clock)
            return PositionsReadResult(
                metadata=self._metadata(ReadEndpoint.POSITIONS, started_at, completed_at, None, 0, failure, False),
                positions=(),
            )
        base_query = self._scope_query(symbol, settle_coin)
        if base_query is None:
            completed_at = _now_utc(self._clock)
            return PositionsReadResult(
                metadata=self._metadata(
                    ReadEndpoint.POSITIONS,
                    started_at,
                    completed_at,
                    None,
                    0,
                    ReadFailure(ReadErrorCode.INVALID_REQUEST),
                    False,
                ),
                positions=(),
            )
        query = (("category", BYBIT_DEMO_V5_CATEGORY),) + base_query
        positions, failure, pages, source_timestamp, oldest_source = self._paginate(
            POSITIONS_PATH, query, _POSITION_PAGE_LIMIT, _parse_positions_page, lambda item: (
                item.category,
                item.symbol,
                item.position_idx,
            )
        )
        completed_at = _now_utc(self._clock)
        if failure is None:
            failure = self._binding_failure()
        if failure is None:
            failure = self._freshness_failure(oldest_source, source_timestamp, completed_at)
        return PositionsReadResult(
            metadata=self._metadata(
                ReadEndpoint.POSITIONS,
                started_at,
                completed_at,
                source_timestamp,
                pages,
                failure,
                bool(positions),
                oldest_source_timestamp=oldest_source,
            ),
            positions=tuple(positions),
        )

    def _read_open_orders(
        self, *, symbol: Optional[str], settle_coin: Optional[str]
    ) -> OpenOrdersReadResult:
        started_at = _now_utc(self._clock)
        failure = (
            self._binding_failure()
            or self._capability_failure("orders_read")
            or self._purpose_failure(ReadEndpoint.OPEN_ORDERS)
        )
        if failure is not None:
            completed_at = _now_utc(self._clock)
            return OpenOrdersReadResult(
                metadata=self._metadata(ReadEndpoint.OPEN_ORDERS, started_at, completed_at, None, 0, failure, False),
                orders=(),
            )
        base_query = self._scope_query(symbol, settle_coin)
        if base_query is None:
            completed_at = _now_utc(self._clock)
            return OpenOrdersReadResult(
                metadata=self._metadata(
                    ReadEndpoint.OPEN_ORDERS,
                    started_at,
                    completed_at,
                    None,
                    0,
                    ReadFailure(ReadErrorCode.INVALID_REQUEST),
                    False,
                ),
                orders=(),
            )
        query = (
            ("category", BYBIT_DEMO_V5_CATEGORY),
            ("openOnly", "0"),
        ) + base_query
        orders, failure, pages, source_timestamp, oldest_source = self._paginate(
            OPEN_ORDERS_PATH, query, _ORDER_PAGE_LIMIT, _parse_open_orders_page, lambda item: item.order_id
        )
        completed_at = _now_utc(self._clock)
        if failure is None:
            failure = self._binding_failure()
        if failure is None:
            failure = self._freshness_failure(oldest_source, source_timestamp, completed_at)
        return OpenOrdersReadResult(
            metadata=self._metadata(
                ReadEndpoint.OPEN_ORDERS,
                started_at,
                completed_at,
                source_timestamp,
                pages,
                failure,
                bool(orders),
                oldest_source_timestamp=oldest_source,
            ),
            orders=tuple(orders),
        )

    def _scope_query(
        self, symbol: Optional[str], settle_coin: Optional[str]
    ) -> Optional[Tuple[Tuple[str, str], ...]]:
        if symbol is not None:
            if not isinstance(symbol, str) or not symbol.strip():
                return None
            return (("symbol", symbol.strip().upper()),)
        target = BYBIT_DEMO_V5_DEFAULT_SETTLE_COIN if settle_coin is None else settle_coin
        if not isinstance(target, str) or not target.strip():
            return None
        return (("settleCoin", target.strip().upper()),)

    def _paginate(
        self,
        path: str,
        base_query: Tuple[Tuple[str, str], ...],
        page_limit: int,
        parser: Callable[[Mapping[str, Any]], Tuple[list, Optional[str]]],
        key_fn: Callable[[Any], Any],
    ) -> Tuple[
        list,
        Optional[ReadFailure],
        int,
        Optional[datetime],
        Optional[datetime],
    ]:
        items: list = []
        seen_keys: set = set()
        seen_cursors: set = set()
        cursor: Optional[str] = None
        requests_made = 0
        successful_pages = 0
        latest_source: Optional[datetime] = None
        oldest_source: Optional[datetime] = None
        failure: Optional[ReadFailure] = None
        while True:
            if requests_made >= self._max_pages:
                failure = ReadFailure(ReadErrorCode.PAGINATION_INCOMPLETE)
                break
            query = base_query + (("limit", str(page_limit)),)
            if cursor is not None:
                query = query + (("cursor", cursor),)
            try:
                request = self._request(path, query)
            except ValueError:
                failure = ReadFailure(ReadErrorCode.INVALID_REQUEST)
                break
            requests_made += 1
            try:
                response = self._send(request)
                result, source_timestamp = self._successful_result(response)
                page_items, next_cursor = parser(result)
            except _HttpEnvelopeError as exc:
                failure = _http_failure(exc.status_code)
                break
            except _VenueEnvelopeError as exc:
                failure = _venue_failure(exc.ret_code)
                break
            except _MalformedResponse:
                failure = ReadFailure(ReadErrorCode.MALFORMED_RESPONSE)
                break
            except (ValueError, TypeError):
                failure = ReadFailure(ReadErrorCode.MALFORMED_RESPONSE)
                break
            except ReadTransportError as exc:
                failure = _transport_failure(exc)
                break
            except Exception:
                failure = ReadFailure(ReadErrorCode.STATE_UNKNOWN)
                break
            successful_pages += 1
            if source_timestamp is not None:
                oldest_source = (
                    source_timestamp if oldest_source is None else min(oldest_source, source_timestamp)
                )
                latest_source = (
                    source_timestamp if latest_source is None else max(latest_source, source_timestamp)
                )
            for item in page_items:
                key = key_fn(item)
                if key in seen_keys:
                    failure = ReadFailure(ReadErrorCode.DUPLICATE_RECORD)
                    break
                seen_keys.add(key)
                items.append(item)
            if failure is not None:
                break
            late_binding_failure = self._binding_failure()
            if late_binding_failure is not None:
                failure = late_binding_failure
                break
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                failure = ReadFailure(ReadErrorCode.PAGINATION_INCOMPLETE)
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return items, failure, successful_pages, latest_source, oldest_source


class _HttpEnvelopeError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("venue returned a non-success HTTP status")


# The public read surface intentionally has no submit/cancel/close method.
