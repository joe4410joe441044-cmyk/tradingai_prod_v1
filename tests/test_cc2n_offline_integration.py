from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from backend.accounts.models import (
    AccountId,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
)
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalBindingStatus,
)
from backend.execution.adapter_contracts import CapabilityState
from backend.execution.bybit_demo_http_sender import BybitDemoHttpSender
from backend.execution.bybit_demo_read_adapter import BybitDemoReadAdapter
from backend.execution.bybit_key_info import (
    GeneralReadAuthorizationGate,
    ReadinessBinding,
    ReadinessReuseStatus,
    assess_readiness_reuse,
    require_reusable_readiness,
)
from backend.execution.bybit_server_time import (
    BYBIT_SERVER_TIME_PATH,
    BybitDemoServerTimeSource,
)
from backend.execution.bybit_v5_signed_transport import BybitV5SignedReadTransport
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadCapabilities,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
)
from backend.execution.read_only_bootstrap import BybitDemoKeyInfoBootstrap
from backend.execution.read_only_credential_file_provider import (
    CREDENTIAL_FILE_SCHEMA_VERSION,
    ReadOnlyCredentialFileProvider,
)
from backend.execution.read_only_credentials import CredentialScope
from backend.execution.read_only_observations import ReadDataQuality, ReadErrorCode
from backend.execution.read_only_policy import ClockPolicy, ReadOnlySafetyPolicy


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")
OTHER_ACCOUNT_ID = AccountId("acc_22222222222242228222222222222222")
CREDENTIAL_ID = "fabricated-integration-credential"
FABRICATED_KEY = "fabricated-key-not-real"
FABRICATED_SECRET = "fabricated-secret-not-real"
EXPECTED_USER_ID = 12345

WALLET_PATH = "/v5/account/wallet-balance"
POSITIONS_PATH = "/v5/position/list"
ORDERS_PATH = "/v5/order/realtime"
KEY_INFO_PATH = "/v5/user/query-api"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in offline tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _envelope(result: dict) -> dict:
    return {"retCode": 0, "retMsg": "OK", "time": NOW_MS, "result": result}


def _server_time_body() -> bytes:
    nanos = int(NOW.timestamp() * 1_000_000_000)
    return json.dumps(
        {
            "retCode": 0,
            "retMsg": "OK",
            "time": NOW_MS,
            "result": {"timeSecond": str(int(NOW.timestamp())), "timeNano": str(nanos)},
        }
    ).encode("utf-8")


def _key_info_body() -> bytes:
    return json.dumps(
        _envelope(
            {
                "readOnly": 1,
                "uta": 1,
                "userID": EXPECTED_USER_ID,
                "parentUid": "",
                "isMaster": True,
                "type": 1,
                "permissions": {
                    "Wallet": ["AccountTransfer"],
                    "ContractTrade": ["Order", "Position"],
                },
                "ips": [],
                "expiredAt": "2027-01-01T00:00:00Z",
                "deadlineDay": 30,
                "createdAt": "2026-01-01T00:00:00Z",
            }
        )
    ).encode("utf-8")


def _wallet_body() -> bytes:
    return json.dumps(
        _envelope(
            {
                "list": [
                    {
                        "accountType": "UNIFIED",
                        "totalEquity": "1000",
                        "totalWalletBalance": "1000",
                        "totalMarginBalance": "1000",
                        "totalAvailableBalance": "1000",
                        "totalPerpUPL": "0",
                        "coin": [
                            {
                                "coin": "USDT",
                                "equity": "1000",
                                "usdValue": "1000",
                                "walletBalance": "1000",
                                "locked": "0",
                                "unrealisedPnl": "0",
                                "cumRealisedPnl": "0",
                            }
                        ],
                    }
                ]
            }
        )
    ).encode("utf-8")


def _positions_body() -> bytes:
    return json.dumps(
        _envelope(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "positionIdx": 0,
                        "side": "Buy",
                        "size": "0.1",
                        "avgPrice": "10000",
                        "markPrice": "10000",
                        "unrealisedPnl": "0",
                        "positionValue": "1000",
                        "leverage": "1",
                    }
                ],
                "nextPageCursor": "",
            }
        )
    ).encode("utf-8")


def _orders_body() -> bytes:
    return json.dumps(
        _envelope(
            {
                "category": "linear",
                "list": [
                    {
                        "orderStatus": "New",
                        "side": "Buy",
                        "qty": "0.1",
                        "price": "10000",
                        "orderLinkId": "cid-1",
                        "orderType": "Limit",
                        "leavesQty": "0.1",
                        "cumExecQty": "0",
                        "cumExecValue": "0",
                        "avgPrice": "0",
                        "reduceOnly": False,
                        "positionIdx": 0,
                        "createdTime": NOW_MS,
                        "updatedTime": NOW_MS,
                        "orderId": "order-1",
                        "symbol": "BTCUSDT",
                    }
                ],
                "nextPageCursor": "",
            }
        )
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = {"Content-Type": "application/json"}
        self.closed = False

    def iter_content(self, chunk_size: int = 65536):
        yield self.body

    def close(self) -> None:
        self.closed = True


class RoutedSession:
    def __init__(self) -> None:
        self.requests_seen = []
        self.closed = False
        self.trust_env = True
        self.proxies = {}
        self.auth = None
        self.headers = requests.structures.CaseInsensitiveDict()

    def prepare_request(self, request):
        return request.prepare()

    def send(self, prepared, **kwargs):
        self.requests_seen.append((prepared, kwargs))
        path = urlsplit(prepared.url).path
        routes = {
            BYBIT_SERVER_TIME_PATH: _server_time_body,
            KEY_INFO_PATH: _key_info_body,
            WALLET_PATH: _wallet_body,
            POSITIONS_PATH: _positions_body,
            ORDERS_PATH: _orders_body,
        }
        builder = routes.get(path)
        if builder is None:
            return FakeResponse(b'{"retCode":1,"retMsg":"unexpected"}', status_code=404)
        return FakeResponse(builder())

    def close(self) -> None:
        self.closed = True


def _reference() -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        CREDENTIAL_ID,
        "HYRO_DEMO",
    )


def _write_credential(path: Path, *, generation: str = "gen-1", account_id: AccountId = ACCOUNT_ID) -> None:
    document = {
        "schema_version": CREDENTIAL_FILE_SCHEMA_VERSION,
        "credentials": {
            CREDENTIAL_ID: {
                "account_id": account_id.value,
                "execution_mode": ExecutionMode.EXTERNAL_SIMULATION.value,
                "execution_venue": ExecutionVenue.BYBIT_DEMO.value,
                "endpoint_profile": EndpointProfile.BYBIT_DEMO_V5.value,
                "generation": generation,
                "api_key": FABRICATED_KEY,
                "api_secret": FABRICATED_SECRET,
            }
        },
    }
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _scope() -> CredentialScope:
    return CredentialScope(
        account_id=ACCOUNT_ID,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
    )


def _binding(capabilities: ReadCapabilities) -> ReadOnlyAdapterConfiguration:
    return ReadOnlyAdapterConfiguration(
        account_id=ACCOUNT_ID,
        account_type=AccountType.PROP,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        record_lifecycle=AccountLifecycleState.REGISTERED,
        registry_revision=1,
        record_revision=1,
        credential_reference=_reference(),
        external_binding_status=ExternalBindingStatus.VERIFIED,
        external_binding_verified=True,
        external_binding_fingerprint="fp-integration-1",
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
        read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
        capabilities=capabilities,
    )


def _full_capabilities() -> ReadCapabilities:
    return ReadCapabilities(
        account_read=CapabilityState.SUPPORTED,
        positions_read=CapabilityState.SUPPORTED,
        orders_read=CapabilityState.SUPPORTED,
        server_time=CapabilityState.SUPPORTED,
    )


def _build(tmp_path: Path, *, capabilities=None):
    path = tmp_path / "credential.json"
    _write_credential(path)
    clock = FixedClock()
    provider = ReadOnlyCredentialFileProvider(str(path))
    session = RoutedSession()
    sender = BybitDemoHttpSender(
        session=session, allow_network=True, clock=clock.now
    )
    source = BybitDemoServerTimeSource(sender)
    policy = ReadOnlySafetyPolicy(
        clock=ClockPolicy(require_server_time=True)
    )
    binding = _binding(capabilities if capabilities is not None else _full_capabilities())
    readiness_state = {"value": None}
    general_read_gate = GeneralReadAuthorizationGate(
        lambda: readiness_state["value"], lambda: binding
    )
    transport = BybitV5SignedReadTransport(
        binding,
        sender,
        provider,
        clock,
        policy=policy,
        server_time_source=source.as_callable(clock),
        general_read_gate=general_read_gate,
    )
    return binding, transport, sender, session, path, clock, provider, readiness_state


def test_full_offline_path_bootstrap_then_read(tmp_path: Path):
    binding, transport, sender, session, path, clock, provider, readiness_state = _build(tmp_path)

    bootstrap = BybitDemoKeyInfoBootstrap(
        transport, expected_user_id=EXPECTED_USER_ID
    )
    key_result = bootstrap.read_key_info()
    assert key_result.succeeded is True
    assert key_result.readiness.authenticated_read_ready is True
    assert key_result.binding is not None
    readiness_state["value"] = key_result.readiness

    # Readiness must be reusable before the observation read proceeds.
    require_reusable_readiness(
        key_result.readiness, key_result.binding, now=clock.now()
    )

    adapter = BybitDemoReadAdapter(binding, transport, clock)
    observation = adapter.observe_account()

    assert observation.overall_quality is ReadDataQuality.COMPLETE
    assert observation.summary.metadata.data_quality is ReadDataQuality.COMPLETE
    assert observation.positions.metadata.data_quality is ReadDataQuality.COMPLETE
    assert observation.open_orders.metadata.data_quality is ReadDataQuality.COMPLETE
    assert observation.summary.summary is not None
    assert len(observation.positions.positions) == 1
    assert len(observation.open_orders.orders) == 1

    # The unauthenticated server-time request must never carry auth headers.
    for prepared, _kwargs in session.requests_seen:
        if urlsplit(prepared.url).path == BYBIT_SERVER_TIME_PATH:
            assert not any(
                name.lower().startswith("x-bapi-") for name in prepared.headers
            )
    paths = {urlsplit(prepared.url).path for prepared, _kwargs in session.requests_seen}
    assert {WALLET_PATH, POSITIONS_PATH, ORDERS_PATH, KEY_INFO_PATH, BYBIT_SERVER_TIME_PATH} <= paths
    sender.close()


def test_rotation_invalidates_old_readiness_binding(tmp_path: Path):
    binding, transport, sender, session, path, clock, provider, readiness_state = _build(tmp_path)
    bootstrap = BybitDemoKeyInfoBootstrap(transport, expected_user_id=EXPECTED_USER_ID)
    key_result = bootstrap.read_key_info()
    assert key_result.succeeded is True
    old_binding = key_result.binding
    assert old_binding.credential_generation == "gen-1"

    _write_credential(path, generation="gen-2")
    new_credential = provider.resolve(_reference(), _scope())
    assert new_credential.credential_generation == "gen-2"

    new_binding = ReadinessBinding(
        account_id=binding.account_id,
        credential_reference=binding.credential_reference,
        registry_revision=binding.registry_revision,
        record_revision=binding.record_revision,
        credential_generation=new_credential.credential_generation,
    )
    status = assess_readiness_reuse(
        key_result.readiness, new_binding, now=clock.now()
    )
    assert status is ReadinessReuseStatus.BINDING_MISMATCH
    sender.close()


def test_capability_gate_is_not_bypassed(tmp_path: Path):
    capabilities = ReadCapabilities(
        account_read=CapabilityState.SUPPORTED,
        positions_read=CapabilityState.UNKNOWN,
        orders_read=CapabilityState.SUPPORTED,
        server_time=CapabilityState.SUPPORTED,
    )
    binding, transport, sender, session, path, clock, provider, readiness_state = _build(
        tmp_path, capabilities=capabilities
    )
    adapter = BybitDemoReadAdapter(binding, transport, clock)
    result = adapter.list_positions()
    assert result.positions == ()
    assert result.metadata.failure is not None
    assert result.metadata.failure.code is ReadErrorCode.CAPABILITY_UNKNOWN
    paths = {urlsplit(prepared.url).path for prepared, _kwargs in session.requests_seen}
    assert POSITIONS_PATH not in paths
    sender.close()


def test_scope_mismatch_file_is_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write_credential(path, account_id=OTHER_ACCOUNT_ID)
    provider = ReadOnlyCredentialFileProvider(str(path))
    scope = CredentialScope(
        account_id=ACCOUNT_ID,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
    )
    from backend.execution.read_only_credentials import (
        CredentialProviderError,
        CredentialProviderErrorCode,
    )

    with pytest.raises(CredentialProviderError) as raised:
        provider.resolve(_reference(), scope)
    assert raised.value.code is CredentialProviderErrorCode.SCOPE_MISMATCH
