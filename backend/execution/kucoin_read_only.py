# -*- coding: utf-8 -*-
"""KuCoin Futures READ-ONLY readiness verification.

This module only wraps the existing signer/public client.  Every request must
be an allow-listed GET.  It never creates, cancels, modifies, closes, transfers
or changes leverage, and it never mutates runtime order authority.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import requests

from backend.execution.kucoin_trade import KucoinTradeClient
from backend.market.kucoin_futures_public import KucoinFuturesPublicClient
from backend.utils.log_buffer import logger


READ_ONLY_METHODS = frozenset({"GET"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

PUBLIC_ENDPOINT_PREFIXES = (
    "/api/v1/contracts/",
    "/api/v1/ticker",
    "/api/v1/allTickers",
)
PRIVATE_ENDPOINT_PREFIXES = (
    "/api/v1/account-overview",
    "/api/v1/positions",
    "/api/v1/orders",
    "/api/v1/stopOrders",
    "/api/v2/position/getMarginMode",
)
ALLOWED_ENDPOINT_PREFIXES = PUBLIC_ENDPOINT_PREFIXES + PRIVATE_ENDPOINT_PREFIXES

DEFAULT_TIMEOUT = 10.0
MAX_TIMEOUT = 15.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_STALE = "STALE"
STATUS_MISSING_FIELDS = "MISSING_FIELDS"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
STATUS_BLOCKED = "BLOCKED"

_FRESHNESS_TIMESTAMP_KEYS = ("ts", "timestamp", "updatedAt", "lastSync", "createdAt")


class ReadOnlyViolation(RuntimeError):
    """Raised when a caller attempts a non-read-only operation."""


class ReadOnlyRateLimited(RuntimeError):
    """Raised after all bounded retries observed HTTP 429."""


def _endpoint_path(url):
    if not isinstance(url, str) or not url:
        raise ReadOnlyViolation("ENDPOINT_REQUIRED")
    return urlsplit(url).path


def _allowed_path(path):
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in ALLOWED_ENDPOINT_PREFIXES
    )


class ReadOnlyTransport:
    """GET-only transport enforcing the endpoint allow-list before any call."""

    def __init__(
        self,
        session=None,
        *,
        max_retries=DEFAULT_MAX_RETRIES,
        backoff_seconds=DEFAULT_BACKOFF_SECONDS,
        max_timeout=MAX_TIMEOUT,
        sleep=None,
    ):
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not isinstance(backoff_seconds, (int, float)) or backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        if not isinstance(max_timeout, (int, float)) or max_timeout <= 0:
            raise ValueError("max_timeout must be positive")
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = float(backoff_seconds)
        self.max_timeout = float(max_timeout)
        self.sleep = sleep or time.sleep
        self.calls = []
        self.write_attempts = 0
        self.rate_limited = False

    def _bound_timeout(self, timeout):
        if timeout is None:
            return DEFAULT_TIMEOUT
        try:
            value = float(timeout)
        except (TypeError, ValueError):
            raise ReadOnlyViolation("INVALID_TIMEOUT") from None
        if value <= 0:
            raise ReadOnlyViolation("INVALID_TIMEOUT")
        return min(value, self.max_timeout)

    def _delay(self, attempt):
        if self.backoff_seconds:
            self.sleep(self.backoff_seconds * (2 ** attempt))

    def _validate(self, method, url):
        verb = str(method or "").upper()
        if verb not in READ_ONLY_METHODS:
            self.write_attempts += 1
            raise ReadOnlyViolation("WRITE_METHOD_FORBIDDEN")
        path = _endpoint_path(url)
        if not _allowed_path(path):
            raise ReadOnlyViolation("ENDPOINT_NOT_ALLOWLISTED")
        return verb, path

    def get(self, url, timeout=None, **kwargs):
        verb, path = self._validate("GET", url)
        bounded_timeout = self._bound_timeout(timeout)
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, timeout=bounded_timeout, **kwargs
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._delay(attempt)
                    continue
                raise
            status = getattr(response, "status_code", None)
            if status == 429:
                self.rate_limited = True
                if attempt < self.max_retries:
                    self._delay(attempt)
                    continue
                self.calls.append((verb, path, bounded_timeout, attempt + 1, status))
                raise ReadOnlyRateLimited("KUCOIN_RATE_LIMITED")
            self.calls.append((verb, path, bounded_timeout, attempt + 1, status))
            return response
        raise last_error

    def _reject_write(self, method, url=None):
        self.write_attempts += 1
        raise ReadOnlyViolation("WRITE_METHOD_FORBIDDEN")

    def post(self, url=None, **kwargs):
        self._reject_write("POST", url)

    def put(self, url=None, **kwargs):
        self._reject_write("PUT", url)

    def patch(self, url=None, **kwargs):
        self._reject_write("PATCH", url)

    def delete(self, url=None, **kwargs):
        self._reject_write("DELETE", url)

    def request(self, method, url, **kwargs):
        if str(method or "").upper() != "GET":
            self._reject_write(method, url)
        return self.get(url, **kwargs)


def _number(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _timestamp_value(value):
    number = _number(value)
    if number is None:
        return None
    if number > 100000000000:
        number = number / 1000.0
    return number


def _observation_time(payload):
    if not isinstance(payload, dict):
        return None
    for key in _FRESHNESS_TIMESTAMP_KEYS:
        if key in payload:
            result = _timestamp_value(payload.get(key))
            if result is not None:
                return result
    return None


def _missing_keys(payload, keys):
    if not isinstance(payload, dict):
        return list(keys)
    return [key for key in keys if payload.get(key) in (None, "")]


class KucoinReadOnlyVerifier:
    """Read-only readiness probes over the existing KuCoin clients."""

    def __init__(
        self,
        trade_client,
        *,
        public_client=None,
        transport=None,
        clock=None,
        max_age_seconds=60.0,
    ):
        if not isinstance(trade_client, KucoinTradeClient):
            raise TypeError("KucoinTradeClient required")
        read_only_transport = transport or trade_client.session
        if not isinstance(read_only_transport, ReadOnlyTransport):
            raise TypeError("ReadOnlyTransport required")
        if not isinstance(max_age_seconds, (int, float)) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.trade = trade_client
        self.transport = read_only_transport
        self.public = public_client or KucoinFuturesPublicClient(
            session=read_only_transport, timeout=DEFAULT_TIMEOUT
        )
        if getattr(self.public, "session", None) is not read_only_transport:
            self.public.session = read_only_transport
        self.clock = clock or time.time
        self.max_age_seconds = float(max_age_seconds)

    @classmethod
    def from_credentials(
        cls,
        *,
        api_key,
        api_secret,
        passphrase,
        session=None,
        sleep=None,
        clock=None,
        max_age_seconds=60.0,
        max_retries=DEFAULT_MAX_RETRIES,
        backoff_seconds=DEFAULT_BACKOFF_SECONDS,
    ):
        transport = ReadOnlyTransport(
            session=session,
            sleep=sleep,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
        )
        trade = KucoinTradeClient(
            api_key=api_key, api_secret=api_secret, passphrase=passphrase
        )
        trade.session = transport
        public = KucoinFuturesPublicClient(
            session=transport, timeout=DEFAULT_TIMEOUT
        )
        return cls(
            trade,
            public_client=public,
            transport=transport,
            clock=clock,
            max_age_seconds=max_age_seconds,
        )

    def _now(self):
        return float(self.clock())

    def _freshness(self, observed_at):
        if observed_at is None:
            return None
        age = self._now() - observed_at
        return 0 <= age <= self.max_age_seconds

    def _result(
        self,
        category,
        status,
        *,
        data=None,
        reason=None,
        observed_at=None,
        fresh=None,
        source=None,
    ):
        return {
            "category": category,
            "status": status,
            "readOnly": True,
            "source": source,
            "observedAt": observed_at,
            "fresh": fresh,
            "reason": reason,
            "data": data if isinstance(data, dict) else {},
        }

    def _classify_error(self, category, error):
        status_code = getattr(error, "status_code", None)
        name = type(error).__name__.lower()
        if isinstance(error, ReadOnlyRateLimited) or self.transport.rate_limited:
            return self._result(category, STATUS_RATE_LIMITED, reason="KUCOIN_RATE_LIMITED")
        if isinstance(error, ReadOnlyViolation):
            return self._result(category, STATUS_BLOCKED, reason=str(error))
        if status_code in (401, 403):
            return self._result(
                category, STATUS_AUTHENTICATION_FAILED, reason="KUCOIN_AUTHENTICATION_FAILED"
            )
        if isinstance(error, (requests.exceptions.Timeout, TimeoutError)) or "timeout" in name:
            return self._result(category, STATUS_UNAVAILABLE, reason="KUCOIN_READ_TIMEOUT")
        if status_code is not None or isinstance(error, requests.exceptions.RequestException):
            return self._result(category, STATUS_UNAVAILABLE, reason="KUCOIN_READ_HTTP_ERROR")
        return self._result(category, STATUS_UNAVAILABLE, reason="KUCOIN_READ_FAILED")

    def _raw_positions(self, positions=None):
        if positions is not None:
            return positions
        data = self.trade.private_get("/api/v1/positions")
        if not isinstance(data, list):
            raise ValueError("KUCOIN_POSITION_RESPONSE_INVALID")
        return data

    def public_market_read(self):
        try:
            tickers = self.public.get_all_tickers()
        except Exception as error:
            return self._classify_error("PUBLIC_MARKET", error)
        if not tickers:
            return self._result(
                "PUBLIC_MARKET", STATUS_PARTIAL, reason="KUCOIN_PUBLIC_DATA_EMPTY"
            )
        return self._result(
            "PUBLIC_MARKET",
            STATUS_OK,
            data={"tickerCount": len(tickers)},
            source="KUCOIN_PUBLIC_MARKET",
            observed_at=self._now(),
        )

    def account_read(self):
        try:
            overview = self.trade.get_account_overview()
        except Exception as error:
            return self._classify_error("ACCOUNT", error)
        if not isinstance(overview, dict):
            return self._result(
                "ACCOUNT", STATUS_PARTIAL, reason="KUCOIN_ACCOUNT_RESPONSE_INVALID"
            )
        missing = _missing_keys(overview, ("equity", "availableBalance"))
        observed_at = _observation_time(overview)
        fresh = self._freshness(observed_at)
        data = {
            "currency": overview.get("currency"),
            "equity": _number(overview.get("equity")),
            "availableBalance": _number(overview.get("availableBalance")),
            "balance": _number(overview.get("balance")),
            "marginUsed": _number(overview.get("marginUsed")),
            "marginRatio": _number(overview.get("marginRatio")),
        }
        if overview.get("source") != "KUCOIN_FUTURES_READ_ONLY":
            return self._result(
                "ACCOUNT",
                STATUS_PARTIAL,
                data=data,
                reason="KUCOIN_ACCOUNT_SOURCE_INVALID",
                observed_at=observed_at,
                fresh=fresh,
            )
        if missing:
            return self._result(
                "ACCOUNT",
                STATUS_MISSING_FIELDS,
                data=data,
                reason="KUCOIN_ACCOUNT_MISSING_FIELDS",
                observed_at=observed_at,
                fresh=fresh,
            )
        if fresh is False:
            return self._result(
                "ACCOUNT",
                STATUS_STALE,
                data=data,
                reason="KUCOIN_ACCOUNT_STALE",
                observed_at=observed_at,
                fresh=fresh,
            )
        return self._result(
            "ACCOUNT",
            STATUS_OK,
            data=data,
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def position_read(self, symbol=None, *, positions=None):
        try:
            positions = self._raw_positions(positions)
        except Exception as error:
            return self._classify_error("POSITION", error)
        active = []
        observed_times = []
        for item in positions:
            if not isinstance(item, dict):
                return self._result(
                    "POSITION", STATUS_PARTIAL, reason="KUCOIN_POSITION_ITEM_INVALID"
                )
            quantity = _number(item.get("currentQty"))
            if quantity is None:
                return self._result(
                    "POSITION", STATUS_MISSING_FIELDS, reason="KUCOIN_POSITION_QTY_MISSING"
                )
            observed_times.append(_observation_time(item))
            if quantity == 0:
                continue
            active.append(
                {
                    "symbol": item.get("symbol"),
                    "qty": abs(quantity),
                    "side": "BUY" if quantity > 0 else "SELL",
                    "entryPrice": _number(item.get("avgEntryPrice")),
                    "markPrice": _number(item.get("markPrice")),
                    "liquidationPrice": _number(item.get("liquidationPrice")),
                    "leverage": _number(item.get("realLeverage") or item.get("leverage")),
                    "marginMode": item.get("marginMode"),
                    "unrealisedPnl": _number(item.get("unrealisedPnl")),
                }
            )
        if symbol:
            wanted = str(symbol).strip().upper()
            active = [item for item in active if str(item.get("symbol") or "").upper() == wanted]
        observed_at = max((item for item in observed_times if item), default=None)
        fresh = self._freshness(observed_at)
        status = STATUS_STALE if fresh is False else STATUS_OK
        return self._result(
            "POSITION",
            status,
            data={
                "state": "FLAT" if not active else "OPEN",
                "count": len(active),
                "positions": active,
            },
            reason="KUCOIN_POSITION_STALE" if status == STATUS_STALE else None,
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def open_order_read(self, symbol=None):
        try:
            result = self.trade.get_open_orders(symbol)
        except Exception as error:
            return self._classify_error("OPEN_ORDERS", error)
        if not isinstance(result, dict):
            return self._result(
                "OPEN_ORDERS", STATUS_PARTIAL, reason="KUCOIN_OPEN_ORDER_RESPONSE_INVALID"
            )
        if result.get("success") is not True:
            return self._result(
                "OPEN_ORDERS",
                STATUS_UNAVAILABLE,
                data={"count": 0, "orders": []},
                reason="KUCOIN_OPEN_ORDER_READ_FAILED",
            )
        orders = result.get("orders")
        count = result.get("count")
        if not isinstance(orders, list) or type(count) is not int:
            return self._result(
                "OPEN_ORDERS", STATUS_PARTIAL, reason="KUCOIN_OPEN_ORDER_RESPONSE_INVALID"
            )
        if count != len(orders):
            return self._result(
                "OPEN_ORDERS",
                STATUS_PARTIAL,
                data={"count": len(orders), "orders": orders},
                reason="KUCOIN_OPEN_ORDER_COUNT_MISMATCH",
            )
        observed_at = _observation_time(result)
        fresh = self._freshness(observed_at)
        status = STATUS_STALE if fresh is False else STATUS_OK
        return self._result(
            "OPEN_ORDERS",
            status,
            data={"state": "NONE" if count == 0 else "EXISTS", "count": count, "orders": orders},
            reason="KUCOIN_OPEN_ORDER_STALE" if status == STATUS_STALE else None,
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def conditional_order_read(self, symbol=None):
        endpoint = "/api/v1/stopOrders?status=active"
        if symbol:
            endpoint += "&symbol=" + str(symbol).strip().upper()
        try:
            payload = self.trade.private_get(endpoint)
        except Exception as error:
            return self._classify_error("CONDITIONAL_ORDERS", error)
        if isinstance(payload, dict):
            items = payload.get("items")
            if items is None:
                items = payload.get("list")
        elif isinstance(payload, list):
            items = payload
        else:
            items = None
        if not isinstance(items, list):
            return self._result(
                "CONDITIONAL_ORDERS",
                STATUS_PARTIAL,
                reason="KUCOIN_CONDITIONAL_ORDER_RESPONSE_INVALID",
            )
        observed_at = _observation_time(payload if isinstance(payload, dict) else {})
        fresh = self._freshness(observed_at)
        status = STATUS_STALE if fresh is False else STATUS_OK
        return self._result(
            "CONDITIONAL_ORDERS",
            status,
            data={"state": "NONE" if not items else "EXISTS", "count": len(items), "orders": items},
            reason="KUCOIN_CONDITIONAL_ORDER_STALE" if status == STATUS_STALE else None,
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def contract_read(self, symbol):
        try:
            rules = self.trade.get_symbol_rules(symbol)
        except Exception as error:
            return self._classify_error("CONTRACT", error)
        if not isinstance(rules, dict):
            return self._result(
                "CONTRACT", STATUS_PARTIAL, reason="KUCOIN_CONTRACT_RESPONSE_INVALID"
            )
        required = ("min_size", "qty_step", "multiplier", "max_leverage")
        missing = _missing_keys(rules, required)
        data = {key: rules.get(key) for key in required + (
            "symbol", "status", "settle_currency", "quote_currency",
            "max_size", "taker_fee_rate",
        )}
        if missing:
            return self._result(
                "CONTRACT",
                STATUS_MISSING_FIELDS,
                data=data,
                reason="KUCOIN_CONTRACT_MISSING_FIELDS",
            )
        return self._result(
            "CONTRACT",
            STATUS_OK,
            data=data,
            observed_at=self._now(),
            fresh=True,
            source="KUCOIN_PUBLIC_CONTRACT",
        )

    def margin_mode_read(self, symbol):
        try:
            authority = self.trade.get_margin_mode(symbol)
        except Exception as error:
            return self._classify_error("MARGIN_MODE", error)
        if not isinstance(authority, dict):
            return self._result(
                "MARGIN_MODE", STATUS_PARTIAL, reason="KUCOIN_MARGIN_MODE_RESPONSE_INVALID"
            )
        data = {
            "symbol": authority.get("symbol"),
            "marginMode": authority.get("marginMode"),
            "available": authority.get("available"),
            "reason": authority.get("reason"),
        }
        if authority.get("available") is not True:
            return self._result(
                "MARGIN_MODE",
                STATUS_UNAVAILABLE,
                data=data,
                reason=authority.get("reason") or "KUCOIN_MARGIN_MODE_UNAVAILABLE",
            )
        observed_at = _timestamp_value(authority.get("updatedAt"))
        fresh = self._freshness(observed_at)
        status = STATUS_STALE if fresh is False else STATUS_OK
        return self._result(
            "MARGIN_MODE",
            status,
            data=data,
            reason="KUCOIN_MARGIN_MODE_STALE" if status == STATUS_STALE else None,
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_V2_POSITION_MARGIN_MODE",
        )

    def leverage_liquidation_read(self, symbol, *, positions=None):
        try:
            positions = self._raw_positions(positions)
        except Exception as error:
            return self._classify_error("LEVERAGE_LIQUIDATION", error)
        wanted = str(symbol).strip().upper()
        matched = None
        for item in positions:
            if isinstance(item, dict) and str(item.get("symbol") or "").upper() == wanted:
                matched = item
                break
        if matched is None:
            return self._result(
                "LEVERAGE_LIQUIDATION",
                STATUS_OK,
                data={
                    "position": "FLAT",
                    "leverage": None,
                    "liquidationPrice": None,
                    "markPrice": None,
                    "marginMode": None,
                    "liquidationDistancePercent": None,
                },
                source="KUCOIN_FUTURES_READ_ONLY",
            )
        mark_price = _number(matched.get("markPrice"))
        liquidation_price = _number(matched.get("liquidationPrice"))
        distance = None
        if mark_price and liquidation_price and mark_price > 0:
            distance = abs(mark_price - liquidation_price) / mark_price * 100.0
        observed_at = _observation_time(matched)
        fresh = self._freshness(observed_at)
        if fresh is False:
            return self._result(
                "LEVERAGE_LIQUIDATION",
                STATUS_STALE,
                data={
                    "position": "OPEN",
                    "leverage": _number(matched.get("realLeverage") or matched.get("leverage")),
                    "liquidationPrice": liquidation_price,
                    "markPrice": mark_price,
                    "marginMode": matched.get("marginMode"),
                    "liquidationDistancePercent": distance,
                },
                reason="KUCOIN_LEVERAGE_LIQUIDATION_STALE",
                observed_at=observed_at,
                fresh=fresh,
            )
        return self._result(
            "LEVERAGE_LIQUIDATION",
            STATUS_OK,
            data={
                "position": "OPEN",
                "leverage": _number(matched.get("realLeverage") or matched.get("leverage")),
                "liquidationPrice": liquidation_price,
                "markPrice": mark_price,
                "marginMode": matched.get("marginMode"),
                "liquidationDistancePercent": distance,
            },
            observed_at=observed_at,
            fresh=fresh,
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def protective_stop_read(self, symbol, *, conditional=None):
        conditional = conditional or self.conditional_order_read(symbol)
        if conditional["status"] not in (STATUS_OK, STATUS_STALE):
            return self._result(
                "PROTECTIVE_STOP",
                conditional["status"],
                data={"count": 0, "stops": []},
                reason=conditional.get("reason"),
                observed_at=conditional.get("observedAt"),
                fresh=conditional.get("fresh"),
            )
        stops = []
        for order in conditional["data"].get("orders") or []:
            if not isinstance(order, dict):
                continue
            if order.get("reduceOnly") is not True:
                continue
            if order.get("stopPrice") in (None, ""):
                continue
            stops.append(
                {
                    "orderId": order.get("id") or order.get("orderId"),
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "size": order.get("size") or order.get("qty"),
                    "stopPrice": order.get("stopPrice"),
                    "reduceOnly": True,
                }
            )
        return self._result(
            "PROTECTIVE_STOP",
            conditional["status"],
            data={"state": "PRESENT" if stops else "NONE", "count": len(stops), "stops": stops},
            reason=conditional.get("reason"),
            observed_at=conditional.get("observedAt"),
            fresh=conditional.get("fresh"),
            source="KUCOIN_FUTURES_READ_ONLY",
        )

    def verify(self, symbol):
        live_order_allowed_before = bool(self.trade.live_order_allowed)
        runtime_submission_allowed_before = self.trade.runtime_submission_allowed
        intent_path_before = getattr(self.trade, "order_intent_path", None)
        write_attempts_before = self.transport.write_attempts

        try:
            raw_positions = self._raw_positions()
            position_error = None
        except Exception as error:
            raw_positions = None
            position_error = error

        if position_error is None:
            position_check = self.position_read(symbol, positions=raw_positions)
            leverage_check = self.leverage_liquidation_read(
                symbol, positions=raw_positions
            )
        else:
            position_check = self._classify_error("POSITION", position_error)
            leverage_check = self._classify_error(
                "LEVERAGE_LIQUIDATION", position_error
            )

        conditional_check = self.conditional_order_read(symbol)

        checks = {
            "publicMarket": self.public_market_read(),
            "account": self.account_read(),
            "position": position_check,
            "openOrders": self.open_order_read(symbol),
            "conditionalOrders": conditional_check,
            "contract": self.contract_read(symbol),
            "marginMode": self.margin_mode_read(symbol),
            "leverageLiquidation": leverage_check,
            "protectiveStop": self.protective_stop_read(
                symbol, conditional=conditional_check
            ),
        }

        live_order_allowed_after = bool(self.trade.live_order_allowed)
        runtime_submission_allowed_after = self.trade.runtime_submission_allowed
        intent_path_after = getattr(self.trade, "order_intent_path", None)
        write_attempts_after = self.transport.write_attempts
        authority_unchanged = (
            live_order_allowed_before == live_order_allowed_after
            and runtime_submission_allowed_before == runtime_submission_allowed_after
            and intent_path_before == intent_path_after
        )
        write_attempts = write_attempts_after - write_attempts_before

        statuses = {name: check["status"] for name, check in checks.items()}
        if write_attempts:
            overall = STATUS_BLOCKED
        elif not authority_unchanged:
            overall = STATUS_BLOCKED
        elif any(status not in (STATUS_OK, STATUS_STALE) for status in statuses.values()):
            overall = STATUS_PARTIAL
        elif any(status == STATUS_STALE for status in statuses.values()):
            overall = STATUS_STALE
        else:
            overall = STATUS_OK

        return {
            "category": "READ_ONLY_READINESS",
            "status": overall,
            "readOnly": True,
            "symbol": str(symbol),
            "checks": checks,
            "statuses": statuses,
            "safety": {
                "writeAttempts": write_attempts,
                "orderMutations": 0,
                "runtimeAuthorityMutation": not authority_unchanged,
                "intentStoreTouched": intent_path_before != intent_path_after,
                "liveOrderAllowed": live_order_allowed_after,
                "runtimeSubmissionAllowed": runtime_submission_allowed_after,
            },
            "observedAt": self._now(),
        }

    def redacted_summary(self, result):
        lines = [
            "KUCOIN_READ_ONLY category=%s status=%s"
            % (result.get("category"), result.get("status"))
        ]
        for name, status in sorted((result.get("statuses") or {}).items()):
            lines.append("KUCOIN_READ_ONLY check=%s status=%s" % (name, status))
        text = "\n".join(lines)
        logger.info(text)
        return text
