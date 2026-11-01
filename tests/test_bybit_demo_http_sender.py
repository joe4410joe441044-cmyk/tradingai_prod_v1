from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from backend.execution.bybit_demo_http_sender import BybitDemoHttpSender
from backend.execution.bybit_server_time import (
    BYBIT_SERVER_TIME_PATH,
    BybitDemoServerTimeSource,
    ServerTimeFetchError,
    ServerTimeParseError,
    ServerTimeStaleError,
    parse_server_time_response,
)
from backend.execution.bybit_v5_signed_transport import (
    HttpSenderError,
    HttpSenderFailureKind,
    HttpSenderResponse,
    SignedReadRequest,
)
from backend.execution.read_only_policy import BYBIT_DEMO_HOST


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FABRICATED_KEY = "fabricated-key-not-real"
FABRICATED_SECRET = "fabricated-secret-not-real"
PATH = "/v5/account/wallet-balance"


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


class Sequence:
    def __init__(self, values) -> None:
        self.values = list(values)
        self.last = self.values[-1]

    def __call__(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        chunks=(b'{"retCode":0,"retMsg":"OK","result":{}}',),
        headers=None,
        raise_at=None,
        exc=None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers if headers is not None else {}
        self._chunks = list(chunks)
        self._raise_at = raise_at
        self._exc = exc
        self.closed = False
        self.iterated = 0

    def iter_content(self, chunk_size: int = 1):
        for index, chunk in enumerate(self._chunks):
            if self._raise_at is not None and index == self._raise_at:
                raise self._exc
            self.iterated += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responder=None) -> None:
        self.responder = responder or (lambda prepared: FakeResponse())
        self.sent = []
        self.closed = False
        self.trust_env = True
        self.proxies = {"http": "http://ambient-proxy.invalid"}
        self.auth = ("ambient-user", "ambient-pass")
        self.headers = requests.structures.CaseInsensitiveDict(
            {"Authorization": "Bearer ambient", "Cookie": "session=ambient"}
        )

    def prepare_request(self, request):
        return request.prepare()

    def send(self, prepared, **kwargs):
        self.sent.append((prepared, kwargs))
        result = self.responder(prepared)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        self.closed = True


class RecordingRequestsSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.sent = []

    def send(self, prepared, **kwargs):
        self.sent.append((prepared, kwargs))
        return FakeResponse(chunks=(_server_time_body(NOW),))


class FakeSemaphore:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.timeouts = []
        self.releases = 0

    def acquire(self, *, timeout):
        self.timeouts.append(timeout)
        return self.acquired

    def release(self) -> None:
        self.releases += 1


def _signed_request(*, query: str = "", path: str = PATH) -> SignedReadRequest:
    return SignedReadRequest(
        method="GET",
        host=BYBIT_DEMO_HOST,
        path=path,
        query=query,
        headers=(
            ("X-BAPI-API-KEY", FABRICATED_KEY),
            ("X-BAPI-TIMESTAMP", "1767225600000"),
            ("X-BAPI-RECV-WINDOW", "5000"),
            ("X-BAPI-SIGN", "a" * 64),
        ),
        timeout_seconds=5.0,
        max_response_bytes=1_000_000,
    )


def _server_time_body(moment: datetime) -> bytes:
    nanos = int(moment.timestamp() * 1_000_000_000)
    return (
        '{"retCode":0,"retMsg":"OK","result":{'
        f'"timeSecond":"{int(moment.timestamp())}",'
        f'"timeNano":"{nanos}"'
        "}}"
    ).encode("utf-8")


def _sender(**kwargs) -> tuple[BybitDemoHttpSender, FakeSession]:
    session = kwargs.pop("session", None) or FakeSession()
    return (
        BybitDemoHttpSender(session=session, allow_network=True, **kwargs),
        session,
    )


# -- constructor / gate -------------------------------------------------------


def test_constructor_does_not_send():
    sender, session = _sender(clock=FixedClock().now)
    assert session.sent == []
    assert sender.enabled is True
    assert sender.max_response_bytes == 1_000_000


def test_default_gate_blocks_send():
    session = FakeSession()
    sender = BybitDemoHttpSender(session=session)
    assert sender.enabled is False
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


def test_public_get_gate_blocks_send():
    session = FakeSession(lambda prepared: FakeResponse(chunks=(_server_time_body(NOW),)))
    sender = BybitDemoHttpSender(session=session)
    with pytest.raises(HttpSenderError):
        sender.get_public(BYBIT_SERVER_TIME_PATH)
    assert session.sent == []


def test_public_get_rejects_other_paths():
    sender, session = _sender()
    for path in ("/v5/account/wallet-balance", "/v5/market/time/../x", ""):
        with pytest.raises(HttpSenderError):
            sender.get_public(path)
    assert session.sent == []


# -- request shape rejection --------------------------------------------------


def test_rejects_mutated_host_and_path_and_method():
    sender, session = _sender()
    base = _signed_request()

    wrong_host = _signed_request()
    object.__setattr__(wrong_host, "host", "api.bybit.com")
    with pytest.raises(HttpSenderError):
        sender.send(wrong_host)

    wrong_path = _signed_request()
    object.__setattr__(wrong_path, "path", "/v5/../etc/passwd")
    with pytest.raises(HttpSenderError):
        sender.send(wrong_path)

    wrong_method = _signed_request()
    object.__setattr__(wrong_method, "method", "POST")
    with pytest.raises(HttpSenderError):
        sender.send(wrong_method)

    assert session.sent == []
    sender.send(base)
    assert len(session.sent) == 1


def test_rejects_non_signed_request_object():
    sender, session = _sender()
    with pytest.raises(HttpSenderError):
        sender.send({"method": "GET"})
    assert session.sent == []


# -- prepared query guard -----------------------------------------------------


def test_prepared_query_guard_blocks_normalisation():
    # A lowercase percent triplet is normalised by requests; the signed bytes
    # and the prepared bytes differ, so the sender must not transmit.
    sender, session = _sender()
    request = _signed_request(query="cursor=a%7eb")
    with pytest.raises(HttpSenderError) as raised:
        sender.send(request)
    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


def test_signed_query_transmitted_verbatim():
    sender, session = _sender(clock=FixedClock().now)
    query = "cursor=a~b&x=%3D%26"
    response = sender.send(_signed_request(query=query))
    assert response.status_code == 200
    assert len(session.sent) == 1
    prepared, kwargs = session.sent[0]
    assert prepared.url == f"https://{BYBIT_DEMO_HOST}{PATH}?{query}"
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["proxies"] == {}
    assert kwargs["verify"] is True
    assert 0 < kwargs["timeout"][0] <= 3.0
    assert 0 < kwargs["timeout"][1] <= 5.0


def test_auth_headers_present_and_unchanged():
    sender, session = _sender()
    sender.send(_signed_request())
    prepared, _kwargs = session.sent[0]
    assert prepared.headers["X-BAPI-API-KEY"] == FABRICATED_KEY
    assert prepared.headers["X-BAPI-SIGN"] == "a" * 64


# -- TLS / proxy / ambient ----------------------------------------------------


def test_tls_verify_default_true_and_ca_bundle():
    sender, session = _sender()
    sender.send(_signed_request())
    assert session.sent[0][1]["verify"] is True

    sender2, session2 = _sender(ca_bundle="/tmp/fabricated-ca.pem")
    sender2.send(_signed_request())
    assert session2.sent[0][1]["verify"] == "/tmp/fabricated-ca.pem"


def test_ambient_configuration_disabled():
    session = FakeSession()
    BybitDemoHttpSender(session=session, allow_network=True)
    assert session.trust_env is False
    assert session.proxies == {}
    assert session.auth is None
    assert "Authorization" not in session.headers
    assert "Cookie" not in session.headers


@pytest.mark.parametrize(
    "ambient",
    ["Authorization", "Proxy-Authorization", "X-Ambient", "Host"],
)
@pytest.mark.parametrize("public", [False, True])
def test_post_construction_ambient_headers_are_rejected(ambient, public):
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)
    session.headers[ambient] = "fabricated-ambient-value"

    with pytest.raises(HttpSenderError) as raised:
        if public:
            sender.get_public(BYBIT_SERVER_TIME_PATH)
        else:
            sender.send(_signed_request())

    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


def test_public_request_rejects_session_default_x_bapi_header():
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)
    session.headers["X-BAPI-API-KEY"] = "fabricated-ambient-value"

    with pytest.raises(HttpSenderError) as raised:
        sender.get_public(BYBIT_SERVER_TIME_PATH)

    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


def test_authenticated_request_overrides_session_default_x_bapi_with_signed_value():
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)
    session.headers["X-BAPI-API-KEY"] = "fabricated-ambient-value"

    sender.send(_signed_request())

    prepared, _kwargs = session.sent[0]
    assert prepared.headers["X-BAPI-API-KEY"] == FABRICATED_KEY


@pytest.mark.parametrize("public", [False, True])
def test_post_construction_cookie_jar_is_rejected(public):
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)
    session.cookies.set("ambient", "fabricated", domain=BYBIT_DEMO_HOST, path="/")

    with pytest.raises(HttpSenderError) as raised:
        if public:
            sender.get_public(BYBIT_SERVER_TIME_PATH)
        else:
            sender.send(_signed_request())

    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


@pytest.mark.parametrize("public", [False, True])
def test_post_construction_session_auth_is_rejected(public):
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)
    session.auth = ("fabricated-user", "fabricated-password")

    with pytest.raises(HttpSenderError) as raised:
        if public:
            sender.get_public(BYBIT_SERVER_TIME_PATH)
        else:
            sender.send(_signed_request())

    assert raised.value.kind is HttpSenderFailureKind.SENDER_REJECTED
    assert session.sent == []


def test_authenticated_prepared_header_set_is_exactly_allowlisted():
    session = RecordingRequestsSession()
    sender = BybitDemoHttpSender(session=session, allow_network=True)

    sender.send(_signed_request())

    prepared, _kwargs = session.sent[0]
    assert {name.lower() for name in prepared.headers} == {
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "x-bapi-api-key",
        "x-bapi-timestamp",
        "x-bapi-recv-window",
        "x-bapi-sign",
    }


# -- retry / streaming / cleanup ---------------------------------------------


def test_no_hidden_retry_on_error_status():
    sender, session = _sender(
        session=FakeSession(lambda prepared: FakeResponse(status_code=500))
    )
    response = sender.send(_signed_request())
    assert response.status_code == 500
    assert len(session.sent) == 1


def test_streaming_cap_aborts_and_closes():
    response = FakeResponse(chunks=(b"x" * 40, b"y" * 40))
    sender, _session = _sender(
        session=FakeSession(lambda prepared: response), max_response_bytes=50
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.RESPONSE_TOO_LARGE
    assert response.closed is True


def test_content_length_hint_rejects_without_reading():
    response = FakeResponse(chunks=(b"x" * 10,), headers={"Content-Length": "100"})
    sender, _session = _sender(
        session=FakeSession(lambda prepared: response), max_response_bytes=50
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.RESPONSE_TOO_LARGE
    assert response.iterated == 0
    assert response.closed is True


def test_missing_content_length_still_capped():
    response = FakeResponse(chunks=(b"x" * 200,))
    sender, _session = _sender(
        session=FakeSession(lambda prepared: response), max_response_bytes=50
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.RESPONSE_TOO_LARGE


def test_invalid_content_length_is_ignored_and_stream_capped():
    response = FakeResponse(
        chunks=(b"x" * 200,), headers={"Content-Length": "not-a-number"}
    )
    sender, _session = _sender(
        session=FakeSession(lambda prepared: response), max_response_bytes=50
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.RESPONSE_TOO_LARGE
    assert response.iterated == 1


def test_redirect_is_returned_not_followed():
    response = FakeResponse(
        status_code=302, headers={"Location": "https://evil.example/next"}
    )
    sender, session = _sender(session=FakeSession(lambda prepared: response))
    result = sender.send(_signed_request())
    assert result.status_code == 302
    assert session.sent[0][1]["allow_redirects"] is False


def test_chunk_failure_maps_to_connection_failed():
    response = FakeResponse(
        chunks=(b"{", b"}"),
        raise_at=1,
        exc=requests.exceptions.ConnectionError("boom at /secret"),
    )
    sender, _session = _sender(session=FakeSession(lambda prepared: response))
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.CONNECTION_FAILED
    assert response.closed is True


def test_send_timeout_maps_to_timeout():
    sender, _session = _sender(
        session=FakeSession(lambda prepared: requests.exceptions.Timeout("slow"))
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.TIMEOUT


def test_stream_deadline_maps_to_timeout():
    response = FakeResponse(chunks=(b"{}",))
    clock = Sequence([0.0, 0.0, 0.0, 0.0, 100.0])
    sender, _session = _sender(
        session=FakeSession(lambda prepared: response),
        monotonic=clock,
        total_timeout=5.0,
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    assert raised.value.kind is HttpSenderFailureKind.TIMEOUT
    assert response.closed is True


def test_semaphore_wait_uses_remaining_deadline_and_times_out_without_send():
    sender, session = _sender(monotonic=Sequence([10.0, 10.25]), total_timeout=2.0)
    semaphore = FakeSemaphore(acquired=False)
    sender._semaphore = semaphore

    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())

    assert raised.value.kind is HttpSenderFailureKind.TIMEOUT
    assert semaphore.timeouts == [pytest.approx(1.75)]
    assert semaphore.releases == 0
    assert session.sent == []


def test_deadline_expiry_after_semaphore_acquire_releases_without_send():
    sender, session = _sender(monotonic=Sequence([0.0, 0.0, 3.0]), total_timeout=2.0)
    semaphore = FakeSemaphore(acquired=True)
    sender._semaphore = semaphore

    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())

    assert raised.value.kind is HttpSenderFailureKind.TIMEOUT
    assert semaphore.releases == 1
    assert session.sent == []


def test_socket_timeouts_are_clipped_to_remaining_total_deadline():
    sender, session = _sender(
        monotonic=Sequence([0.0, 0.25, 0.75, 0.75, 0.75, 0.75, 0.75]),
        connect_timeout=3.0,
        read_timeout=5.0,
        total_timeout=2.0,
    )

    sender.send(_signed_request())

    assert session.sent[0][1]["timeout"] == pytest.approx((1.25, 1.25))


def test_response_and_session_are_closed():
    response = FakeResponse()
    sender, session = _sender(session=FakeSession(lambda prepared: response))
    sender.send(_signed_request())
    assert response.closed is True
    assert session.closed is False
    sender.close()
    assert session.closed is True
    sender.close()
    assert session.closed is True


def test_bounded_concurrency():
    release = threading.Event()
    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def responder(prepared):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        release.wait(timeout=5.0)
        with lock:
            state["active"] -= 1
        return FakeResponse()

    sender, _session = _sender(
        session=FakeSession(responder), max_concurrency=1
    )
    threads = [
        threading.Thread(target=lambda: sender.send(_signed_request()))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    assert state["max"] <= 1
    release.set()
    for thread in threads:
        thread.join(timeout=5.0)
    assert state["max"] == 1


def test_safe_response_headers_only():
    headers = {
        "Content-Type": "application/json",
        "X-Bapi-Limit": "10",
        "Set-Cookie": "session=secret",
        "Location": "https://evil.example",
    }
    response = FakeResponse(headers=headers)
    sender, _session = _sender(session=FakeSession(lambda prepared: response))
    result = sender.send(_signed_request())
    names = {name for name, _value in result.headers}
    assert "content-type" in names
    assert "x-bapi-limit" in names
    assert "set-cookie" not in names
    assert "location" not in names


def test_errors_do_not_leak_secret_or_chain():
    sender, _session = _sender(
        session=FakeSession(lambda prepared: requests.exceptions.SSLError("tls at /secret"))
    )
    with pytest.raises(HttpSenderError) as raised:
        sender.send(_signed_request())
    error = raised.value
    assert error.kind is HttpSenderFailureKind.TLS_FAILED
    assert FABRICATED_SECRET not in str(error)
    assert FABRICATED_KEY not in repr(error)
    assert error.__cause__ is None
    assert "secret" not in str(error)


# -- public server time -------------------------------------------------------


class FakeGetter:
    def __init__(self, response):
        self.response = response
        self.paths = []

    def get_public(self, path):
        self.paths.append(path)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _http_response(body: bytes, status_code: int = 200) -> HttpSenderResponse:
    return HttpSenderResponse(
        status_code=status_code, body=body, received_at=NOW, headers=()
    )


def test_public_get_sends_no_auth_header():
    body = _server_time_body(NOW)
    sender, session = _sender(session=FakeSession(lambda prepared: FakeResponse(chunks=(body,))))
    result = sender.get_public(BYBIT_SERVER_TIME_PATH)
    assert result.status_code == 200
    prepared, kwargs = session.sent[0]
    assert prepared.url == f"https://{BYBIT_DEMO_HOST}{BYBIT_SERVER_TIME_PATH}"
    assert all(
        not name.lower().startswith("x-bapi-") for name in prepared.headers
    )
    assert kwargs["allow_redirects"] is False


def test_server_time_source_parses_without_credentials():
    getter = FakeGetter(_http_response(_server_time_body(NOW)))
    source = BybitDemoServerTimeSource(getter)
    observation = source.observe(observed_at=NOW)
    assert observation.server_time == NOW
    assert observation.observed_at == NOW
    assert getter.paths == [BYBIT_SERVER_TIME_PATH]


def test_server_time_source_malformed_and_unavailable():
    source = BybitDemoServerTimeSource(FakeGetter(_http_response(b"not json")))
    with pytest.raises(ServerTimeParseError):
        source.observe(observed_at=NOW)

    source = BybitDemoServerTimeSource(FakeGetter(_http_response(b"{}", status_code=503)))
    with pytest.raises(ServerTimeFetchError):
        source.observe(observed_at=NOW)

    source = BybitDemoServerTimeSource(FakeGetter(requests.exceptions.ConnectionError("x")))
    with pytest.raises(ServerTimeFetchError):
        source.observe(observed_at=NOW)


def test_server_time_source_rejects_stale_response():
    old = NOW - timedelta(seconds=30)
    source = BybitDemoServerTimeSource(FakeGetter(_http_response(_server_time_body(old))))
    with pytest.raises(ServerTimeStaleError):
        source.observe(observed_at=NOW)


def test_server_time_as_callable_uses_clock_and_monotonic():
    getter = FakeGetter(_http_response(_server_time_body(NOW)))
    source = BybitDemoServerTimeSource(getter)
    clock = FixedClock(NOW)
    callable_source = source.as_callable(clock, monotonic=Sequence([10.0, 10.002]))
    observation = callable_source()
    assert observation.server_time == NOW
    assert observation.observed_at == NOW + timedelta(milliseconds=2)
    parsed = parse_server_time_response(
        {"retCode": 0, "retMsg": "OK", "result": {"timeNano": str(int(NOW.timestamp() * 1e9))}},
        observed_at=NOW,
    )
    assert parsed.server_time == NOW
