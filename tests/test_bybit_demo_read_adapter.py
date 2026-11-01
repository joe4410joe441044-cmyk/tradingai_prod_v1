from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backend.accounts.models import (
    AccountId,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.accounts.registry_contract import AccountRegistrationDraft
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalAccountBinding,
    ExternalBindingEnvironment,
    ExternalBindingStatus,
)
from backend.accounts.registry_store import AccountRegistryStore, DurableAccountRegistry
from backend.accounts.resolver import (
    AccountResolutionRequest,
    CredentialRequirement,
    resolve_account,
)
from backend.execution.adapter_contracts import CapabilityState, OrderSide
from backend.execution.bybit_demo_read_adapter import (
    ACCOUNT_SUMMARY_PATH,
    OPEN_ORDERS_PATH,
    POSITIONS_PATH,
    BybitDemoReadAdapter,
)
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadCapabilities,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
    build_read_only_configuration,
)
from backend.execution.read_only_observations import (
    ReadDataQuality,
    ReadErrorCode,
)
from backend.execution.read_only_transport import (
    ReadOnlyRequest,
    ReadOnlyResponse,
    ReadTransportError,
    ReadTransportFailureKind,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "bybit_demo_read"
ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class FakeTransport:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.requests: list[ReadOnlyRequest] = []

    def send(self, request: ReadOnlyRequest) -> ReadOnlyResponse:
        self.requests.append(request)
        result = self._handler(request)
        if isinstance(result, Exception):
            raise result
        return result


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _response(body: dict, *, status: int = 200) -> ReadOnlyResponse:
    return ReadOnlyResponse(status, copy.deepcopy(body), NOW)


def _query(request: ReadOnlyRequest) -> dict[str, str]:
    return request.query_dict()


def _capabilities(**overrides) -> ReadCapabilities:
    values = {
        "account_read": CapabilityState.SUPPORTED,
        "positions_read": CapabilityState.SUPPORTED,
        "orders_read": CapabilityState.SUPPORTED,
        "server_time": CapabilityState.SUPPORTED,
    }
    values.update(overrides)
    return ReadCapabilities(**values)


def _reference() -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "fabricated-bundle",
        "HYRO_DEMO",
    )


def _configuration(**overrides) -> ReadOnlyAdapterConfiguration:
    values = {
        "account_id": ACCOUNT_ID,
        "account_type": AccountType.PROP,
        "execution_mode": ExecutionMode.EXTERNAL_SIMULATION,
        "execution_venue": ExecutionVenue.BYBIT_DEMO,
        "record_lifecycle": AccountLifecycleState.REGISTERED,
        "registry_revision": 7,
        "record_revision": 3,
        "credential_reference": _reference(),
        "external_binding_status": ExternalBindingStatus.VERIFIED,
        "external_binding_verified": True,
        "external_binding_fingerprint": "fabricated-fingerprint",
        "endpoint_profile": EndpointProfile.BYBIT_DEMO_V5,
        "read_purpose": ReadPurpose.ACCOUNT_OBSERVATION,
        "capabilities": _capabilities(),
    }
    values.update(overrides)
    return ReadOnlyAdapterConfiguration(**values)


def _adapter(handler, *, binding=None, clock=None, **kwargs) -> tuple[BybitDemoReadAdapter, FakeTransport]:
    transport = FakeTransport(handler)
    adapter = BybitDemoReadAdapter(
        binding or _configuration(),
        transport,
        clock or FixedClock(),
        **kwargs,
    )
    return adapter, transport


def _summary_handler():
    return _response(_load("wallet_balance_fabricated.json"))


def test_adapter_construction_has_no_io_and_no_execution_surface():
    adapter, transport = _adapter(lambda request: _summary_handler())
    assert transport.requests == []
    for name in ("submit_order", "cancel_order", "close_position", "place_order", "amend_order"):
        assert not hasattr(adapter, name)
    assert adapter.endpoint_base == "https://api-demo.bybit.com"


def test_adapter_requires_explicit_transport_and_clock():
    with pytest.raises(TypeError):
        BybitDemoReadAdapter(_configuration(), None, FixedClock())
    with pytest.raises(TypeError):
        BybitDemoReadAdapter(_configuration(), FakeTransport(_summary_handler), None)


def test_adapter_rejects_paper_normal_and_wrong_profile_bindings():
    paper = _configuration(
        execution_mode=ExecutionMode.PAPER,
        execution_venue=ExecutionVenue.INTERNAL_PAPER,
        endpoint_profile=EndpointProfile.INTERNAL_PAPER_V1,
        credential_reference=None,
        external_binding_status=None,
        external_binding_verified=False,
        external_binding_fingerprint=None,
    )
    with pytest.raises(ValueError):
        BybitDemoReadAdapter(paper, FakeTransport(_summary_handler), FixedClock())
    normal = _configuration(account_type=AccountType.NORMAL)
    with pytest.raises(ValueError):
        BybitDemoReadAdapter(normal, FakeTransport(_summary_handler), FixedClock())
    bloFin = _configuration(
        execution_venue=ExecutionVenue.BLOFIN_DEMO,
        endpoint_profile=EndpointProfile.BLOFIN_DEMO_V1,
    )
    with pytest.raises(ValueError):
        BybitDemoReadAdapter(bloFin, FakeTransport(_summary_handler), FixedClock())
    with pytest.raises(ValueError):
        _configuration(
            execution_mode=ExecutionMode.LIVE,
            execution_venue=ExecutionVenue.KUCOIN_FUTURES,
        )


def test_read_requests_are_get_only_credential_free_and_allowlisted():
    def handler(request):
        if request.path == POSITIONS_PATH:
            name = (
                "positions_page1_fabricated.json"
                if _query(request).get("cursor") is None
                else "positions_page2_fabricated.json"
            )
            return _response(_load(name))
        return _response(_load("open_orders_page2_fabricated.json"))

    adapter, transport = _adapter(handler)
    adapter.list_positions()
    adapter.list_open_orders()
    assert {request.path for request in transport.requests} == {POSITIONS_PATH, OPEN_ORDERS_PATH}
    assert all(request.path in {POSITIONS_PATH, OPEN_ORDERS_PATH} for request in transport.requests)
    for request in transport.requests:
        assert request.method == "GET"
        keys = set(_query(request))
        assert not keys & {"api_key", "sign", "signature", "timestamp", "passphrase", "secret"}
        assert "://" not in request.path
        assert not hasattr(request, "headers")
    with pytest.raises(ValueError):
        ReadOnlyRequest("POST", "/v5/account/wallet-balance", ())
    with pytest.raises(ValueError):
        ReadOnlyRequest("GET", "https://evil.example/v5/account/wallet-balance", ())
    with pytest.raises(ValueError):
        ReadOnlyRequest("GET", "/v5/../secret", ())
    with pytest.raises(ValueError):
        adapter._request("/v5/unknown", ())


def test_account_summary_preserves_units_decimal_precision_and_negative_values():
    adapter, _ = _adapter(lambda request: _summary_handler())
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.metadata.account_id == ACCOUNT_ID
    assert result.metadata.pages_fetched == 1
    assert result.metadata.source_timestamp == NOW
    assert result.metadata.source_timestamp_available is True
    summary = result.summary
    assert summary.account_type == "UNIFIED"
    assert summary.total_equity_usd == Decimal("10250.75")
    assert summary.total_wallet_balance_usd == Decimal("10000.00")
    assert summary.total_margin_balance_usd == Decimal("10100.25")
    assert summary.total_available_balance_usd == Decimal("9000.50")
    assert summary.total_perp_upl_usd == Decimal("-150.25")
    coins = {coin.coin: coin for coin in summary.coins}
    assert coins["USDT"].equity == Decimal("10050.25")
    assert coins["USDT"].unrealised_pnl == Decimal("-150.25")
    # Coin equity is in coin units and is not the account-wide USD value.
    assert coins["BTC"].equity == Decimal("0.002")
    assert coins["BTC"].usd_value == Decimal("200.50")
    assert summary.total_equity_usd != coins["BTC"].equity


def test_wallet_missing_empty_and_zero_are_distinct():
    body = _load("wallet_balance_fabricated.json")
    item = body["result"]["list"][0]
    coin = item["coin"][0]
    coin["equity"] = ""
    coin["locked"] = "0"
    del coin["usdValue"]
    del item["totalPerpUPL"]
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    summary = result.summary
    usdt = next(item for item in summary.coins if item.coin == "USDT")
    assert usdt.equity is None
    assert usdt.locked == Decimal("0")
    assert usdt.usd_value is None
    assert "usdValue" in usdt.missing_fields
    assert "equity" in usdt.missing_fields
    assert summary.total_perp_upl_usd is None
    assert "totalPerpUPL" in summary.missing_fields


def test_positions_multipage_zero_position_and_negative_pnl():
    pages = {
        None: _response(_load("positions_page1_fabricated.json")),
        "fabricated-position-page-2": _response(_load("positions_page2_fabricated.json")),
    }

    def handler(request):
        return pages[_query(request).get("cursor")]

    adapter, transport = _adapter(handler)
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.metadata.pages_fetched == 2
    assert [request.query_dict().get("cursor") for request in transport.requests] == [
        None,
        "fabricated-position-page-2",
    ]
    positions = {position.symbol: position for position in result.positions}
    assert set(positions) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert positions["BTCUSDT"].side is OrderSide.BUY
    assert positions["BTCUSDT"].position_idx == 1
    assert positions["BTCUSDT"].size == Decimal("0.05")
    assert positions["BTCUSDT"].unrealised_pnl == Decimal("50.00")
    assert positions["ETHUSDT"].side is None
    assert positions["ETHUSDT"].size == Decimal("0")
    assert positions["ETHUSDT"].avg_price is None
    assert "avgPrice" in positions["ETHUSDT"].missing_fields
    assert positions["SOLUSDT"].side is OrderSide.SELL
    assert positions["SOLUSDT"].unrealised_pnl == Decimal("-7.125")


def test_open_orders_multipage_partial_fill_and_empty_optional_strings():
    pages = {
        None: _response(_load("open_orders_page1_fabricated.json")),
        "fabricated-order-page-2": _response(_load("open_orders_page2_fabricated.json")),
    }
    adapter, _ = _adapter(lambda request: pages[_query(request).get("cursor")])
    result = adapter.list_open_orders()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.metadata.pages_fetched == 2
    orders = {order.order_id: order for order in result.orders}
    assert set(orders) == {"fabricated-order-0001", "fabricated-order-0002", "fabricated-order-0003"}
    partial = orders["fabricated-order-0001"]
    assert partial.order_status == "PartiallyFilled"
    assert partial.qty == Decimal("0.05")
    assert partial.cum_exec_qty == Decimal("0.03")
    assert partial.leaves_qty == Decimal("0.02")
    assert partial.reduce_only is False
    assert partial.created_at == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=10)
    market = orders["fabricated-order-0002"]
    assert market.price == Decimal("0")
    assert market.avg_price is None
    assert market.client_order_id is None
    assert market.reduce_only is True
    assert "avgPrice" in market.missing_fields
    assert orders["fabricated-order-0003"].order_status == "Untriggered"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.__setitem__("retCode", True),
        lambda body: body.__setitem__("retCode", "0"),
        lambda body: body.__setitem__("retMsg", None),
        lambda body: body.pop("result"),
        lambda body: body.__setitem__("result", []),
        lambda body: body["result"]["list"][0].__setitem__("totalEquity", "NaN"),
        lambda body: body["result"]["list"][0].__setitem__("totalEquity", 1.5),
        lambda body: body["result"]["list"][0].__setitem__("accountType", "SPOT"),
        lambda body: body.pop("time"),
        lambda body: body.__setitem__("time", "not-a-timestamp"),
    ],
)
def test_malformed_wallet_responses_never_become_success(mutate):
    body = _load("wallet_balance_fabricated.json")
    mutate(body)
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    if "time" not in body:
        # A missing server timestamp is recorded, not invented.
        assert result.metadata.data_quality is ReadDataQuality.COMPLETE
        assert result.metadata.source_timestamp is None
        assert result.metadata.source_timestamp_available is False
        assert result.metadata.missing_fields == ("source_timestamp",)
    else:
        assert result.metadata.data_quality is ReadDataQuality.FAILED
        assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE
        assert result.summary is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["result"]["list"][0].__setitem__("size", True),
        lambda body: body["result"]["list"][0].__setitem__("size", "NaN"),
        lambda body: body["result"]["list"][0].__setitem__("positionIdx", True),
        lambda body: body["result"]["list"][0].pop("symbol"),
        lambda body: body["result"]["list"][0].__setitem__("side", "Long"),
        lambda body: body["result"]["list"][0].__setitem__("side", "Buy") or body["result"]["list"][0].__setitem__("size", "0"),
        lambda body: body["result"]["list"][1].__setitem__("side", "") or body["result"]["list"][1].__setitem__("size", "1"),
        lambda body: body["result"].__setitem__("category", "inverse"),
    ],
)
def test_malformed_position_payloads_are_rejected(mutate):
    body = _load("positions_page1_fabricated.json")
    mutate(body)
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE
    assert result.positions == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["result"]["list"][0].__setitem__("qty", True),
        lambda body: body["result"]["list"][0].__setitem__("qty", "0"),
        lambda body: body["result"]["list"][0].__setitem__("orderStatus", "Filled"),
        lambda body: body["result"]["list"][0].__setitem__("reduceOnly", "false"),
        lambda body: body["result"]["list"][0].__setitem__("side", "Long"),
    ],
)
def test_malformed_open_order_payloads_are_rejected(mutate):
    body = _load("open_orders_page1_fabricated.json")
    mutate(body)
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.list_open_orders()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("ret_code", "expected"),
    [
        (10003, ReadErrorCode.AUTHENTICATION_FAILED),
        (10005, ReadErrorCode.PERMISSION_DENIED),
        (10006, ReadErrorCode.RATE_LIMITED),
        (10002, ReadErrorCode.CLOCK_SKEW),
        (99999, ReadErrorCode.VENUE_REJECTED),
    ],
)
def test_venue_errors_are_classified_and_redacted(ret_code, expected):
    body = {
        "retCode": ret_code,
        "retMsg": "raw venue text SECRET-TOKEN-123 must not leak",
        "result": {},
        "retExtInfo": {},
        "time": 1767225600000,
    }
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    failure = result.metadata.failure
    assert failure.code is expected
    assert failure.venue_ret_code == ret_code
    assert "SECRET-TOKEN-123" not in failure.safe_message
    assert "SECRET-TOKEN-123" not in repr(failure)
    assert failure.retryable is (expected in {ReadErrorCode.RATE_LIMITED, ReadErrorCode.TIMEOUT})


@pytest.mark.parametrize(
    ("error", "expected", "retryable"),
    [
        (ReadTransportError(ReadTransportFailureKind.TIMEOUT), ReadErrorCode.TIMEOUT, True),
        (ReadTransportError(ReadTransportFailureKind.CONNECTION_FAILED), ReadErrorCode.TRANSPORT_FAILURE, True),
    ],
)
def test_transport_errors_are_classified(error, expected, retryable):
    adapter, _ = _adapter(lambda request: error)
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is expected
    assert result.metadata.failure.retryable is retryable


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ReadErrorCode.AUTHENTICATION_FAILED),
        (403, ReadErrorCode.PERMISSION_DENIED),
        (429, ReadErrorCode.RATE_LIMITED),
        (500, ReadErrorCode.TRANSPORT_FAILURE),
        (404, ReadErrorCode.VENUE_REJECTED),
    ],
)
def test_http_status_is_classified_without_response_text(status, expected):
    adapter, _ = _adapter(lambda request: _response({"secret": "SECRET"}, status=status))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is expected
    assert "SECRET" not in repr(result)


def test_pagination_cursor_loop_is_partial_and_stops():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        body = _load("positions_page1_fabricated.json")
        body["result"]["nextPageCursor"] = "loop-cursor"
        body["result"]["list"] = body["result"]["list"][:1] if calls["count"] == 1 else []
        return _response(body)

    adapter, transport = _adapter(handler)
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.PAGINATION_INCOMPLETE
    assert len(transport.requests) == 2
    assert len(result.positions) == 1


def test_pagination_page_limit_is_partial_and_bounded():
    def handler(request):
        body = _load("positions_page1_fabricated.json")
        body["result"]["nextPageCursor"] = "always-more"
        return _response(body)

    adapter, transport = _adapter(handler, max_pages=1)
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.PAGINATION_INCOMPLETE
    assert len(transport.requests) == 1


def test_later_page_failure_returns_partial_rows_not_full_success():
    def handler(request):
        if _query(request).get("cursor") is None:
            return _response(_load("open_orders_page1_fabricated.json"))
        return _response(
            {
                "retCode": 10005,
                "retMsg": "SECRET-TOKEN-456 raw denial",
                "result": {},
                "retExtInfo": {},
                "time": 1767225601000,
            }
        )

    adapter, _ = _adapter(handler)
    result = adapter.list_open_orders()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.PERMISSION_DENIED
    assert "SECRET-TOKEN-456" not in repr(result)
    assert len(result.orders) == 2


def test_duplicate_contradictory_records_become_partial():
    def handler(request):
        if _query(request).get("cursor") is None:
            return _response(_load("open_orders_page1_fabricated.json"))
        body = _load("open_orders_page2_fabricated.json")
        body["result"]["list"][0]["orderId"] = "fabricated-order-0001"
        body["result"]["list"][0]["qty"] = "999"
        return _response(body)

    adapter, _ = _adapter(handler)
    result = adapter.list_open_orders()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.DUPLICATE_RECORD
    assert len(result.orders) == 2
    assert all(order.order_id != "fabricated-order-0003" for order in result.orders)


def test_empty_page_with_next_cursor_is_not_treated_as_terminal():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            body = _load("positions_page1_fabricated.json")
            body["result"]["list"] = []
            body["result"]["nextPageCursor"] = "fabricated-position-page-2"
            return _response(body)
        return _response(_load("positions_page2_fabricated.json"))

    adapter, _ = _adapter(handler)
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.metadata.pages_fetched == 2
    assert [position.symbol for position in result.positions] == ["SOLUSDT"]


def test_observe_account_is_a_non_atomic_endpoint_envelope():
    def handler(request):
        if request.path == ACCOUNT_SUMMARY_PATH:
            return _response(_load("wallet_balance_fabricated.json"))
        if request.path == POSITIONS_PATH:
            return _response(_load("positions_page2_fabricated.json"))
        return _response(
            {"retCode": 10005, "retMsg": "denied", "result": {}, "retExtInfo": {}, "time": 1767225600000}
        )

    adapter, _ = _adapter(handler)
    result = adapter.observe_account()
    assert result.overall_quality is ReadDataQuality.PARTIAL
    assert result.summary.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.positions.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.open_orders.metadata.data_quality is ReadDataQuality.FAILED
    assert result.atomic_snapshot is False
    assert result.account_id == ACCOUNT_ID
    assert result.registry_revision == 7
    assert result.record_revision == 3


def test_stale_and_future_server_timestamps_are_not_success():
    stale = _load("wallet_balance_fabricated.json")
    stale["time"] = int((NOW - timedelta(seconds=120)).timestamp() * 1000)
    adapter, _ = _adapter(lambda request: _response(stale), stale_after=timedelta(seconds=30))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.STALE
    assert result.metadata.failure.code is ReadErrorCode.STALE_DATA
    assert result.summary is not None

    future = _load("wallet_balance_fabricated.json")
    future["time"] = int((NOW + timedelta(seconds=120)).timestamp() * 1000)
    adapter, _ = _adapter(lambda request: _response(future), future_skew_tolerance=timedelta(seconds=60))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.STALE
    assert result.metadata.failure.code is ReadErrorCode.CLOCK_SKEW


def test_unsupported_and_unknown_capabilities_do_not_call_transport():
    unsupported = _configuration(capabilities=_capabilities(account_read=CapabilityState.UNSUPPORTED))
    adapter, transport = _adapter(lambda request: _summary_handler(), binding=unsupported)
    result = adapter.get_account_summary()
    assert result.metadata.failure.code is ReadErrorCode.UNSUPPORTED_CAPABILITY
    assert transport.requests == []

    unknown = _configuration(capabilities=_capabilities(positions_read=CapabilityState.UNKNOWN))
    adapter, transport = _adapter(lambda request: _summary_handler(), binding=unknown)
    result = adapter.list_positions()
    assert result.metadata.failure.code is ReadErrorCode.CAPABILITY_UNKNOWN
    assert transport.requests == []


def test_invalid_position_and_order_scope_requests_fail_before_transport():
    adapter, transport = _adapter(lambda request: _summary_handler())
    assert adapter.list_positions(settle_coin="").metadata.failure.code is ReadErrorCode.INVALID_REQUEST
    assert adapter.list_open_orders(symbol="").metadata.failure.code is ReadErrorCode.INVALID_REQUEST
    assert transport.requests == []


def _seed_registry(tmp_path):
    ticks = iter(NOW + timedelta(seconds=index) for index in range(20))
    store = AccountRegistryStore(tmp_path)
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks))
    assert registry.initialize().status.value == "SAVED"
    reference = _reference()
    external = ExternalAccountBinding(
        ExecutionVenue.BYBIT_DEMO,
        ExternalBindingEnvironment.DEMO,
        ExternalBindingStatus.VERIFIED,
        "fabricated-external",
        "fabricated-fingerprint",
        NOW,
        "injected-test",
    )
    draft = AccountRegistrationDraft(
        "bybit-read-request",
        AccountType.PROP,
        ExecutionMode.EXTERNAL_SIMULATION,
        ExecutionVenue.BYBIT_DEMO,
        PropProgram.HYROTRADER,
        PropPhase.CHALLENGE,
        display_label="Fabricated Bybit read account",
        credential_reference=reference,
        external_binding=external,
    )
    registered = registry.register(
        draft, expected_registry_revision=1, operation_id="op-bybit-read-register"
    )
    account_id = registered.identity.account_id
    resolution = resolve_account(
        AccountResolutionRequest(
            account_id,
            expected_registry_revision=2,
            required_account_type=AccountType.PROP,
            required_execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
            required_execution_venue=ExecutionVenue.BYBIT_DEMO,
            credential_requirement=CredentialRequirement.REFERENCE_REQUIRED,
            require_verified_external_binding=True,
        ),
        store.load(),
    )
    configuration = build_read_only_configuration(
        resolution,
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
        read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
        capabilities=_capabilities(),
    )
    return store, registry, account_id, configuration


def test_injected_snapshot_source_rejects_stale_or_disabled_binding_before_transport(tmp_path):
    store, registry, account_id, configuration = _seed_registry(tmp_path)
    adapter, transport = _adapter(
        lambda request: _summary_handler(),
        binding=configuration,
        snapshot_source=lambda: store.load().snapshot,
    )
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert len(transport.requests) == 1

    registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-bybit-read-disable",
    )
    before = len(transport.requests)
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.STALE_BINDING
    assert result.metadata.failure.venue_safe_code == "ACCOUNT_DISABLED"
    assert result.summary is None
    assert len(transport.requests) == before


def test_snapshot_source_returning_non_snapshot_fails_closed():
    adapter, transport = _adapter(lambda request: _summary_handler(), snapshot_source=lambda: object())
    result = adapter.get_account_summary()
    assert result.metadata.failure.code is ReadErrorCode.INVALID_BINDING
    assert transport.requests == []


def test_observation_does_not_carry_execution_authority_or_raw_payload():
    adapter, _ = _adapter(lambda request: _summary_handler())
    result = adapter.get_account_summary()
    assert not hasattr(result, "venue_order_id")
    assert not hasattr(result, "submit_order")
    assert not hasattr(result.metadata, "raw_payload")
    assert "_FIXTURE" not in repr(result)
    assert "FABRICATED/SYNTHETIC" not in repr(result)


# --- CC-2J regression tests for CC-2I findings F-01 .. F-06 ---


def test_f01_snapshot_source_exception_stays_typed_and_redacted():
    def raising_snapshot_source():
        raise RuntimeError("SECRET-TOKEN-999 registry failure")

    adapter, transport = _adapter(
        lambda request: _summary_handler(),
        snapshot_source=raising_snapshot_source,
    )
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.STATE_UNKNOWN
    assert "SECRET-TOKEN-999" not in repr(result)
    assert transport.requests == []

    observation = adapter.observe_account()
    assert observation.overall_quality is ReadDataQuality.FAILED
    assert observation.post_read_binding_failure.code is ReadErrorCode.STATE_UNKNOWN
    assert "SECRET-TOKEN-999" not in repr(observation)
    assert transport.requests == []


def test_f02_stale_first_page_cannot_become_complete():
    def handler(request):
        if _query(request).get("cursor") is None:
            body = _load("positions_page1_fabricated.json")
            body["time"] = int((NOW - timedelta(seconds=120)).timestamp() * 1000)
            return _response(body)
        body = _load("positions_page2_fabricated.json")
        body["time"] = int(NOW.timestamp() * 1000)
        return _response(body)

    adapter, _ = _adapter(handler, stale_after=timedelta(seconds=30))
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.STALE
    assert result.metadata.failure.code is ReadErrorCode.STALE_DATA
    assert result.metadata.source_timestamp == NOW
    assert result.metadata.oldest_source_timestamp == NOW - timedelta(seconds=120)
    assert result.metadata.pages_fetched == 2
    assert len(result.positions) == 3


def test_f02_future_later_page_still_triggers_clock_skew():
    def handler(request):
        if _query(request).get("cursor") is None:
            body = _load("positions_page1_fabricated.json")
            return _response(body)
        body = _load("positions_page2_fabricated.json")
        body["time"] = int((NOW + timedelta(seconds=120)).timestamp() * 1000)
        return _response(body)

    adapter, _ = _adapter(handler, future_skew_tolerance=timedelta(seconds=60))
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.STALE
    assert result.metadata.failure.code is ReadErrorCode.CLOCK_SKEW


def test_f03_absent_wallet_coin_list_is_malformed():
    body = _load("wallet_balance_fabricated.json")
    body["result"]["list"][0].pop("coin")
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE
    assert result.summary is None


def test_f03_explicit_empty_coin_list_remains_valid():
    body = _load("wallet_balance_fabricated.json")
    body["result"]["list"][0]["coin"] = []
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.summary.coins == ()


@pytest.mark.parametrize(
    "field",
    ["totalEquity", "totalWalletBalance", "totalMarginBalance", "totalAvailableBalance"],
)
def test_f03_absent_mandatory_wallet_total_is_malformed(field):
    body = _load("wallet_balance_fabricated.json")
    body["result"]["list"][0].pop(field)
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE
    assert result.summary is None


def test_f03_missing_total_perp_upl_remains_optional():
    body = _load("wallet_balance_fabricated.json")
    body["result"]["list"][0].pop("totalPerpUPL")
    adapter, _ = _adapter(lambda request: _response(body))
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.summary.total_perp_upl_usd is None
    assert "totalPerpUPL" in result.summary.missing_fields


@pytest.mark.parametrize(
    ("fixture", "reader", "container"),
    [
        ("positions_page1_fabricated.json", "list_positions", "positions"),
        ("open_orders_page1_fabricated.json", "list_open_orders", "orders"),
    ],
)
def test_f03_absent_next_page_cursor_is_malformed(fixture, reader, container):
    body = _load(fixture)
    body["result"].pop("nextPageCursor")
    adapter, _ = _adapter(lambda request: _response(body))
    result = getattr(adapter, reader)()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.MALFORMED_RESPONSE
    assert getattr(result, container) == ()


@pytest.mark.parametrize(
    "path",
    [
        "/v5/%2e%2e/secret",
        "/v5/%2E%2E/secret",
        "/v5/%2fsecret",
        "/v5/%5csecret",
        "/v5/\u00fcnicode",
    ],
)
def test_f04_encoded_or_non_ascii_path_is_rejected(path):
    with pytest.raises(ValueError):
        ReadOnlyRequest("GET", path, ())
    assert ReadOnlyRequest("GET", ACCOUNT_SUMMARY_PATH, ()).path == ACCOUNT_SUMMARY_PATH


def test_f05_server_time_capability_controls_freshness_source():
    body = _load("wallet_balance_fabricated.json")
    body["time"] = int((NOW - timedelta(seconds=120)).timestamp() * 1000)
    for state in (CapabilityState.UNSUPPORTED, CapabilityState.UNKNOWN):
        binding = _configuration(capabilities=_capabilities(server_time=state))
        adapter, _ = _adapter(
            lambda request: _response(body),
            binding=binding,
            stale_after=timedelta(seconds=30),
        )
        result = adapter.get_account_summary()
        assert result.metadata.data_quality is ReadDataQuality.COMPLETE
        assert result.metadata.source_timestamp is None
        assert result.metadata.source_timestamp_available is False
        assert result.metadata.missing_fields == ("source_timestamp",)
        assert result.metadata.failure is None


def test_f05_read_purpose_is_enforced_per_endpoint():
    adapter, transport = _adapter(
        lambda request: _summary_handler(),
        binding=_configuration(read_purpose=ReadPurpose.POSITIONS_READ),
    )
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.PURPOSE_MISMATCH
    assert transport.requests == []

    positions_only, _ = _adapter(
        lambda request: _response(_load("positions_page2_fabricated.json")),
        binding=_configuration(read_purpose=ReadPurpose.POSITIONS_READ),
    )
    assert positions_only.list_positions().metadata.data_quality is ReadDataQuality.COMPLETE

    orders_only, transport = _adapter(
        lambda request: _response(_load("open_orders_page2_fabricated.json")),
        binding=_configuration(read_purpose=ReadPurpose.ORDERS_READ),
    )
    assert orders_only.list_positions().metadata.failure.code is ReadErrorCode.PURPOSE_MISMATCH
    assert transport.requests == []
    assert orders_only.list_open_orders().metadata.data_quality is ReadDataQuality.COMPLETE


def test_f06_binding_change_after_single_read_is_detected(tmp_path):
    store, registry, account_id, configuration = _seed_registry(tmp_path)
    fresh = store.load().snapshot
    registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-f06-single",
    )
    stale = store.load().snapshot
    calls = {"count": 0}

    def snapshot_source():
        calls["count"] += 1
        return fresh if calls["count"] == 1 else stale

    adapter, transport = _adapter(
        lambda request: _summary_handler(),
        binding=configuration,
        snapshot_source=snapshot_source,
    )
    result = adapter.get_account_summary()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.STALE_BINDING
    assert result.metadata.failure.venue_safe_code == "ACCOUNT_DISABLED"
    assert result.summary is not None
    assert len(transport.requests) == 1


def test_f06_binding_change_during_pagination_stops_with_partial_rows(tmp_path):
    store, registry, account_id, configuration = _seed_registry(tmp_path)
    fresh = store.load().snapshot
    registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-f06-page",
    )
    stale = store.load().snapshot
    calls = {"count": 0}

    def snapshot_source():
        calls["count"] += 1
        return fresh if calls["count"] == 1 else stale

    adapter, transport = _adapter(
        lambda request: _response(_load("positions_page1_fabricated.json")),
        binding=configuration,
        snapshot_source=snapshot_source,
    )
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.PARTIAL
    assert result.metadata.failure.code is ReadErrorCode.STALE_BINDING
    assert result.metadata.pages_fetched == 1
    assert len(result.positions) == 2
    assert len(transport.requests) == 1


def test_f06_binding_change_between_envelope_endpoints_is_detected(tmp_path):
    store, registry, account_id, configuration = _seed_registry(tmp_path)
    fresh = store.load().snapshot
    registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-f06-envelope",
    )
    stale = store.load().snapshot
    calls = {"count": 0}

    def snapshot_source():
        calls["count"] += 1
        return fresh if calls["count"] <= 2 else stale

    def handler(request):
        if request.path == ACCOUNT_SUMMARY_PATH:
            return _response(_load("wallet_balance_fabricated.json"))
        if request.path == POSITIONS_PATH:
            return _response(_load("positions_page2_fabricated.json"))
        return _response(_load("open_orders_page2_fabricated.json"))

    adapter, transport = _adapter(
        handler,
        binding=configuration,
        snapshot_source=snapshot_source,
    )
    result = adapter.observe_account()
    assert result.summary.metadata.data_quality is ReadDataQuality.COMPLETE
    assert result.positions.metadata.failure.code is ReadErrorCode.STALE_BINDING
    assert result.open_orders.metadata.failure.code is ReadErrorCode.STALE_BINDING
    assert result.overall_quality is ReadDataQuality.PARTIAL
    assert result.post_read_binding_failure.code is ReadErrorCode.STALE_BINDING
    assert len(transport.requests) == 1
