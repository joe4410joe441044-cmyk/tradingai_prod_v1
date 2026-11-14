"""Offline-only Hyro MCP read adapter; mock names are not an official API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Mapping, Protocol, Sequence

from backend.accounts.models import AccountId
from backend.execution.adapter_contracts import AdapterAccountSnapshot, OrderSide
from backend.execution.read_only_observations import (
    OpenOrderObservation, PositionObservation, ReadDataQuality, ReadEndpoint,
    ReadErrorCode, ReadFailure,
)

_SAFE_TOOL = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")

class HyroMcpReadOperation(str, Enum):
    ACCOUNT_IDENTITY = "ACCOUNT_IDENTITY"
    ACCOUNT_SUMMARY = "ACCOUNT_SUMMARY"
    POSITIONS = "POSITIONS"
    OPEN_ORDERS = "OPEN_ORDERS"
    CONDITIONAL_ORDERS = "CONDITIONAL_ORDERS"

@dataclass(frozen=True)
class HyroMcpToolProfile:
    account_identity: str
    account_summary: str
    positions: str
    open_orders: str
    conditional_orders: str

    def by_operation(self) -> dict[HyroMcpReadOperation, str]:
        return dict(zip(HyroMcpReadOperation, (
            self.account_identity, self.account_summary, self.positions,
            self.open_orders, self.conditional_orders,
        )))

    def __post_init__(self) -> None:
        names = tuple(self.by_operation().values())
        if len(set(names)) != len(names) or any(not _SAFE_TOOL.fullmatch(v) for v in names):
            raise ValueError("read tool names must be unique safe identifiers")

@dataclass(frozen=True)
class HyroMcpAccountScope:
    account_id: AccountId
    external_account_ref: str
    platform: str = "HYRO_PLATFORM"

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        if not self.external_account_ref or not self.platform:
            raise ValueError("account scope must be explicit")

class HyroMcpReadTransport(Protocol):
    def list_tools(self) -> Sequence[str]: ...
    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...

@dataclass(frozen=True)
class HyroMcpEndpointResult:
    endpoint: ReadEndpoint
    quality: ReadDataQuality
    value: object | None
    observed_at: datetime | None
    pages_fetched: int
    page_complete: bool
    failure: ReadFailure | None

    @property
    def confirmed_empty(self) -> bool:
        return (self.quality is ReadDataQuality.COMPLETE and self.page_complete
                and isinstance(self.value, tuple) and not self.value)

@dataclass(frozen=True)
class HyroMcpObservation:
    account_id: AccountId
    identity: HyroMcpEndpointResult
    summary: HyroMcpEndpointResult
    positions: HyroMcpEndpointResult
    open_orders: HyroMcpEndpointResult
    conditional_orders: HyroMcpEndpointResult

    @property
    def overall_quality(self) -> ReadDataQuality:
        values = [getattr(self, name).quality for name in
                  ("identity", "summary", "positions", "open_orders", "conditional_orders")]
        if all(v is ReadDataQuality.COMPLETE for v in values): return ReadDataQuality.COMPLETE
        if all(v is ReadDataQuality.FAILED for v in values): return ReadDataQuality.FAILED
        if any(v in (ReadDataQuality.FAILED, ReadDataQuality.PARTIAL) for v in values):
            return ReadDataQuality.PARTIAL
        return ReadDataQuality.STALE

class HyroMcpReadAdapter:
    def __init__(self, transport: HyroMcpReadTransport, *, tools: HyroMcpToolProfile,
                 maximum_age: timedelta = timedelta(minutes=5), maximum_pages: int = 100) -> None:
        if not isinstance(tools, HyroMcpToolProfile):
            raise TypeError("tools must be HyroMcpToolProfile")
        self.transport, self.tools = transport, tools
        if maximum_age <= timedelta(0) or maximum_pages < 1: raise ValueError("invalid read bounds")
        self.maximum_age, self.maximum_pages = maximum_age, maximum_pages

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(self.tools.by_operation().values())

    def invoke_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if name not in self.allowed_tool_names:
            raise PermissionError("MCP_TOOL_NOT_IN_READ_ALLOWLIST")
        return self.transport.call_tool(name, arguments)

    def read(self, scope: HyroMcpAccountScope, *, now: datetime | None = None) -> HyroMcpObservation:
        current = _utc(now or datetime.now(timezone.utc)); advertised = frozenset(self.transport.list_tools())
        identity = self._single(scope, advertised, current, HyroMcpReadOperation.ACCOUNT_IDENTITY)
        if identity.quality is ReadDataQuality.FAILED:
            failed = lambda ep: self._failed(ep, ReadErrorCode.INVALID_BINDING)
            return HyroMcpObservation(scope.account_id, identity, failed(ReadEndpoint.ACCOUNT_SUMMARY),
                failed(ReadEndpoint.POSITIONS), failed(ReadEndpoint.OPEN_ORDERS),
                failed(ReadEndpoint.CONDITIONAL_ORDERS))
        return HyroMcpObservation(scope.account_id, identity,
            self._single(scope, advertised, current, HyroMcpReadOperation.ACCOUNT_SUMMARY),
            self._collection(scope, advertised, current, HyroMcpReadOperation.POSITIONS),
            self._collection(scope, advertised, current, HyroMcpReadOperation.OPEN_ORDERS),
            self._collection(scope, advertised, current, HyroMcpReadOperation.CONDITIONAL_ORDERS))

    def _call(self, scope, advertised, operation, cursor=None):
        name = self.tools.by_operation()[operation]
        if name not in advertised: return ReadFailure(ReadErrorCode.UNSUPPORTED_CAPABILITY)
        args = {"account_ref": scope.external_account_ref}
        if cursor is not None: args["cursor"] = cursor
        try: result = self.invoke_tool(name, args)
        except PermissionError: return ReadFailure(ReadErrorCode.PERMISSION_DENIED)
        except Exception: return ReadFailure(ReadErrorCode.TRANSPORT_FAILURE)
        return result if isinstance(result, Mapping) else ReadFailure(ReadErrorCode.MALFORMED_RESPONSE)

    def _scope_time(self, scope, response):
        if response.get("account_ref") != scope.external_account_ref or response.get("platform") != scope.platform:
            raise ValueError("account scope mismatch")
        return _timestamp(response.get("observed_at"))

    def _single(self, scope, advertised, now, operation):
        endpoint = ReadEndpoint.ACCOUNT_IDENTITY if operation is HyroMcpReadOperation.ACCOUNT_IDENTITY else ReadEndpoint.ACCOUNT_SUMMARY
        response = self._call(scope, advertised, operation)
        if isinstance(response, ReadFailure): return self._failed(endpoint, response.code)
        try:
            at = self._scope_time(scope, response)
            if operation is HyroMcpReadOperation.ACCOUNT_IDENTITY:
                value = {"account_scope_matched": True}
            else:
                missing = tuple(k for k in ("balance", "equity") if response.get(k) is None)
                value = AdapterAccountSnapshot(scope.account_id, at, "HYRO_MCP_MOCK_NOT_OFFICIAL",
                    _text(response.get("currency")), _dec_opt(response.get("balance")),
                    _dec_opt(response.get("equity")), _dec_opt(response.get("available_balance")),
                    _count(response.get("open_position_count")), _count(response.get("open_order_count")), missing)
                if missing:
                    return HyroMcpEndpointResult(endpoint, ReadDataQuality.PARTIAL, value, at, 1, True,
                                                 ReadFailure(ReadErrorCode.PARTIAL_DATA))
        except (TypeError, ValueError): return self._failed(endpoint, ReadErrorCode.INVALID_BINDING if operation is HyroMcpReadOperation.ACCOUNT_IDENTITY else ReadErrorCode.MALFORMED_RESPONSE)
        return self._quality(endpoint, value, at, now, 1, True)

    def _collection(self, scope, advertised, now, operation):
        endpoint = {HyroMcpReadOperation.POSITIONS: ReadEndpoint.POSITIONS,
                    HyroMcpReadOperation.OPEN_ORDERS: ReadEndpoint.OPEN_ORDERS,
                    HyroMcpReadOperation.CONDITIONAL_ORDERS: ReadEndpoint.CONDITIONAL_ORDERS}[operation]
        items, cursor, pages, newest = [], None, 0, None
        while pages < self.maximum_pages:
            response = self._call(scope, advertised, operation, cursor)
            if isinstance(response, ReadFailure):
                return HyroMcpEndpointResult(endpoint, ReadDataQuality.PARTIAL if pages else ReadDataQuality.FAILED,
                    tuple(items) if pages else None, newest, pages, False,
                    ReadFailure(ReadErrorCode.PAGINATION_INCOMPLETE if pages else response.code))
            try:
                at = self._scope_time(scope, response); newest = max(v for v in (newest, at) if v)
                raw = response.get("items")
                if not isinstance(raw, list): raise ValueError("items absent")
                items.extend(_item(operation, x) for x in raw); pages += 1
                if response.get("page_complete") is True:
                    if response.get("next_cursor") not in (None, ""): raise ValueError("cursor after complete")
                    return self._quality(endpoint, tuple(items), newest, now, pages, True)
                next_cursor = response.get("next_cursor")
                if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor: raise ValueError("bad cursor")
                cursor = next_cursor
            except (TypeError, ValueError):
                return HyroMcpEndpointResult(endpoint, ReadDataQuality.PARTIAL if items else ReadDataQuality.FAILED,
                    tuple(items) if items else None, newest, pages, False,
                    ReadFailure(ReadErrorCode.PAGINATION_INCOMPLETE if items else ReadErrorCode.MALFORMED_RESPONSE))
        return HyroMcpEndpointResult(endpoint, ReadDataQuality.PARTIAL, tuple(items), newest, pages, False,
                                     ReadFailure(ReadErrorCode.PAGINATION_INCOMPLETE))

    def _quality(self, endpoint, value, at, now, pages, complete):
        if at > now + timedelta(minutes=1) or now - at > self.maximum_age:
            return HyroMcpEndpointResult(endpoint, ReadDataQuality.STALE, value, at, pages, complete,
                                         ReadFailure(ReadErrorCode.STALE_DATA))
        return HyroMcpEndpointResult(endpoint, ReadDataQuality.COMPLETE, value, at, pages, complete, None)

    @staticmethod
    def _failed(endpoint, code):
        return HyroMcpEndpointResult(endpoint, ReadDataQuality.FAILED, None, None, 0, False, ReadFailure(code))

def _item(operation, raw):
    if not isinstance(raw, Mapping): raise ValueError("invalid item")
    if operation is HyroMcpReadOperation.POSITIONS:
        size = _dec(raw.get("size")); side = None if size == 0 else OrderSide(_text(raw.get("side")).upper())
        return PositionObservation(_text(raw.get("category", "linear")), _text(raw.get("symbol")),
            int(raw.get("position_idx", 0)), side, size, _dec_opt(raw.get("avg_price")),
            _dec_opt(raw.get("mark_price")), _dec_opt(raw.get("unrealised_pnl")),
            _dec_opt(raw.get("position_value")), _dec_opt(raw.get("leverage")))
    status = "Untriggered" if operation is HyroMcpReadOperation.CONDITIONAL_ORDERS else _text(raw.get("status"))
    return OpenOrderObservation(_text(raw.get("category", "linear")), _text(raw.get("order_id")),
        raw.get("client_order_id"), _text(raw.get("symbol")), OrderSide(_text(raw.get("side")).upper()),
        raw.get("order_type"), status, _dec_opt(raw.get("price")), _dec(raw.get("qty")),
        _dec_opt(raw.get("leaves_qty")), _dec_opt(raw.get("cum_exec_qty")),
        _dec_opt(raw.get("cum_exec_value")), _dec_opt(raw.get("avg_price")), raw.get("reduce_only"),
        raw.get("position_idx"), _time_opt(raw.get("created_at")), _time_opt(raw.get("updated_at")))

def _text(v):
    if not isinstance(v, str) or not v.strip(): raise ValueError("required text absent")
    return v.strip()
def _dec(v):
    if not isinstance(v, str): raise ValueError("decimal must be text")
    out = Decimal(v)
    if not out.is_finite(): raise ValueError("decimal not finite")
    return out
def _dec_opt(v): return None if v is None else _dec(v)
def _count(v):
    if v is None: return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0: raise ValueError("bad count")
    return v
def _utc(v):
    if not isinstance(v, datetime) or v.tzinfo is None: raise TypeError("aware datetime required")
    return v.astimezone(timezone.utc)
def _timestamp(v):
    if not isinstance(v, str): raise ValueError("timestamp absent")
    return _utc(datetime.fromisoformat(v.replace("Z", "+00:00")))
def _time_opt(v): return None if v is None else _timestamp(v)
