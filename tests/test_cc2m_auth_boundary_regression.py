from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

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
from backend.execution.bybit_key_info import (
    ExternalBindingCheck,
    GeneralReadAuthorizationGate,
    KeyInfoReadiness,
    KeyInfoProjection,
    ReadinessBinding,
    ReadinessReuseStatus,
    ReadinessStatus,
    assess_readiness_reuse,
    evaluate_key_info_readiness,
    parse_key_info_response,
    require_reusable_readiness,
)
from backend.execution.bybit_server_time import (
    BYBIT_SERVER_TIME_PATH,
    PublicServerTimeRequest,
    ServerTimeEnvelopeError,
    ServerTimeParseError,
    parse_server_time_response,
)
from backend.execution.bybit_v5_signed_transport import (
    BybitV5SignedReadTransport,
    HttpSenderResponse,
    SignedReadRequest,
)
from backend.execution.bybit_v5_signing import (
    SigningError,
    canonical_query,
    canonicalize_pre_encoded_token,
    require_prepared_query_matches,
)
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadCapabilities,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
)
from backend.execution.read_only_credentials import (
    CredentialScope,
    ReadOnlyCredential,
)
from backend.execution.read_only_policy import (
    BYBIT_DEMO_HOST,
    ClockPolicy,
    PolicyErrorCode,
    ReadOnlyPolicyError,
    ReadOnlySafetyPolicy,
    RequestBudget,
    RetryPolicy,
    ServerTimeObservation,
)
from backend.execution.read_only_transport import (
    ReadOnlyRequest,
    ReadTransportError,
    ReadTransportFailureKind,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")
OTHER_ACCOUNT_ID = AccountId("acc_22222222222242228222222222222222")
POSITIONS_PATH = "/v5/position/list"
FABRICATED_KEY = "fabricated-key-not-real"
FABRICATED_SECRET = "fabricated-secret-not-real"


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


class StepClock:
    def __init__(self, values) -> None:
        self.values = list(values)
        self.current = self.values[0]

    def now(self) -> datetime:
        if self.values:
            self.current = self.values.pop(0)
        return self.current


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, value: float) -> None:
        self.calls.append(value)


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


def _reference(credential_id: str = "fabricated-bundle") -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        credential_id,
        "HYRO_DEMO",
    )


def _scope(account_id: AccountId = ACCOUNT_ID) -> CredentialScope:
    return CredentialScope(
        account_id,
        ExecutionMode.EXTERNAL_SIMULATION,
        ExecutionVenue.BYBIT_DEMO,
        EndpointProfile.BYBIT_DEMO_V5,
    )


def _capabilities() -> ReadCapabilities:
    return ReadCapabilities(
        account_read="SUPPORTED",
        positions_read="SUPPORTED",
        orders_read="SUPPORTED",
        server_time="SUPPORTED",
    )


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


_UNSET = object()


class FakeProvider:
    def __init__(self, *, scope=_UNSET, generation="fabricated-generation-1") -> None:
        self.scope = scope
        self.generation = generation
        self.calls = []

    def resolve(self, reference, scope):
        self.calls.append((reference, scope))
        echoed_scope = scope if self.scope is _UNSET else self.scope
        return ReadOnlyCredential(
            reference,
            FABRICATED_KEY,
            FABRICATED_SECRET,
            scope=echoed_scope,
            credential_generation=self.generation,
        )


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
    monotonic=None,
    general_read_gate="default",
):
    sender = FakeSender(handler)
    effective_binding = binding or _binding()
    effective_provider = provider or FakeProvider()
    if server_time_source == "default":
        server_time_source = lambda: ServerTimeObservation(NOW, NOW)
    if general_read_gate == "default":
        readiness_binding = ReadinessBinding(
            account_id=effective_binding.account_id,
            credential_reference=effective_binding.credential_reference,
            registry_revision=effective_binding.registry_revision,
            record_revision=effective_binding.record_revision,
            credential_generation=effective_provider.generation,
        )
        readiness = KeyInfoReadiness(
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
        general_read_gate = GeneralReadAuthorizationGate(
            lambda: readiness, lambda: effective_binding
        )
    transport = BybitV5SignedReadTransport(
        effective_binding,
        sender,
        effective_provider,
        clock or FixedClock(),
        policy=policy or ReadOnlySafetyPolicy(),
        server_time_source=server_time_source,
        sleep=sleep,
        budget=budget,
        monotonic=monotonic,
        general_read_gate=general_read_gate,
    )
    return transport, sender


def _json_response(payload, *, status: int = 200, headers=()) -> HttpSenderResponse:
    return HttpSenderResponse(
        status, json.dumps(payload).encode("utf-8"), NOW, headers=headers
    )


def _ok_body(result=None) -> dict:
    return {"retCode": 0, "retMsg": "OK", "result": result or {}, "time": 1767225600000}


def _request() -> ReadOnlyRequest:
    return ReadOnlyRequest("GET", POSITIONS_PATH, ())


def _projection(**overrides) -> KeyInfoProjection:
    values = {
        "readOnly": 1,
        "uta": 1,
        "permissions": {
            "ContractTrade": ["Order", "Position"],
            "Wallet": ["AccountTransfer"],
        },
        "ips": [],
        "expiredAt": "2027-01-01T00:00:00Z",
        "userID": 987654321,
        "parentUid": "123456789",
        "isMaster": True,
        "type": 1,
        "createdAt": "2025-10-13T03:20:45Z",
    }
    values.update(overrides)
    return parse_key_info_response({"retCode": 0, "retMsg": "OK", "result": values})


# ---------------------------------------------------------------------------
# F-01 clock asymmetry
# ---------------------------------------------------------------------------


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def test_clock_uses_official_asymmetric_bounds_with_margin():
    policy = ClockPolicy(timestamp_margin_ms=100, observation_uncertainty_ms=0)
    observation = ServerTimeObservation(NOW, NOW)
    base = _ms(NOW)

    assert policy.require_fresh(observation, NOW, timestamp_ms=base + 899, recv_window_ms=5000).fresh
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(observation, NOW, timestamp_ms=base + 900, recv_window_ms=5000)
    assert caught.value.code is PolicyErrorCode.CLOCK_SKEW_EXCEEDED

    assert policy.require_fresh(observation, NOW, timestamp_ms=base - 4900, recv_window_ms=5000).fresh
    with pytest.raises(ReadOnlyPolicyError):
        policy.require_fresh(observation, NOW, timestamp_ms=base - 4901, recv_window_ms=5000)


def test_clock_uses_effective_recv_window_not_a_symmetric_bound():
    policy = ClockPolicy(timestamp_margin_ms=100)
    observation = ServerTimeObservation(NOW, NOW)
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(
            observation,
            NOW,
            timestamp_ms=_ms(NOW) - 3000,
            recv_window_ms=1000,
        )
    assert caught.value.code is PolicyErrorCode.CLOCK_SKEW_EXCEEDED


def test_clock_projects_observation_instead_of_using_raw_server_time():
    policy = ClockPolicy(timestamp_margin_ms=100)
    observation = ServerTimeObservation(NOW - timedelta(seconds=10), NOW)
    now = NOW + timedelta(seconds=4)
    assessment = policy.assess(
        observation,
        now,
        timestamp_ms=_ms(now),
        recv_window_ms=5000,
    )
    assert assessment.status.value == "SKEW"
    assert assessment.ahead_ms == 10_000


def test_clock_rejects_future_or_retreating_observations_and_invalid_margins():
    policy = ClockPolicy(timestamp_margin_ms=100)
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(
            ServerTimeObservation(NOW, NOW + timedelta(seconds=10)),
            NOW,
            timestamp_ms=_ms(NOW),
        )
    assert caught.value.code is PolicyErrorCode.CLOCK_OBSERVATION_STALE
    with pytest.raises(ReadOnlyPolicyError) as caught:
        policy.require_fresh(
            ServerTimeObservation(NOW, NOW - timedelta(seconds=10)),
            NOW,
            timestamp_ms=_ms(NOW),
        )
    assert caught.value.code is PolicyErrorCode.CLOCK_OBSERVATION_STALE
    with pytest.raises(ValueError):
        ClockPolicy(timestamp_margin_ms=1000)
    with pytest.raises(ValueError):
        ClockPolicy(timestamp_margin_ms=600, observation_uncertainty_ms=400)


def test_retry_reacquires_clock_and_resigns_after_clock_rejection():
    sequence = iter(
        [
            _json_response({"retCode": 10002, "retMsg": "timestamp", "result": {}}),
            _json_response(_ok_body()),
        ]
    )
    clock = StepClock(
        [NOW, NOW, NOW + timedelta(seconds=2), NOW + timedelta(seconds=2)]
    )
    transport, sender = _transport(
        lambda request: next(sequence),
        clock=clock,
        server_time_source=lambda: ServerTimeObservation(clock.current, clock.current),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2)),
    )
    response = transport.send(_request())
    assert response.status_code == 200
    assert len(sender.requests) == 2
    first, second = sender.requests
    assert first.header("X-BAPI-TIMESTAMP") != second.header("X-BAPI-TIMESTAMP")
    assert first.header("X-BAPI-SIGN") != second.header("X-BAPI-SIGN")


# ---------------------------------------------------------------------------
# F-02 query byte integrity
# ---------------------------------------------------------------------------


def test_pre_encoded_tokens_are_canonicalised_once_to_requests_form():
    assert canonicalize_pre_encoded_token("a%7eb") == "a~b"
    assert canonicalize_pre_encoded_token("a%3db") == "a%3Db"
    assert canonicalize_pre_encoded_token("a%2Bb") == "a%2Bb"
    assert canonicalize_pre_encoded_token("a%2526b") == "a%2526b"
    assert canonicalize_pre_encoded_token("a%41b") == "aAb"
    assert canonicalize_pre_encoded_token("a%C3%A9b") == "a%C3%A9b"
    for bad in ("a&b", "a=b", "a b", "a%2", "a%ZZ", "", "a#b"):
        with pytest.raises(SigningError):
            canonicalize_pre_encoded_token(bad)


def test_signed_and_prepared_query_bytes_match_for_all_cursor_forms():
    for cursor in ("a%7eb", "a%3db", "page_args%3Dfd4300ae%26symbol%3D6%26", "a%2526b"):
        query = canonical_query((("category", "linear"), ("cursor", cursor)))
        prepared = requests.Request(
            "GET", f"https://{BYBIT_DEMO_HOST}{POSITIONS_PATH}?{query}"
        ).prepare()
        require_prepared_query_matches(query, prepared.url)
        assert prepared.url.split("?", 1)[1] == query
        assert "%253D" not in query


def test_transport_transmits_the_canonicalised_cursor_it_signs():
    transport, sender = _transport(lambda request: _json_response(_ok_body()))
    transport.send(
        ReadOnlyRequest(
            "GET", POSITIONS_PATH, (("category", "linear"), ("cursor", "a%7eb"))
        )
    )
    signed = sender.requests[0]
    assert signed.query == "category=linear&cursor=a~b"
    prepared = requests.Request(
        "GET", f"https://{BYBIT_DEMO_HOST}{signed.path}?{signed.query}"
    ).prepare()
    require_prepared_query_matches(signed.query, prepared.url)


def test_query_byte_guard_fails_closed_on_mismatch():
    with pytest.raises(SigningError):
        require_prepared_query_matches("cursor=a~b", "https://x/p?cursor=a%7Eb")
    with pytest.raises(SigningError):
        require_prepared_query_matches("cursor=a%3Db", "https://x/p?cursor=a%3db")


# ---------------------------------------------------------------------------
# F-03 retCode-aware retry
# ---------------------------------------------------------------------------


def test_ret_code_10006_retries_with_bounded_reset_delay():
    reset_ms = _ms(NOW) + 2000
    sequence = iter(
        [
            _json_response(
                {"retCode": 10006, "retMsg": "Too many visits", "result": {}},
                headers=(("X-Bapi-Limit-Reset-Timestamp", str(reset_ms)),),
            ),
            _json_response(_ok_body()),
        ]
    )
    sleep = RecordingSleep()
    transport, sender = _transport(
        lambda request: next(sequence),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2, max_retry_delay_seconds=5)),
        sleep=sleep,
    )
    assert transport.send(_request()).status_code == 200
    assert len(sender.requests) == 2
    assert sleep.calls == [2.0]


def test_ret_code_10002_requires_clock_source_to_retry():
    sequence = iter(
        [
            _json_response({"retCode": 10002, "retMsg": "timestamp", "result": {}}),
            _json_response(_ok_body()),
        ]
    )
    transport, sender = _transport(
        lambda request: next(sequence),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=2)),
    )
    assert transport.send(_request()).status_code == 200
    assert len(sender.requests) == 2

    no_source_sequence = iter(
        [_json_response({"retCode": 10002, "retMsg": "timestamp", "result": {}})]
    )
    policy = ReadOnlySafetyPolicy(
        retry=RetryPolicy(max_attempts=2),
        clock=ClockPolicy(require_server_time=False),
    )
    transport, sender = _transport(
        lambda request: next(no_source_sequence),
        policy=policy,
        server_time_source=None,
    )
    response = transport.send(_request())
    assert response.body["retCode"] == 10002
    assert len(sender.requests) == 1


def test_unknown_ret_codes_and_auth_statuses_are_not_retried():
    unknown = iter(
        [_json_response({"retCode": 99999, "retMsg": "unknown", "result": {}})]
    )
    transport, sender = _transport(
        lambda request: next(unknown),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
    )
    assert transport.send(_request()).body["retCode"] == 99999
    assert len(sender.requests) == 1

    for status in (401, 403):
        transport, sender = _transport(
            lambda request, status=status: _json_response({}, status=status),
            policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
        )
        assert transport.send(_request()).status_code == status
        assert len(sender.requests) == 1

    for status in (401, 403):
        transport, sender = _transport(
            lambda request, status=status: _json_response(
                {"retCode": 10006, "retMsg": "inconsistent", "result": {}},
                status=status,
            ),
            policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
        )
        assert transport.send(_request()).status_code == status
        assert len(sender.requests) == 1


def test_total_deadline_stops_before_an_extra_attempt():
    class FakeMonotonic:
        def __init__(self) -> None:
            self.values = iter([0.0, 0.6, 1.2, 1.8])

        def __call__(self) -> float:
            return next(self.values)

    transport, sender = _transport(
        lambda request: _json_response(
            {"retCode": 10006, "retMsg": "Too many visits", "result": {}}
        ),
        policy=ReadOnlySafetyPolicy(
            retry=RetryPolicy(max_attempts=3, total_deadline_seconds=1.0)
        ),
        monotonic=FakeMonotonic(),
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.TIMEOUT
    assert len(sender.requests) == 1


def test_budget_is_consumed_per_retry_attempt():
    budget = RequestBudget(1)
    transport, sender = _transport(
        lambda request: _json_response(
            {"retCode": 10006, "retMsg": "Too many visits", "result": {}}
        ),
        policy=ReadOnlySafetyPolicy(retry=RetryPolicy(max_attempts=3)),
        budget=budget,
    )
    with pytest.raises(ReadTransportError) as caught:
        transport.send(_request())
    assert caught.value.kind is ReadTransportFailureKind.POLICY_REJECTED
    assert budget.used == 1
    assert len(sender.requests) == 1


# ---------------------------------------------------------------------------
# F-06 concurrency budget
# ---------------------------------------------------------------------------


def test_budget_is_thread_safe_under_concurrency():
    budget = RequestBudget(50)
    successes = []
    failures = []

    def worker():
        try:
            budget.consume()
            successes.append(1)
        except ReadOnlyPolicyError:
            failures.append(1)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda _: worker(), range(100)))

    assert len(successes) == 50
    assert len(failures) == 50
    assert budget.used == 50
    assert budget.remaining == 0
    assert budget.scope == "TRANSPORT_LOCAL"


# ---------------------------------------------------------------------------
# F-04 readiness binding
# ---------------------------------------------------------------------------


def _binding_snapshot(**overrides) -> ReadinessBinding:
    values = {
        "account_id": ACCOUNT_ID,
        "credential_reference": _reference(),
        "registry_revision": 7,
        "record_revision": 3,
        "credential_generation": "fabricated-generation-1",
    }
    values.update(overrides)
    return ReadinessBinding(**values)


def test_readiness_reuse_rejects_account_reference_record_and_generation_mismatch():
    binding = _binding_snapshot()
    readiness = evaluate_key_info_readiness(
        _projection(), clock=FixedClock(), binding=binding
    )
    assert assess_readiness_reuse(readiness, binding, now=NOW) is ReadinessReuseStatus.REUSABLE
    assert (
        assess_readiness_reuse(readiness, _binding_snapshot(account_id=OTHER_ACCOUNT_ID), now=NOW)
        is ReadinessReuseStatus.BINDING_MISMATCH
    )
    assert (
        assess_readiness_reuse(
            readiness, _binding_snapshot(credential_reference=_reference("other")), now=NOW
        )
        is ReadinessReuseStatus.BINDING_MISMATCH
    )
    assert (
        assess_readiness_reuse(readiness, _binding_snapshot(record_revision=4), now=NOW)
        is ReadinessReuseStatus.BINDING_MISMATCH
    )
    assert (
        assess_readiness_reuse(
            readiness, _binding_snapshot(credential_generation="fabricated-generation-2"), now=NOW
        )
        is ReadinessReuseStatus.BINDING_MISMATCH
    )


def test_readiness_reuse_distinguishes_registry_advance_and_freshness():
    binding = _binding_snapshot()
    readiness = evaluate_key_info_readiness(
        _projection(), clock=FixedClock(), binding=binding
    )
    advanced = _binding_snapshot(registry_revision=8)
    assert (
        assess_readiness_reuse(readiness, advanced, now=NOW)
        is ReadinessReuseStatus.BINDING_MISMATCH
    )
    assert (
        assess_readiness_reuse(
            readiness, advanced, now=NOW, allow_registry_revision_advance=True
        )
        is ReadinessReuseStatus.REUSABLE
    )
    assert (
        assess_readiness_reuse(
            readiness,
            _binding_snapshot(registry_revision=6),
            now=NOW,
            allow_registry_revision_advance=True,
        )
        is ReadinessReuseStatus.BINDING_MISMATCH
    )
    assert (
        assess_readiness_reuse(readiness, binding, now=NOW + timedelta(seconds=10))
        is ReadinessReuseStatus.STALE
    )


def test_unbound_readiness_cannot_be_reused_and_require_raises_fixed_text():
    unbound = evaluate_key_info_readiness(_projection(), clock=FixedClock())
    assert (
        assess_readiness_reuse(unbound, _binding_snapshot(), now=NOW)
        is ReadinessReuseStatus.UNBOUND
    )
    with pytest.raises(ValueError) as caught:
        require_reusable_readiness(unbound, _binding_snapshot(), now=NOW)
    assert "not bound" in str(caught.value)


# ---------------------------------------------------------------------------
# F-05 credential scope echo
# ---------------------------------------------------------------------------


def test_transport_rejects_missing_or_mismatched_credential_scope():
    for scope in (None, _scope(OTHER_ACCOUNT_ID)):
        transport, sender = _transport(
            lambda request: _json_response(_ok_body()),
            provider=FakeProvider(scope=scope),
        )
        with pytest.raises(ReadTransportError) as caught:
            transport.send(_request())
        assert caught.value.kind is ReadTransportFailureKind.CREDENTIAL_REJECTED
        assert sender.requests == []


def test_transport_records_opaque_credential_generation():
    transport, _ = _transport(lambda request: _json_response(_ok_body()))
    transport.send(_request())
    assert transport.last_credential_generation == "fabricated-generation-1"


# ---------------------------------------------------------------------------
# F-09 UID output policy
# ---------------------------------------------------------------------------


def test_uid_is_redacted_from_default_repr_and_to_dict():
    projection = _projection()
    assert projection.user_id == 987654321
    assert "987654321" not in repr(projection)
    assert "123456789" not in repr(projection)
    default = projection.to_dict()
    assert default["user_id"] is None
    assert default["parent_uid"] is None
    assert default["external_identifiers_redacted"] is True
    explicit = projection.to_dict(include_external_identifiers=True)
    assert explicit["user_id"] == 987654321
    assert explicit["parent_uid"] == "123456789"
    assert explicit["external_identifiers_redacted"] is False


# ---------------------------------------------------------------------------
# F-10 headers
# ---------------------------------------------------------------------------


def _auth_headers() -> tuple[tuple[str, str], ...]:
    return (
        ("X-BAPI-API-KEY", FABRICATED_KEY),
        ("X-BAPI-TIMESTAMP", "1767225600000"),
        ("X-BAPI-RECV-WINDOW", "5000"),
        ("X-BAPI-SIGN", "a" * 64),
    )


def test_signed_request_allows_only_allowlisted_non_auth_headers():
    allowed = SignedReadRequest(
        "GET",
        BYBIT_DEMO_HOST,
        POSITIONS_PATH,
        "",
        _auth_headers()
        + (("Content-Type", "application/json"), ("X-BAPI-SIGN-TYPE", "2")),
        5.0,
        1000,
    )
    assert allowed.header("Content-Type") == "application/json"
    for forbidden in ("Host", "Cookie", "Authorization", "Proxy-Authorization"):
        with pytest.raises(ValueError):
            SignedReadRequest(
                "GET",
                BYBIT_DEMO_HOST,
                POSITIONS_PATH,
                "",
                _auth_headers() + ((forbidden, "x"),),
                5.0,
                1000,
            )
    with pytest.raises(ValueError):
        SignedReadRequest(
            "GET",
            BYBIT_DEMO_HOST,
            POSITIONS_PATH,
            "",
            _auth_headers() + (("X-BAPI-API-KEY", "overwrite"),),
            5.0,
            1000,
        )


def test_sender_response_retains_only_safe_headers():
    response = HttpSenderResponse(
        200,
        b"{}",
        NOW,
        headers=(("X-Bapi-Limit-Reset-Timestamp", "1767225600000"),),
    )
    assert response.safe_header("x-bapi-limit-reset-timestamp") == "1767225600000"
    with pytest.raises(ValueError):
        HttpSenderResponse(200, b"{}", NOW, headers=(("Set-Cookie", "secret=1"),))
    with pytest.raises(ValueError):
        HttpSenderResponse(200, b"{}", NOW, headers=(("Retry-After", "1\n2"),))


# ---------------------------------------------------------------------------
# F-11 public server-time contract
# ---------------------------------------------------------------------------


def test_public_server_time_request_is_fixed_and_unauthenticated():
    request = PublicServerTimeRequest()
    assert request.method == "GET"
    assert request.host == BYBIT_DEMO_HOST
    assert request.path == BYBIT_SERVER_TIME_PATH
    assert request.requires_credentials is False
    read_only = request.as_read_only_request()
    assert read_only.method == "GET"
    assert read_only.path == BYBIT_SERVER_TIME_PATH
    assert read_only.query == ()
    with pytest.raises(ValueError):
        PublicServerTimeRequest(path="/v5/account/wallet-balance")
    with pytest.raises(ValueError):
        PublicServerTimeRequest(host="api.bybit.com")
    with pytest.raises(ValueError):
        PublicServerTimeRequest(requires_credentials=True)


def test_server_time_parser_accepts_fabricated_nano_and_second_responses():
    nano = parse_server_time_response(
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "timeSecond": "1767225600",
                "timeNano": "1767225600123456789",
            },
        },
        observed_at=NOW,
    )
    assert nano.server_time == datetime(
        2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc
    )
    assert nano.observed_at == NOW

    second = parse_server_time_response(
        {"retCode": 0, "retMsg": "OK", "result": {"timeSecond": "1767225600"}},
        observed_at=NOW,
    )
    assert second.server_time == NOW


def test_server_time_parser_fails_closed_and_never_reads_a_clock():
    with pytest.raises(ServerTimeEnvelopeError) as caught:
        parse_server_time_response(
            {"retCode": 10006, "retMsg": "raw text", "result": {}}, observed_at=NOW
        )
    assert caught.value.ret_code == 10006
    assert "raw text" not in str(caught.value)
    for body in (
        {"retCode": 0, "retMsg": "OK", "result": {}},
        {"retCode": 0, "retMsg": "OK", "result": {"timeNano": "not-digits"}},
        {"retCode": 0, "result": {"timeSecond": "1"}},
        {"retCode": "0", "retMsg": "OK", "result": {"timeSecond": "1"}},
    ):
        with pytest.raises(ServerTimeParseError):
            parse_server_time_response(body, observed_at=NOW)
    with pytest.raises(TypeError):
        parse_server_time_response(
            {"retCode": 0, "retMsg": "OK", "result": {"timeSecond": "1"}},
            observed_at=datetime(2026, 1, 1),
        )


# ---------------------------------------------------------------------------
# Bootstrap binding integration
# ---------------------------------------------------------------------------


def test_bootstrap_readiness_carries_binding_and_generation():
    from backend.execution.read_only_bootstrap import BybitDemoKeyInfoBootstrap

    transport, sender = _transport(
        lambda request: _json_response(
            {"retCode": 0, "retMsg": "OK", "result": {
                "readOnly": 1,
                "uta": 1,
                "permissions": {
                    "ContractTrade": ["Order", "Position"],
                    "Wallet": ["AccountTransfer"],
                },
                "ips": [],
                "expiredAt": "2027-01-01T00:00:00Z",
                "userID": 987654321,
                "parentUid": "123456789",
                "isMaster": True,
                "type": 1,
                "createdAt": "2025-10-13T03:20:45Z",
            }, "time": 1767225600000}
        )
    )
    result = BybitDemoKeyInfoBootstrap(
        transport,
        expected_user_id=987654321,
        expected_parent_uid="123456789",
    ).read_key_info()
    assert result.succeeded is True
    assert result.binding is not None
    assert result.binding.credential_generation == "fabricated-generation-1"
    assert result.readiness is not None
    assert result.readiness.binding == result.binding
    assert result.readiness.observed_at is not None
    assert result.readiness.source_time == NOW
    require_reusable_readiness(result.readiness, result.binding, now=NOW)
    assert len(sender.requests) == 1
