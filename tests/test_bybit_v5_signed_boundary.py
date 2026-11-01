from __future__ import annotations

import hashlib
import hmac
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.accounts.models import AccountId, AccountLifecycleState, AccountType, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalBindingStatus,
)
from backend.execution.bybit_v5_signing import (
    SigningError,
    canonical_query,
    percent_encode,
    sign_get,
    utc_timestamp_ms,
    validate_recv_window,
)
from backend.execution.bybit_v5_signed_transport import (
    BybitV5SignedReadTransport,
    HttpSenderError,
    HttpSenderFailureKind,
    HttpSenderResponse,
    SignedReadRequest,
)
from backend.execution.bybit_key_info import (
    ExternalBindingCheck,
    GeneralReadAuthorizationGate,
    KEY_INFO_PATH,
    KeyInfoReadiness,
    ReadinessBinding,
    ReadinessStatus,
)
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
)
from backend.execution.read_only_credentials import (
    CredentialProviderError,
    CredentialProviderErrorCode,
    CredentialScope,
    ReadOnlyCredential,
)
from backend.execution.read_only_policy import (
    BYBIT_DEMO_HOST,
    ClockPolicy,
    EgressPolicy,
    PolicyErrorCode,
    ReadOnlyPolicyError,
    ReadOnlySafetyPolicy,
    RetryPolicy,
    ServerTimeObservation,
)
from backend.execution.read_only_observations import ReadDataQuality, ReadErrorCode
from backend.execution.read_only_transport import (
    ReadOnlyRequest,
    ReadOnlyResponse,
    ReadTransportError,
    ReadTransportFailureKind,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "bybit_demo_read"
ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")
OTHER_ACCOUNT_ID = AccountId("acc_22222222222242228222222222222222")


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
    def __init__(self, *, reference=None, credential=None, error=None) -> None:
        self.reference = reference
        self.credential = credential
        self.error = error
        self.calls = []

    def resolve(self, reference, scope):
        self.calls.append((reference, scope))
        if self.error is not None:
            raise self.error
        if self.reference is not None and reference != self.reference:
            raise CredentialProviderError(CredentialProviderErrorCode.REFERENCE_UNKNOWN)
        if self.credential is not None:
            return self.credential
        return ReadOnlyCredential(
            reference,
            "fabricated-key-not-real",
            "fabricated-secret-not-real",
            scope=scope,
            credential_generation="fabricated-generation-1",
        )


class SequenceProvider:
    def __init__(self, generations) -> None:
        self.generations = list(generations)
        self.current = self.generations[-1]
        self.calls = []

    def resolve(self, reference, scope):
        self.calls.append((reference, scope))
        if self.generations:
            self.current = self.generations.pop(0)
        return ReadOnlyCredential(
            reference,
            "fabricated-key-not-real",
            "fabricated-secret-not-real",
            scope=scope,
            credential_generation=self.current,
        )


def _reference(credential_id: str = "fabricated-bundle") -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        credential_id,
        "HYRO_DEMO",
    )


def _capabilities(**overrides) -> ReadCapabilities:
    values = {
        "account_read": "SUPPORTED",
        "positions_read": "SUPPORTED",
        "orders_read": "SUPPORTED",
        "server_time": "SUPPORTED",
    }
    values.update(overrides)
    return ReadCapabilities(**values)


def _binding(**overrides) -> ReadOnlyAdapterConfiguration:
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


def _json_response(payload, *, status: int = 200) -> HttpSenderResponse:
    return HttpSenderResponse(status, json.dumps(payload).encode("utf-8"), NOW)


def _ok_body(result=None) -> dict:
    return {"retCode": 0, "retMsg": "OK", "result": result or {}, "time": 1767225600000}


def _server_time(value: datetime = NOW, observed_at: datetime = NOW) -> ServerTimeObservation:
    return ServerTimeObservation(value, observed_at)


def _readiness(
    binding: ReadOnlyAdapterConfiguration,
    generation: str = "fabricated-generation-1",
) -> KeyInfoReadiness:
    readiness_binding = ReadinessBinding(
        account_id=binding.account_id,
        credential_reference=binding.credential_reference,
        registry_revision=binding.registry_revision,
        record_revision=binding.record_revision,
        credential_generation=generation,
    )
    return KeyInfoReadiness(
        key_level_status=ReadinessStatus.PASS,
        read_only_status=ReadinessStatus.PASS,
        unified_account_status=ReadinessStatus.PASS,
        permission_status=ReadinessStatus.PASS,
        expiry_status=ReadinessStatus.PASS,
        demo_support_status=ReadinessStatus.PASS,
        ip_status=ReadinessStatus.PASS,
        external_binding_check=ExternalBindingCheck.MATCHED,
        authenticated_read_ready=True,
        binding=readiness_binding,
        observed_at=NOW,
        source_time=NOW,
    )


def _general_read_gate(
    binding: ReadOnlyAdapterConfiguration,
    generation: str = "fabricated-generation-1",
) -> GeneralReadAuthorizationGate:
    readiness = _readiness(binding, generation)
    return GeneralReadAuthorizationGate(lambda: readiness, lambda: binding)


def _transport(
    handler,
    *,
    binding=None,
    provider=None,
    policy=None,
    clock=None,
    server_time_source="default",
    sleep=None,
    budget=None,
    general_read_gate="default",
):
    sender = FakeSender(handler)
    credential_provider = provider or FakeProvider()
    effective_binding = binding or _binding()
    if server_time_source == "default":
        server_time_source = lambda: _server_time()
    if general_read_gate == "default":
        general_read_gate = _general_read_gate(effective_binding)
    transport = BybitV5SignedReadTransport(
        effective_binding,
        sender,
        credential_provider,
        clock or FixedClock(),
        policy=policy or ReadOnlySafetyPolicy(),
        server_time_source=server_time_source,
        sleep=sleep,
        budget=budget,
        general_read_gate=general_read_gate,
    )
    return transport, sender, credential_provider


def _request(path: str = ACCOUNT_SUMMARY_PATH, query=()) -> ReadOnlyRequest:
    return ReadOnlyRequest("GET", path, query)


def _decode_query(request: SignedReadRequest) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(request.query, keep_blank_values=True, strict_parsing=True))


# ---------------------------------------------------------------------------
# General-read readiness authorization
# ---------------------------------------------------------------------------


def test_general_read_without_gate_is_rejected_before_send():
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), general_read_gate=None
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_stale_readiness_is_rejected_before_send():
    later = NOW + timedelta(seconds=6)
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        clock=FixedClock(later),
        server_time_source=lambda: _server_time(later, later),
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_credential_generation_mismatch_is_rejected_before_send():
    provider = SequenceProvider(["fabricated-generation-2"])
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), provider=provider
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_current_binding_revision_change_is_rejected_before_send():
    binding = _binding()
    changed = _binding(registry_revision=8, record_revision=4)
    gate = GeneralReadAuthorizationGate(
        lambda: _readiness(binding), lambda: changed
    )
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        binding=binding,
        general_read_gate=gate,
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_current_binding_account_change_is_rejected_before_send():
    binding = _binding()
    changed = _binding(account_id=OTHER_ACCOUNT_ID)
    gate = GeneralReadAuthorizationGate(
        lambda: _readiness(binding), lambda: changed
    )
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        binding=binding,
        general_read_gate=gate,
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_disabled_account_current_source_is_rejected_before_send():
    binding = _binding()
    gate = GeneralReadAuthorizationGate(lambda: _readiness(binding), lambda: None)
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        binding=binding,
        general_read_gate=gate,
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_current_binding_snapshot_failure_is_rejected_before_send():
    binding = _binding()

    def unavailable():
        raise RuntimeError("fabricated snapshot unavailable")

    gate = GeneralReadAuthorizationGate(lambda: _readiness(binding), unavailable)
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        binding=binding,
        general_read_gate=gate,
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert sender.requests == []


def test_credential_rotation_during_response_is_rejected_after_send():
    provider = SequenceProvider(
        ["fabricated-generation-1", "fabricated-generation-2"]
    )
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), provider=provider
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert len(sender.requests) == 1


def test_binding_change_during_response_is_rejected_after_send():
    binding = _binding()
    state = {"binding": binding}
    gate = GeneralReadAuthorizationGate(
        lambda: _readiness(binding), lambda: state["binding"]
    )

    def handler(request):
        state["binding"] = _binding(registry_revision=8, record_revision=4)
        return _json_response(_ok_body())

    transport, sender, _ = _transport(
        handler, binding=binding, general_read_gate=gate
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert len(sender.requests) == 1


def test_rotation_between_retry_attempts_blocks_second_send():
    provider = SequenceProvider(
        ["fabricated-generation-1", "fabricated-generation-2"]
    )
    transport, sender, _ = _transport(
        lambda request: HttpSenderError(HttpSenderFailureKind.TIMEOUT),
        provider=provider,
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2)),
    )

    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())

    assert caught.value.kind is ReadTransportFailureKind.READINESS_REJECTED
    assert len(sender.requests) == 1


def test_key_info_bootstrap_path_is_allowed_without_general_read_gate():
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), general_read_gate=None
    )

    response = transport.send(_request(KEY_INFO_PATH))

    assert response.status_code == 200
    assert len(sender.requests) == 1


# ---------------------------------------------------------------------------
# Signing / canonical query
# ---------------------------------------------------------------------------


def test_canonical_query_preserves_order_and_encodes_once():
    pairs = (("category", "linear"), ("symbol", "BTC USDT/PERP"), ("note", "a+b/c==?&"))
    encoded = canonical_query(pairs)
    assert encoded == (
        "category=linear&symbol=BTC%20USDT%2FPERP&note=a%2Bb%2Fc%3D%3D%3F%26"
    )
    assert "%25" not in encoded
    assert percent_encode("A-Z_a.z~") == "A-Z_a.z~"


def test_canonical_query_preserves_pre_encoded_cursor_without_double_encoding():
    cursor = "page_args%3Dfd4300ae%26symbol%3D6%26"
    encoded = canonical_query((("category", "linear"), ("cursor", cursor)))
    assert encoded == f"category=linear&cursor={cursor}"
    assert "%253D" not in encoded
    for bad in ("a&b", "a=b", "a b", "a%2", "a%ZZ", "", "a#b"):
        with pytest.raises(SigningError):
            canonical_query((("cursor", bad),))
    with pytest.raises(SigningError):
        canonical_query((("cursor", "abc"),), pre_encoded_keys=frozenset({"symbol"}))


def test_transport_sends_the_exact_pre_encoded_cursor_it_signs():
    cursor = "page_args%3Dfd4300ae%26symbol%3D6%26"
    transport, sender, _ = _transport(lambda request: _json_response(_ok_body()))
    transport.send(_request(POSITIONS_PATH, (("category", "linear"), ("cursor", cursor))))
    signed = sender.requests[0]
    assert signed.query == f"category=linear&cursor={cursor}"
    message = (
        signed.header("X-BAPI-TIMESTAMP")
        + signed.header("X-BAPI-API-KEY")
        + signed.header("X-BAPI-RECV-WINDOW")
        + signed.query
    )
    expected = hmac.new(
        b"fabricated-secret-not-real", message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert signed.header("X-BAPI-SIGN") == expected


def test_transport_maps_malformed_cursor_to_policy_rejection_before_sender():
    transport, sender, _ = _transport(lambda request: _json_response(_ok_body()))
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request(POSITIONS_PATH, (("cursor", "bad&cursor"),)))
    assert caught.value.kind is ReadTransportFailureKind.POLICY_REJECTED
    assert sender.requests == []


def test_canonical_query_rejects_duplicates_and_bad_shapes():
    with pytest.raises(SigningError):
        canonical_query((("category", "linear"), ("category", "inverse")))
    with pytest.raises(SigningError):
        canonical_query((("a",),))
    with pytest.raises(SigningError):
        canonical_query(((1, "b"),))
    with pytest.raises(SigningError):
        canonical_query((("", "b"),))


def test_sign_get_known_independent_vector():
    signature = sign_get(
        api_secret="fabricated-secret-not-real",
        api_key="fabricated-key-not-real",
        timestamp_ms=1700000000000,
        recv_window_ms=5000,
        encoded_query="category=linear&symbol=BTCUSDT&limit=200",
    )
    assert signature == "69926bcae8b2881cd8d4ab1c222a18f5cad78d0dac75461a2e10dc71c79d6098"
    message = (
        "1700000000000fabricated-key-not-real5000"
        "category=linear&symbol=BTCUSDT&limit=200"
    )
    assert signature == hmac.new(
        b"fabricated-secret-not-real", message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def test_sign_get_special_character_vector():
    query = canonical_query(
        (("category", "linear"), ("symbol", "BTC USDT/PERP"), ("note", "a+b/c==?&"))
    )
    signature = sign_get(
        api_secret="fabricated-secret-not-real",
        api_key="fabricated-key-not-real",
        timestamp_ms=1700000000000,
        recv_window_ms=5000,
        encoded_query=query,
    )
    assert signature == "da4e3bd23ca4a66b1ac25032dc5ca8097b2f15275176f12253f8fbd1c0f0e0df"


def test_recv_window_and_timestamp_validation():
    assert validate_recv_window(5000) == 5000
    for value in (True, "5000", None, 999, 60001, 0):
        with pytest.raises(SigningError):
            validate_recv_window(value)
    with pytest.raises(SigningError):
        utc_timestamp_ms(None)
    with pytest.raises(SigningError):
        utc_timestamp_ms(type("BadClock", (), {"now": lambda self: datetime(2026, 1, 1)})())
    assert utc_timestamp_ms(FixedClock()) == 1767225600000


# ---------------------------------------------------------------------------
# Egress / policy
# ---------------------------------------------------------------------------


def test_egress_policy_is_demo_host_get_only_and_subset_of_known_paths():
    policy = EgressPolicy()
    assert policy.host == BYBIT_DEMO_HOST
    assert policy.method == "GET"
    assert policy.allow_redirects is False
    assert policy.allow_proxy is False
    with pytest.raises(ValueError):
        EgressPolicy(allowed_paths=frozenset({"/v5/order/create"}))
    with pytest.raises(ValueError):
        EgressPolicy(timeout_seconds=0)
    with pytest.raises(ValueError):
        EgressPolicy(max_response_bytes=0)
    on_mainnet = _request()
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.validate_signed_parts(method="GET", host="api.bybit.com", path=on_mainnet.path)
    assert caught.value.code is PolicyErrorCode.HOST_NOT_ALLOWED
    with pytest.raises(ReadOnlyPolicyError):
        policy.validate_signed_parts(method="POST", host=BYBIT_DEMO_HOST, path=on_mainnet.path)
    with pytest.raises(ReadOnlyPolicyError):
        policy.validate_request(_request("/v5/order/create"))


def test_signed_request_forbids_redirects_proxy_and_malformed_headers():
    transport, sender, _ = _transport(lambda request: _json_response(_ok_body()))
    transport.send(_request())
    signed = sender.requests[0]
    assert signed.host == BYBIT_DEMO_HOST
    assert signed.allow_redirects is False
    assert signed.allow_proxy is False
    assert signed.timeout_seconds == 5.0
    assert signed.max_response_bytes == 1_000_000
    assert "fabricated-key-not-real" not in repr(signed)
    assert "fabricated-secret-not-real" not in repr(signed)
    assert signed.header("X-BAPI-SIGN") not in repr(signed)
    with pytest.raises(ValueError):
        SignedReadRequest(
            "GET", BYBIT_DEMO_HOST, ACCOUNT_SUMMARY_PATH, "", signed.headers, 5.0, 1000,
            allow_redirects=True,
        )
    with pytest.raises(ValueError):
        SignedReadRequest(
            "GET", BYBIT_DEMO_HOST, ACCOUNT_SUMMARY_PATH, "", signed.headers, 5.0, 1000,
            allow_proxy=True,
        )
    with pytest.raises(ValueError):
        SignedReadRequest("GET", "api.bybit.com", ACCOUNT_SUMMARY_PATH, "", signed.headers, 5.0, 1000)
    with pytest.raises(ValueError):
        SignedReadRequest(
            "GET", BYBIT_DEMO_HOST, ACCOUNT_SUMMARY_PATH, "", signed.headers + (("X-Extra", "1"),), 5.0, 1000
        )
    with pytest.raises(ValueError):
        SignedReadRequest(
            "GET", BYBIT_DEMO_HOST, ACCOUNT_SUMMARY_PATH, "", signed.headers[:-1], 5.0, 1000
        )


def test_transport_rejects_non_allowlisted_path_before_sender():
    transport, sender, _ = _transport(lambda request: _json_response(_ok_body()))
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request("/v5/order/create"))
    assert caught.value.kind is ReadTransportFailureKind.POLICY_REJECTED
    assert sender.requests == []


def test_transport_construction_has_no_io_and_no_execution_surface():
    sender = FakeSender(lambda request: _json_response(_ok_body()))
    provider = FakeProvider()
    clock = FixedClock()
    transport = BybitV5SignedReadTransport(
        _binding(),
        sender,
        provider,
        clock,
        policy=ReadOnlySafetyPolicy(),
        server_time_source=lambda: _server_time(),
    )
    assert sender.requests == []
    assert provider.calls == []
    assert transport.budget.used == 0
    for name in ("submit_order", "cancel_order", "close_position", "place_order", "amend_order"):
        assert not hasattr(transport, name)
    assert not hasattr(transport, "runtime_authority")


def test_transport_requires_explicit_sender_provider_and_clock():
    sender = FakeSender(lambda request: _json_response(_ok_body()))
    provider = FakeProvider()
    with pytest.raises(TypeError):
        BybitV5SignedReadTransport(
            _binding(), None, provider, FixedClock(), policy=ReadOnlySafetyPolicy()
        )
    with pytest.raises(TypeError):
        BybitV5SignedReadTransport(
            _binding(), sender, None, FixedClock(), policy=ReadOnlySafetyPolicy()
        )
    with pytest.raises(TypeError):
        BybitV5SignedReadTransport(
            _binding(), sender, provider, None, policy=ReadOnlySafetyPolicy()
        )
    with pytest.raises(ValueError):
        _transport(
            lambda request: _json_response(_ok_body()),
            binding=_binding(execution_mode=ExecutionMode.PAPER, execution_venue=ExecutionVenue.INTERNAL_PAPER),
        )


# ---------------------------------------------------------------------------
# Clock policy
# ---------------------------------------------------------------------------


def test_clock_policy_fresh_stale_skew_and_unknown():
    policy = ClockPolicy(require_server_time=True)
    assert policy.require_fresh(_server_time(), NOW).fresh is True
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(None, NOW)
    assert caught.value.code is PolicyErrorCode.CLOCK_OBSERVATION_UNAVAILABLE
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(_server_time(observed_at=NOW - timedelta(seconds=10)), NOW)
    assert caught.value.code is PolicyErrorCode.CLOCK_OBSERVATION_STALE
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(_server_time(value=NOW - timedelta(seconds=10)), NOW)
    assert caught.value.code is PolicyErrorCode.CLOCK_SKEW_EXCEEDED


def test_transport_requires_fresh_server_time_observation():
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), server_time_source=None
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.CLOCK_REJECTED
    assert sender.requests == []

    stale_transport, stale_sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        server_time_source=lambda: _server_time(observed_at=NOW - timedelta(seconds=10)),
    )
    with pytest.raises(ReadTransportError) as caught:
        stale_transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.CLOCK_REJECTED
    assert stale_sender.requests == []


# ---------------------------------------------------------------------------
# Signed request construction / sender contract
# ---------------------------------------------------------------------------


def test_transport_signs_exact_sent_query_with_injected_clock_and_provider():
    transport, sender, provider = _transport(
        lambda request: _json_response(_ok_body()),
    )
    response = transport.send(_request(POSITIONS_PATH, (("category", "linear"), ("limit", "200"))))
    assert isinstance(response, ReadOnlyResponse)
    assert response.status_code == 200
    signed = sender.requests[0]
    assert signed.path == POSITIONS_PATH
    assert signed.query == "category=linear&limit=200"
    assert _decode_query(signed) == {"category": "linear", "limit": "200"}
    assert signed.header("X-BAPI-TIMESTAMP") == "1767225600000"
    assert signed.header("X-BAPI-RECV-WINDOW") == "5000"
    assert signed.header("X-BAPI-API-KEY") == "fabricated-key-not-real"
    expected = hmac.new(
        b"fabricated-secret-not-real",
        b"1767225600000fabricated-key-not-real5000category=linear&limit=200",
        hashlib.sha256,
    ).hexdigest()
    assert signed.header("X-BAPI-SIGN") == expected
    assert provider.calls[0][1] == CredentialScope(
        ACCOUNT_ID, ExecutionMode.EXTERNAL_SIMULATION, ExecutionVenue.BYBIT_DEMO, EndpointProfile.BYBIT_DEMO_V5
    )


def test_provider_error_and_mismatched_credential_stop_before_sender():
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        provider=FakeProvider(error=CredentialProviderError(CredentialProviderErrorCode.UNAVAILABLE)),
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.CREDENTIAL_REJECTED
    assert sender.requests == []

    wrong = ReadOnlyCredential(
        _reference("other-bundle"),
        "fabricated-key-not-real",
        "fabricated-secret-not-real",
        scope=CredentialScope(
            ACCOUNT_ID,
            ExecutionMode.EXTERNAL_SIMULATION,
            ExecutionVenue.BYBIT_DEMO,
            EndpointProfile.BYBIT_DEMO_V5,
        ),
    )
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), provider=FakeProvider(credential=wrong)
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.CREDENTIAL_REJECTED
    assert sender.requests == []

    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()), provider=FakeProvider(credential=object())
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.CREDENTIAL_REJECTED
    assert sender.requests == []


# ---------------------------------------------------------------------------
# Retry / budget / response bounds
# ---------------------------------------------------------------------------


def test_retry_budget_and_bounded_retries():
    def timeout(request):
        return HttpSenderError(HttpSenderFailureKind.TIMEOUT)

    transport, sender, _ = _transport(
        timeout,
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2)),
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.TIMEOUT
    assert len(sender.requests) == 2

    budgeted, budgeted_sender, _ = _transport(
        timeout,
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2), max_requests=1),
    )
    with pytest.raises(ReadTransportError) as caught:
        budgeted.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.POLICY_REJECTED
    assert budgeted.budget.used == 1
    assert len(budgeted_sender.requests) == 1


def test_authentication_and_permission_are_never_retried():
    for status in (401, 403):
        transport, sender, _ = _transport(
            lambda request, status=status: _json_response({}, status=status),
            policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
        )
        response = transport.send(_request())
        assert response.status_code == status
        assert len(sender.requests) == 1


def test_rate_limit_is_bounded_and_retryable():
    sequence = iter(
        [
            _json_response({"retCode": 10006, "retMsg": "Too many visits!", "result": {}}, status=429),
            _json_response(_ok_body()),
        ]
    )
    transport, sender, _ = _transport(
        lambda request: next(sequence),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2)),
    )
    response = transport.send(_request())
    assert response.status_code == 200
    assert len(sender.requests) == 2


def test_retry_delay_requires_injected_sleep_and_uses_it():
    with pytest.raises(ValueError):
        _transport(
            lambda request: HttpSenderError(HttpSenderFailureKind.TIMEOUT),
            policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2, retry_delay_seconds=1)),
            sleep=None,
        )
    slept = []
    sequence = iter([HttpSenderError(HttpSenderFailureKind.TIMEOUT), _json_response(_ok_body())])
    transport, sender, _ = _transport(
        lambda request: next(sequence),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2, retry_delay_seconds=1)),
        sleep=slept.append,
    )
    assert transport.send(_request()).status_code == 200
    assert slept == [1.0]
    assert len(sender.requests) == 2


def test_response_size_redirect_and_invalid_json_are_typed_failures():
    transport, sender, _ = _transport(
        lambda request: HttpSenderResponse(200, b"x" * 20, NOW),
        policy=ReadOnlySafetyPolicy(egress=EgressPolicy(max_response_bytes=10)),
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.RESPONSE_TOO_LARGE

    transport, sender, _ = _transport(lambda request: _json_response({}, status=302))
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.REDIRECT_REJECTED
    assert len(sender.requests) == 1

    transport, sender, _ = _transport(
        lambda request: HttpSenderResponse(200, b"not-json", NOW)
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.INVALID_RESPONSE

    transport, sender, _ = _transport(
        lambda request: HttpSenderResponse(401, b"not-json", NOW)
    )
    response = transport.send(_request())
    assert response.status_code == 401
    assert response.body == {}

    transport, sender, _ = _transport(lambda request: object())
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.INVALID_RESPONSE


def test_sender_tls_failure_is_not_sent_to_adapter_as_success():
    transport, sender, _ = _transport(
        lambda request: HttpSenderError(HttpSenderFailureKind.TLS_FAILED)
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.STATE_UNKNOWN


# ---------------------------------------------------------------------------
# Adapter integration through the signed transport
# ---------------------------------------------------------------------------


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_existing_adapter_works_through_signed_transport_with_mock_sender():
    def handler(request: SignedReadRequest) -> HttpSenderResponse:
        if request.path == POSITIONS_PATH:
            name = (
                "positions_page1_fabricated.json"
                if "cursor" not in _decode_query(request)
                else "positions_page2_fabricated.json"
            )
            return _json_response(_load(name))
        if request.path == OPEN_ORDERS_PATH:
            return _json_response(_load("open_orders_page2_fabricated.json"))
        return _json_response(_load("wallet_balance_fabricated.json"))

    transport, sender, _ = _transport(handler)
    adapter = BybitDemoReadAdapter(_binding(), transport, FixedClock())
    summary = adapter.get_account_summary()
    positions = adapter.list_positions()
    orders = adapter.list_open_orders()
    assert summary.metadata.data_quality is ReadDataQuality.COMPLETE
    assert positions.metadata.data_quality is ReadDataQuality.COMPLETE
    assert orders.metadata.data_quality is ReadDataQuality.COMPLETE
    assert {request.path for request in sender.requests} == {
        ACCOUNT_SUMMARY_PATH,
        POSITIONS_PATH,
        OPEN_ORDERS_PATH,
    }
    for signed in sender.requests:
        assert signed.host == BYBIT_DEMO_HOST
        assert signed.method == "GET"
        assert signed.header("X-BAPI-SIGN") not in repr(signed)
        assert "fabricated-key-not-real" not in repr(signed)
        message = (
            signed.header("X-BAPI-TIMESTAMP")
            + signed.header("X-BAPI-API-KEY")
            + signed.header("X-BAPI-RECV-WINDOW")
            + signed.query
        )
        expected = hmac.new(
            b"fabricated-secret-not-real", message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert signed.header("X-BAPI-SIGN") == expected


def test_adapter_maps_signed_transport_policy_failure_to_typed_failure():
    transport, sender, _ = _transport(
        lambda request: _json_response(_ok_body()),
        policy=ReadOnlySafetyPolicy(
            egress=EgressPolicy(allowed_paths=frozenset({ACCOUNT_SUMMARY_PATH}))
        ),
    )
    adapter = BybitDemoReadAdapter(_binding(), transport, FixedClock())
    result = adapter.list_positions()
    assert result.metadata.data_quality is ReadDataQuality.FAILED
    assert result.metadata.failure.code is ReadErrorCode.INVALID_REQUEST
    assert sender.requests == []
