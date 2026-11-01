from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone

import pytest

from backend.accounts.models import AccountId, AccountLifecycleState, AccountType, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalBindingStatus,
)
from backend.execution.adapter_contracts import CapabilityState
from backend.execution.bybit_key_info import (
    BYBIT_DEMO_KEY_INFO_SUPPORT,
    KEY_INFO_PATH,
    ExternalBindingCheck,
    KeyInfoEnvelopeError,
    KeyInfoParseError,
    KeyInfoProjection,
    KeyInfoReadiness,
    KeyReadinessPolicy,
    ReadinessStatus,
    evaluate_key_info_readiness,
    parse_key_info_response,
    project_key_info_result,
)
from backend.execution.bybit_v5_signed_transport import (
    BybitV5SignedReadTransport,
    HttpSenderFailureKind,
    HttpSenderError,
    HttpSenderResponse,
    SignedReadRequest,
)
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadCapabilities,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
)
from backend.execution.read_only_bootstrap import BybitDemoKeyInfoBootstrap
from backend.execution.read_only_credentials import (
    ReadOnlyCredential,
)
from backend.execution.read_only_observations import ReadErrorCode
from backend.execution.read_only_policy import (
    ReadOnlySafetyPolicy,
    RetryPolicy,
    ServerTimeObservation,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")
FABRICATED_API_KEY = "fabricated-api-key-must-not-appear"
FABRICATED_SECRET = "fabricated-secret-must-not-appear"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in offline tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class FakeSender:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.requests: list[SignedReadRequest] = []

    def send(self, request: SignedReadRequest) -> HttpSenderResponse:
        self.requests.append(request)
        result = self._handler(request)
        if isinstance(result, Exception):
            raise result
        return result


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, reference, scope):
        self.calls.append((reference, scope))
        return ReadOnlyCredential(
            reference,
            "fabricated-key-not-real",
            "fabricated-secret-not-real",
            scope=scope,
            credential_generation="fabricated-generation-1",
        )


def _reference() -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "fabricated-bundle",
        "HYRO_DEMO",
    )


def _binding() -> ReadOnlyAdapterConfiguration:
    return ReadOnlyAdapterConfiguration(
        account_id=ACCOUNT_ID,
        account_type=AccountType.PROP,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        record_lifecycle=AccountLifecycleState.REGISTERED,
        registry_revision=7,
        record_revision=3,
        credential_reference=_reference(),
        external_binding_status=ExternalBindingStatus.VERIFIED,
        external_binding_verified=True,
        external_binding_fingerprint="fabricated-fingerprint",
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
        read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
        capabilities=ReadCapabilities(
            account_read=CapabilityState.SUPPORTED,
            positions_read=CapabilityState.SUPPORTED,
            orders_read=CapabilityState.SUPPORTED,
            server_time=CapabilityState.SUPPORTED,
        ),
    )


def _result(**overrides) -> dict:
    values = {
        "id": "fabricated-id",
        "note": "fabricated-note",
        "apiKey": FABRICATED_API_KEY,
        "readOnly": 1,
        "secret": FABRICATED_SECRET,
        "permissions": {
            "ContractTrade": ["Order", "Position"],
            "Wallet": ["AccountTransfer"],
            "Spot": [],
            "Options": [],
            "Derivatives": [],
            "Exchange": [],
            "Earn": [],
            "FiatP2P": [],
            "FiatConvertBroker": [],
            "FiatGlobalPay": [],
            "FiatBitPay": [],
            "BitCard": [],
            "ByXPost": [],
            "Affiliate": [],
            "BlockTrade": [],
            "NFT": [],
            "CopyTrading": [],
        },
        "ips": [],
        "type": 1,
        "deadlineDay": -2,
        "expiredAt": "2027-01-01T00:00:00Z",
        "createdAt": "2025-10-13T03:20:45Z",
        "uta": 1,
        "userID": 1448939,
        "isMaster": True,
        "parentUid": "0",
    }
    values.update(overrides)
    return values


def _envelope(**overrides) -> dict:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": _result(**overrides),
        "retExtInfo": {},
        "time": 1767225600000,
    }


def _projection(**overrides) -> KeyInfoProjection:
    return parse_key_info_response(_envelope(**overrides))


def _readiness(projection=None, **kwargs):
    return evaluate_key_info_readiness(
        projection or _projection(),
        clock=FixedClock(),
        **kwargs,
    )


def _transport_for(handler, *, binding=None, policy=None):
    sender = FakeSender(handler)
    transport = BybitV5SignedReadTransport(
        binding or _binding(),
        sender,
        FakeProvider(),
        FixedClock(),
        policy=policy or ReadOnlySafetyPolicy(),
        server_time_source=lambda: ServerTimeObservation(NOW, NOW),
    )
    return transport, sender


def _json_response(payload, *, status: int = 200) -> HttpSenderResponse:
    return HttpSenderResponse(status, json.dumps(payload).encode("utf-8"), NOW)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def test_projection_retains_only_safe_fields_and_never_api_key_or_secret():
    projection = _projection()
    assert projection.read_only == 1
    assert projection.uta == 1
    assert projection.user_id == 1448939
    assert projection.parent_uid == "0"
    assert projection.is_master is True
    assert projection.ip_restricted is False
    assert projection.ip_count == 0
    assert projection.expiry_reported is True
    assert projection.permissions == (
        ("Affiliate", ()),
        ("BitCard", ()),
        ("BlockTrade", ()),
        ("ByXPost", ()),
        ("ContractTrade", ("Order", "Position")),
        ("CopyTrading", ()),
        ("Derivatives", ()),
        ("Earn", ()),
        ("Exchange", ()),
        ("FiatBitPay", ()),
        ("FiatConvertBroker", ()),
        ("FiatGlobalPay", ()),
        ("FiatP2P", ()),
        ("NFT", ()),
        ("Options", ()),
        ("Spot", ()),
        ("Wallet", ("AccountTransfer",)),
    )
    for rendered in (repr(projection), str(projection.to_dict()), json.dumps(projection.to_dict())):
        assert FABRICATED_API_KEY not in rendered
        assert FABRICATED_SECRET not in rendered
    assert "ips" not in projection.to_dict()


def test_projection_never_renders_raw_ips():
    projection = _projection(ips=["203.0.113.10", "198.51.100.7"])
    assert projection.ip_restricted is True
    assert projection.ip_count == 2
    assert "203.0.113.10" not in repr(projection)
    assert "203.0.113.10" not in json.dumps(projection.to_dict())


def test_projection_marks_missing_and_invalid_fields_instead_of_guessing():
    projection = project_key_info_result(
        {
            "readOnly": "1",
            "uta": True,
            "permissions": "not-a-mapping",
            "ips": "not-a-list",
            "expiredAt": "not-a-date",
        }
    )
    assert projection.read_only is None
    assert projection.uta is None
    assert projection.ip_restricted is None
    assert projection.expiry_reported is False
    for name in ("readOnly", "uta", "permissions", "ips", "expiredAt"):
        assert name in projection.invalid_fields
    for name in ("userID", "parentUid", "isMaster", "type", "deadlineDay", "createdAt"):
        assert name in projection.missing_fields


def test_projection_distinguishes_unknown_permissions():
    projection = _projection(
        permissions={
            "ContractTrade": ["Order", "Position", "FutureWrite"],
            "Wallet": ["AccountTransfer"],
            "BrandNewScope": ["Something"],
        }
    )
    assert projection.unknown_scopes == ("BrandNewScope",)
    assert projection.unknown_permission_tokens == ("ContractTrade:FutureWrite",)


def test_key_info_envelope_errors_are_fixed_text():
    with pytest.raises(KeyInfoEnvelopeError) as caught:
        parse_key_info_response({"retCode": 10005, "retMsg": "raw venue text", "result": {}})
    assert caught.value.ret_code == 10005
    assert "raw venue text" not in str(caught.value)
    with pytest.raises(KeyInfoParseError):
        parse_key_info_response({"retCode": 0, "retMsg": "OK", "result": []})
    with pytest.raises(KeyInfoParseError):
        parse_key_info_response({"retMsg": "OK", "result": {}})


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readiness_passes_key_level_but_never_claims_external_binding():
    readiness = _readiness()
    assert readiness.key_level_status is ReadinessStatus.PASS
    assert readiness.read_only_status is ReadinessStatus.PASS
    assert readiness.unified_account_status is ReadinessStatus.PASS
    assert readiness.permission_status is ReadinessStatus.PASS
    assert readiness.expiry_status is ReadinessStatus.PASS
    assert readiness.demo_support_status is ReadinessStatus.PASS
    assert readiness.ip_status is ReadinessStatus.PASS
    assert readiness.external_binding_check is ExternalBindingCheck.NOT_CHECKED
    assert readiness.authenticated_read_ready is False
    assert "TRANSFER_SCOPED_PERMISSION_PRESENT" in readiness.reasons
    assert "EXTERNAL_BINDING_NOT_CHECKED" in readiness.reasons
    assert readiness.demo_key_info_support is BYBIT_DEMO_KEY_INFO_SUPPORT


def test_read_only_uses_exact_zero_one_and_not_truthiness():
    blocked = _readiness(_projection(readOnly=0))
    assert blocked.read_only_status is ReadinessStatus.BLOCK
    assert blocked.key_level_status is ReadinessStatus.BLOCK
    missing = _readiness(_projection(readOnly=None))
    assert missing.read_only_status is ReadinessStatus.UNKNOWN
    invalid = _readiness(_projection(readOnly="1"))
    assert invalid.read_only_status is ReadinessStatus.UNKNOWN


def test_unified_account_and_permission_readiness():
    assert _readiness(_projection(uta=0)).unified_account_status is ReadinessStatus.BLOCK
    assert _readiness(_projection(uta=None)).unified_account_status is ReadinessStatus.UNKNOWN
    missing_wallet = _readiness(_projection(permissions={"ContractTrade": ["Order", "Position"]}))
    assert missing_wallet.permission_status is ReadinessStatus.BLOCK
    missing_position = _readiness(
        _projection(permissions={"ContractTrade": ["Order"], "Wallet": ["AccountTransfer"]})
    )
    assert missing_position.permission_status is ReadinessStatus.BLOCK
    blocked = _readiness(_projection(permissions={"ContractTrade": ["Order", "Position"], "Wallet": ["Withdraw"]}))
    assert blocked.permission_status is ReadinessStatus.BLOCK
    unknown = _readiness(
        _projection(permissions={"ContractTrade": ["Order", "Position"], "Wallet": ["AccountTransfer"], "NewScope": []})
    )
    assert unknown.permission_status is ReadinessStatus.UNKNOWN


def test_expiry_readiness():
    past = _readiness(_projection(expiredAt="2025-01-01T00:00:00Z"))
    assert past.expiry_status is ReadinessStatus.BLOCK
    assert "KEY_EXPIRED" in past.reasons
    missing = _readiness(_projection(expiredAt=""))
    assert missing.expiry_status is ReadinessStatus.UNKNOWN
    placeholder = _readiness(_projection(expiredAt="1970-01-01T00:00:00Z"))
    assert placeholder.expiry_status is ReadinessStatus.UNKNOWN


def test_ip_and_external_binding_gate_authenticated_readiness():
    unrestricted = _readiness()
    assert unrestricted.ip_status is ReadinessStatus.PASS
    assert unrestricted.authenticated_read_ready is False

    restricted = _readiness(_projection(ips=["203.0.113.10"]))
    assert restricted.ip_status is ReadinessStatus.UNKNOWN
    assert "EGRESS_IP_NOT_PROVIDED" in restricted.reasons
    assert restricted.authenticated_read_ready is False

    matched = _readiness(
        _projection(ips=["203.0.113.10"]),
        expected_user_id=1448939,
        expected_parent_uid="0",
        expected_egress_ip="203.0.113.10",
    )
    assert matched.ip_status is ReadinessStatus.PASS
    assert matched.external_binding_check is ExternalBindingCheck.MATCHED
    assert matched.authenticated_read_ready is True

    mismatched = _readiness(
        _projection(ips=["203.0.113.10"]),
        expected_user_id=1448939,
        expected_egress_ip="198.51.100.7",
    )
    assert mismatched.ip_status is ReadinessStatus.BLOCK
    assert mismatched.authenticated_read_ready is False

    wrong_account = _readiness(expected_user_id=9999999)
    assert wrong_account.external_binding_check is ExternalBindingCheck.MISMATCH
    assert wrong_account.authenticated_read_ready is False


def test_demo_support_unknown_or_unsupported_never_passes():
    unknown = _readiness(demo_key_info_support=CapabilityState.UNKNOWN)
    assert unknown.demo_support_status is ReadinessStatus.UNKNOWN
    assert unknown.key_level_status is ReadinessStatus.UNKNOWN
    assert unknown.authenticated_read_ready is False

    unsupported = _readiness(demo_key_info_support=CapabilityState.UNSUPPORTED)
    assert unsupported.demo_support_status is ReadinessStatus.BLOCK
    assert unsupported.key_level_status is ReadinessStatus.BLOCK
    assert unsupported.authenticated_read_ready is False

    without = KeyInfoReadiness.without_projection(
        demo_key_info_support=CapabilityState.UNKNOWN
    )
    assert without.key_level_status is ReadinessStatus.UNKNOWN
    assert without.authenticated_read_ready is False


# ---------------------------------------------------------------------------
# Bootstrap scope
# ---------------------------------------------------------------------------


def test_bootstrap_rejects_demo_unknown_before_any_send():
    transport, sender = _transport_for(lambda request: _json_response(_envelope()))
    bootstrap = BybitDemoKeyInfoBootstrap(
        transport, demo_key_info_support=CapabilityState.UNKNOWN
    )
    result = bootstrap.read_key_info()
    assert result.succeeded is False
    assert result.failure.code is ReadErrorCode.CAPABILITY_UNKNOWN
    assert result.readiness is not None
    assert result.readiness.authenticated_read_ready is False
    assert sender.requests == []

    unsupported = BybitDemoKeyInfoBootstrap(
        transport, demo_key_info_support=CapabilityState.UNSUPPORTED
    ).read_key_info()
    assert unsupported.failure.code is ReadErrorCode.UNSUPPORTED_CAPABILITY
    assert sender.requests == []


def test_bootstrap_is_restricted_to_the_key_info_endpoint():
    bootstrap = BybitDemoKeyInfoBootstrap(_transport_for(lambda request: _json_response(_envelope()))[0])
    assert bootstrap.allowed_paths == frozenset({KEY_INFO_PATH})
    BybitDemoKeyInfoBootstrap.require_allowed_path(KEY_INFO_PATH)
    with pytest.raises(ValueError):
        BybitDemoKeyInfoBootstrap.require_allowed_path("/v5/position/list")
    for name in ("list_positions", "list_open_orders", "get_account_summary", "observe_account", "submit_order"):
        assert not hasattr(bootstrap, name)


def test_bootstrap_reads_only_key_info_and_returns_safe_readiness():
    transport, sender = _transport_for(lambda request: _json_response(_envelope()))
    bootstrap = BybitDemoKeyInfoBootstrap(
        transport,
        expected_user_id=1448939,
        expected_parent_uid="0",
        expected_egress_ip="203.0.113.10",
    )
    result = bootstrap.read_key_info()
    assert result.succeeded is True
    assert result.failure is None
    assert result.projection is not None
    assert FABRICATED_API_KEY not in repr(result)
    assert FABRICATED_SECRET not in repr(result)
    assert result.readiness.external_binding_check is ExternalBindingCheck.MATCHED
    assert result.readiness.ip_status is ReadinessStatus.PASS
    assert result.authenticated_read_ready is True
    assert len(sender.requests) == 1
    signed = sender.requests[0]
    assert signed.path == KEY_INFO_PATH
    assert signed.query == ""
    assert signed.header("X-BAPI-SIGN")


def test_bootstrap_stops_on_auth_failure_without_retry():
    transport, sender = _transport_for(
        lambda request: _json_response({"retCode": 10003, "retMsg": "raw", "result": {}}, status=401),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
    )
    result = BybitDemoKeyInfoBootstrap(transport).read_key_info()
    assert result.succeeded is False
    assert result.failure.code is ReadErrorCode.AUTHENTICATION_FAILED
    assert len(sender.requests) == 1


def test_bootstrap_maps_malformed_and_venue_failures_without_raw_text():
    malformed_transport, malformed_sender = _transport_for(
        lambda request: HttpSenderResponse(200, b"not-json", NOW)
    )
    malformed = BybitDemoKeyInfoBootstrap(malformed_transport).read_key_info()
    assert malformed.failure.code is ReadErrorCode.MALFORMED_RESPONSE
    assert len(malformed_sender.requests) == 1

    venue_transport, venue_sender = _transport_for(
        lambda request: _json_response({"retCode": 10005, "retMsg": "raw venue text", "result": {}})
    )
    venue = BybitDemoKeyInfoBootstrap(venue_transport).read_key_info()
    assert venue.failure.code is ReadErrorCode.PERMISSION_DENIED
    assert venue.failure.safe_message == "read permission denied"
    assert "raw venue text" not in repr(venue)
    assert len(venue_sender.requests) == 1


def test_bootstrap_rejects_invalid_expectations_and_missing_transport():
    transport, _ = _transport_for(lambda request: _json_response(_envelope()))
    with pytest.raises(TypeError):
        BybitDemoKeyInfoBootstrap(None)
    with pytest.raises(TypeError):
        BybitDemoKeyInfoBootstrap(transport, expected_user_id=True)
    with pytest.raises(TypeError):
        BybitDemoKeyInfoBootstrap(transport, expected_parent_uid=0)
    with pytest.raises(TypeError):
        BybitDemoKeyInfoBootstrap(transport, demo_key_info_support="SUPPORTED")
