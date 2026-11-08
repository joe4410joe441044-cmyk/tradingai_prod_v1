# -*- coding: utf-8 -*-
"""Offline READ-ONLY boundary tests for KuCoin Futures readiness probes."""

import json
import os
import time

import pytest
import requests

from backend.execution.kucoin_read_only import (
    ALLOWED_ENDPOINT_PREFIXES,
    STATUS_AUTHENTICATION_FAILED,
    STATUS_MISSING_FIELDS,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_RATE_LIMITED,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    KucoinReadOnlyVerifier,
    ReadOnlyRateLimited,
    ReadOnlyTransport,
    ReadOnlyViolation,
)


API_KEY = "test-api-key-value"
API_SECRET = "test-api-secret-value"
PASSPHRASE = "test-passphrase-value"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code)

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, routes=None):
        self.routes = list((routes or {}).items())
        self.calls = []
        self.posts = []
        self.sleeps = []

    def get(self, url, timeout=None, headers=None, **kwargs):
        self.calls.append({"url": url, "timeout": timeout, "headers": headers})
        for fragment, handler in self.routes:
            if fragment in url:
                item = handler(url) if callable(handler) else handler
                if isinstance(item, list):
                    item = item.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        return default_response(url)

    def post(self, url=None, **kwargs):
        self.posts.append(url)
        return FakeResponse({"code": "200000", "data": {}})


def default_response(url):
    if "/api/v1/account-overview" in url:
        return FakeResponse({"code": "200000", "data": {
            "currency": "USDT", "accountEquity": "8.0", "availableBalance": "7.9",
            "marginBalance": "8.0", "positionMargin": "0", "orderMargin": "0",
            "riskRatio": "0.01", "unrealisedPNL": "0",
        }})
    if "/api/v1/positions" in url:
        return FakeResponse({"code": "200000", "data": []})
    if "/api/v1/stopOrders" in url:
        return FakeResponse({"code": "200000", "data": {"items": [], "totalPage": 1}})
    if "/api/v1/orders" in url:
        return FakeResponse({"code": "200000", "data": {
            "items": [], "totalPage": 1, "currentPage": 1,
        }})
    if "/api/v2/position/getMarginMode" in url:
        return FakeResponse({"code": "200000", "data": {"marginMode": "ISOLATED"}})
    if "/api/v1/contracts/" in url:
        return FakeResponse({"code": "200000", "data": {
            "symbol": "XRPUSDTM", "status": "Open", "settleCurrency": "USDT",
            "quoteCurrency": "USDT", "isInverse": False, "lotSize": 1,
            "multiplier": "1", "marketMaxOrderQty": "100000", "maxLeverage": 50,
            "takerFeeRate": "0.0006",
        }})
    if "/api/v1/allTickers" in url:
        return FakeResponse({"code": "200000", "data": [
            {"symbol": "XRPUSDTM", "price": "1.0"}
        ]})
    return FakeResponse({"code": "200000", "data": {}})


def build_verifier(routes=None, **kwargs):
    session = FakeSession(routes)
    verifier = KucoinReadOnlyVerifier.from_credentials(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=PASSPHRASE,
        session=session,
        sleep=lambda seconds: session.sleeps.append(seconds),
        **kwargs,
    )
    return verifier, session


def open_position(updated_at=None, **changes):
    payload = {
        "symbol": "XRPUSDTM",
        "currentQty": "1",
        "avgEntryPrice": "1.0",
        "markPrice": "1.1",
        "liquidationPrice": "0.5",
        "realLeverage": "3",
        "marginMode": "ISOLATED",
        "unrealisedPnl": "0.1",
        "updatedAt": int((updated_at if updated_at is not None else time.time()) * 1000),
    }
    payload.update(changes)
    return payload


def test_transport_allows_allowlisted_get():
    session = FakeSession()
    transport = ReadOnlyTransport(session=session)

    response = transport.get(
        "https://api-futures.kucoin.com/api/v1/positions", timeout=5
    )

    assert response.status_code == 200
    assert transport.calls == [("GET", "/api/v1/positions", 5.0, 1, 200)]
    assert transport.write_attempts == 0


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_transport_rejects_every_write_method(method):
    session = FakeSession()
    transport = ReadOnlyTransport(session=session)

    with pytest.raises(ReadOnlyViolation, match="WRITE_METHOD_FORBIDDEN"):
        getattr(transport, method.lower())(
            "https://api-futures.kucoin.com/api/v1/orders"
        )

    assert transport.write_attempts == 1
    assert session.calls == []


def test_transport_rejects_non_allowlisted_get():
    session = FakeSession()
    transport = ReadOnlyTransport(session=session)

    with pytest.raises(ReadOnlyViolation, match="ENDPOINT_NOT_ALLOWLISTED"):
        transport.get("https://api-futures.kucoin.com/api/v1/withdrawals", timeout=5)

    assert session.calls == []


def test_transport_rejects_write_on_allowlisted_order_path():
    session = FakeSession()
    transport = ReadOnlyTransport(session=session)

    with pytest.raises(ReadOnlyViolation, match="WRITE_METHOD_FORBIDDEN"):
        transport.request(
            "POST", "https://api-futures.kucoin.com/api/v1/orders", json={}
        )

    assert transport.write_attempts == 1
    assert session.calls == []


def test_transport_bounds_and_validates_timeout():
    session = FakeSession()
    transport = ReadOnlyTransport(session=session)

    transport.get("https://api-futures.kucoin.com/api/v1/positions", timeout=999)
    assert session.calls[-1]["timeout"] == 15.0

    for invalid in (0, -1, "not-a-number"):
        with pytest.raises(ReadOnlyViolation, match="INVALID_TIMEOUT"):
            transport.get(
                "https://api-futures.kucoin.com/api/v1/positions", timeout=invalid
            )


def test_transport_retries_timeout_then_succeeds():
    session = FakeSession({"positions": [
        requests.Timeout("slow"),
        FakeResponse({"code": "200000", "data": []}),
    ]})
    transport = ReadOnlyTransport(session=session, max_retries=1, sleep=lambda _: None)

    response = transport.get(
        "https://api-futures.kucoin.com/api/v1/positions", timeout=5
    )

    assert response.status_code == 200
    assert len(session.calls) == 2
    assert transport.calls[-1][3] == 2


def test_transport_retry_exhaustion_raises():
    session = FakeSession({"positions": [
        requests.Timeout("slow"), requests.Timeout("slow"),
    ]})
    transport = ReadOnlyTransport(session=session, max_retries=1, sleep=lambda _: None)

    with pytest.raises(requests.Timeout):
        transport.get("https://api-futures.kucoin.com/api/v1/positions", timeout=5)

    assert len(session.calls) == 2


def test_transport_rate_limit_retries_then_reports_rate_limited():
    session = FakeSession({"positions": [
        FakeResponse({}, status=429), FakeResponse({}, status=429),
    ]})
    transport = ReadOnlyTransport(session=session, max_retries=1, sleep=lambda _: None)

    with pytest.raises(ReadOnlyRateLimited):
        transport.get("https://api-futures.kucoin.com/api/v1/positions", timeout=5)

    assert transport.rate_limited is True
    assert len(session.calls) == 2


def test_transport_rate_limit_then_success():
    session = FakeSession({"positions": [
        FakeResponse({}, status=429),
        FakeResponse({"code": "200000", "data": []}),
    ]})
    transport = ReadOnlyTransport(session=session, max_retries=1, sleep=lambda _: None)

    response = transport.get(
        "https://api-futures.kucoin.com/api/v1/positions", timeout=5
    )

    assert response.status_code == 200
    assert transport.rate_limited is True


def test_full_read_only_verification_flat_account_is_ok():
    verifier, session = build_verifier()

    result = verifier.verify("XRPUSDTM")

    assert result["status"] == STATUS_OK
    assert set(result["statuses"].values()) == {STATUS_OK}
    assert result["checks"]["account"]["data"]["equity"] == 8.0
    assert result["checks"]["account"]["data"]["availableBalance"] == 7.9
    assert result["checks"]["position"]["data"]["state"] == "FLAT"
    assert result["checks"]["openOrders"]["data"]["state"] == "NONE"
    assert result["checks"]["conditionalOrders"]["data"]["state"] == "NONE"
    assert result["checks"]["protectiveStop"]["data"]["state"] == "NONE"
    assert result["checks"]["marginMode"]["data"]["marginMode"] == "ISOLATED"
    assert result["checks"]["leverageLiquidation"]["data"]["position"] == "FLAT"
    assert result["safety"]["writeAttempts"] == 0
    assert result["safety"]["orderMutations"] == 0
    assert result["safety"]["runtimeAuthorityMutation"] is False
    assert result["safety"]["intentStoreTouched"] is False
    assert result["safety"]["liveOrderAllowed"] is False
    assert session.posts == []


def test_account_missing_fields_is_reported():
    def account(url):
        return FakeResponse({"code": "200000", "data": {
            "currency": "USDT", "accountEquity": "8.0",
        }})

    verifier, _ = build_verifier({"account-overview": account})

    result = verifier.account_read()

    assert result["status"] == STATUS_MISSING_FIELDS
    assert result["data"]["availableBalance"] is None


def test_position_stale_response_is_reported():
    stale = open_position(updated_at=time.time() - 3600)
    verifier, _ = build_verifier({"positions": [
        FakeResponse({"code": "200000", "data": [stale]})
    ]})

    result = verifier.position_read("XRPUSDTM")

    assert result["status"] == STATUS_STALE
    assert result["data"]["state"] == "OPEN"
    assert result["fresh"] is False


def test_position_missing_quantity_is_reported():
    verifier, _ = build_verifier({"positions": [
        FakeResponse({"code": "200000", "data": [{"symbol": "XRPUSDTM"}]})
    ]})

    result = verifier.position_read("XRPUSDTM")

    assert result["status"] == STATUS_MISSING_FIELDS


def test_open_order_count_mismatch_is_partial():
    verifier, _ = build_verifier({"orders": [
        FakeResponse({"code": "200000", "data": {
            "items": [], "totalPage": 1, "currentPage": 1,
        }})
    ]})
    original = verifier.trade.get_open_orders
    verifier.trade.get_open_orders = lambda symbol=None: {
        "success": True, "count": 2, "orders": [], "timestamp": time.time(),
    }
    result = verifier.open_order_read("XRPUSDTM")
    verifier.trade.get_open_orders = original

    assert result["status"] == STATUS_PARTIAL
    assert result["reason"] == "KUCOIN_OPEN_ORDER_COUNT_MISMATCH"


def test_protective_stop_present_evidence():
    stop = {
        "id": "stop-1", "symbol": "XRPUSDTM", "side": "sell", "size": "1",
        "stopPrice": "0.9", "reduceOnly": True, "updatedAt": int(time.time() * 1000),
    }
    verifier, _ = build_verifier({"stopOrders": [
        FakeResponse({"code": "200000", "data": {"items": [stop]}})
    ]})

    result = verifier.protective_stop_read("XRPUSDTM")

    assert result["status"] == STATUS_OK
    assert result["data"]["state"] == "PRESENT"
    assert result["data"]["count"] == 1


def test_leverage_and_liquidation_evidence_from_position():
    position = open_position()
    verifier, _ = build_verifier({"positions": [
        FakeResponse({"code": "200000", "data": [position]})
    ]})

    result = verifier.leverage_liquidation_read("XRPUSDTM")

    assert result["status"] == STATUS_OK
    assert result["data"]["leverage"] == 3.0
    assert result["data"]["liquidationPrice"] == 0.5
    assert result["data"]["liquidationDistancePercent"] == pytest.approx(54.5454, rel=1e-3)


def test_contract_missing_fields_is_reported():
    verifier, _ = build_verifier({"contracts/": [
        FakeResponse({"code": "200000", "data": {"symbol": "XRPUSDTM", "lotSize": 1}})
    ]})

    result = verifier.contract_read("XRPUSDTM")

    assert result["status"] == STATUS_MISSING_FIELDS


def test_rate_limited_checks_are_classified():
    verifier, _ = build_verifier()
    fragments = (
        "account-overview", "positions", "stopOrders", "orders",
        "getMarginMode", "contracts/", "allTickers",
    )
    verifier.transport.session.routes = [
        (fragment, lambda url: FakeResponse({}, status=429))
        for fragment in fragments
    ]

    result = verifier.verify("XRPUSDTM")

    assert result["status"] == STATUS_PARTIAL
    assert result["statuses"]["account"] == STATUS_RATE_LIMITED
    assert result["statuses"]["position"] == STATUS_RATE_LIMITED


def test_authentication_failure_is_classified():
    class AuthError(Exception):
        status_code = 401

    verifier, _ = build_verifier({"account-overview": AuthError("denied")})
    original = verifier.trade.get_account_overview
    verifier.trade.get_account_overview = lambda: (_ for _ in ()).throw(AuthError("denied"))

    result = verifier.account_read()

    verifier.trade.get_account_overview = original
    assert result["status"] == STATUS_AUTHENTICATION_FAILED


def test_redacted_logging_and_serialization_have_no_credentials(caplog):
    verifier, _ = build_verifier()

    result = verifier.verify("XRPUSDTM")
    with caplog.at_level("INFO"):
        text = verifier.redacted_summary(result)

    serialized = json.dumps(result, default=str)
    for secret in (API_KEY, API_SECRET, PASSPHRASE):
        assert secret not in serialized
        assert secret not in text
        assert secret not in caplog.text


def test_verify_never_posts_and_does_not_mutate_authority():
    verifier, session = build_verifier()
    verifier.trade.live_order_allowed = False
    verifier.trade.runtime_submission_allowed = True
    verifier.trade.order_intent_path = None

    result = verifier.verify("XRPUSDTM")

    assert session.posts == []
    assert verifier.trade.live_order_allowed is False
    assert verifier.trade.runtime_submission_allowed is True
    assert verifier.trade.order_intent_path is None
    assert result["safety"]["runtimeAuthorityMutation"] is False
    assert os.environ.get("TRADINGAI_LIVE_ORDER_INTENT_PATH", "") == ""


def test_every_real_request_is_allowlisted_get():
    verifier, session = build_verifier()

    verifier.verify("XRPUSDTM")

    assert session.calls
    for call in session.calls:
        from urllib.parse import urlsplit

        path = urlsplit(call["url"]).path
        assert any(
            path == prefix.rstrip("/") or path.startswith(prefix)
            for prefix in ALLOWED_ENDPOINT_PREFIXES
        )


def test_unavailable_private_read_is_reported_not_fabricated():
    verifier, _ = build_verifier({"account-overview": FakeResponse({}, status=503)})
    original = verifier.trade.get_account_overview

    def failed():
        raise requests.HTTPError("HTTP 503")

    verifier.trade.get_account_overview = failed
    result = verifier.account_read()
    verifier.trade.get_account_overview = original

    assert result["status"] == STATUS_UNAVAILABLE
    assert result["data"] == {}
