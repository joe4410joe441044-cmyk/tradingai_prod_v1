"""Public, unauthenticated Bybit server-time request and parser contract.

This module defines only the fixed request shape and a pure response parser.  It
never imports an HTTP client, opens a socket, reads a credential, reads the
system clock, or creates a sender.  Only ``GET /v5/market/time`` on the fixed
demo host is described; this is not a general public-API allowlist and must not
be extended to any other endpoint without a separate review.

Time responsibility:
- Parsed ``server_time`` is venue wall-clock time in UTC.
- ``observed_at`` must be supplied by the caller from an explicitly injected
  wall clock; this module never samples the clock itself.
- Freshness and timestamp policy use wall-clock values.
- Retry/deadline accounting is the transport's responsibility and should use a
  monotonic source, not the venue time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import time
from typing import Any, Callable, Mapping, Optional, Protocol

from backend.execution.bybit_v5_signed_transport import HttpSenderResponse
from backend.execution.read_only_policy import BYBIT_DEMO_HOST, ServerTimeObservation
from backend.execution.read_only_transport import ReadOnlyRequest


BYBIT_SERVER_TIME_PATH = "/v5/market/time"
BYBIT_DEMO_PUBLIC_HOST = BYBIT_DEMO_HOST
_NANOS_PER_SECOND = 1_000_000_000


class ServerTimeParseError(ValueError):
    """Fixed-text parser failure; raw response text is discarded."""


class ServerTimeEnvelopeError(ServerTimeParseError):
    def __init__(self, ret_code: int) -> None:
        if isinstance(ret_code, bool) or not isinstance(ret_code, int):
            ret_code = -1
        self.ret_code = ret_code
        super().__init__("server-time request was rejected")


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _digits(value: object) -> bool:
    return isinstance(value, str) and value.isdigit()


@dataclass(frozen=True)
class PublicServerTimeRequest:
    """Fixed unauthenticated server-time request; credentials are not used."""

    method: str = "GET"
    host: str = BYBIT_DEMO_PUBLIC_HOST
    path: str = BYBIT_SERVER_TIME_PATH
    requires_credentials: bool = False

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise ValueError("server-time request method must be GET")
        if self.host != BYBIT_DEMO_PUBLIC_HOST:
            raise ValueError("server-time request host must be the demo host")
        if self.path != BYBIT_SERVER_TIME_PATH:
            raise ValueError("server-time request path must be the exact market time path")
        if self.requires_credentials is not False:
            raise ValueError("server-time request must not require credentials")

    def as_read_only_request(self) -> ReadOnlyRequest:
        return ReadOnlyRequest(method=self.method, path=self.path, query=())


def _time_from_nanos(value: str) -> datetime:
    nanos = int(value)
    seconds, remainder = divmod(nanos, _NANOS_PER_SECOND)
    return datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(
        microseconds=remainder // 1000
    )


def parse_server_time_response(
    body: Mapping[str, Any], *, observed_at: datetime
) -> ServerTimeObservation:
    """Parse a fabricated or real response body into a projected observation.

    ``observed_at`` is the caller's wall-clock receipt time.  The returned
    observation is an estimate: one-way latency is not measured by this parser.
    """

    if not isinstance(body, Mapping):
        raise ServerTimeParseError("server-time response must be a mapping")
    observed = _utc("observed_at", observed_at)
    ret_code = body.get("retCode")
    if isinstance(ret_code, bool) or not isinstance(ret_code, int):
        raise ServerTimeParseError("server-time response envelope is malformed")
    if not isinstance(body.get("retMsg"), str):
        raise ServerTimeParseError("server-time response envelope is malformed")
    if ret_code != 0:
        raise ServerTimeEnvelopeError(ret_code)
    result = body.get("result")
    if not isinstance(result, Mapping):
        raise ServerTimeParseError("server-time result is malformed")

    time_nano = result.get("timeNano")
    time_second = result.get("timeSecond")
    try:
        if time_nano is not None:
            if not _digits(time_nano):
                raise ServerTimeParseError("server-time nanoseconds are malformed")
            server_time = _time_from_nanos(time_nano)
        elif time_second is not None:
            if not _digits(time_second):
                raise ServerTimeParseError("server-time seconds are malformed")
            server_time = datetime.fromtimestamp(int(time_second), tz=timezone.utc)
        else:
            raise ServerTimeParseError("server-time result is missing timestamps")
    except (OverflowError, OSError, ValueError) as exc:
        if isinstance(exc, ServerTimeParseError):
            raise
        raise ServerTimeParseError("server-time value is out of range") from None
    return ServerTimeObservation(server_time, observed)


class ServerTimeSource(Protocol):
    """Injection contract for an approved server-time source.

    Implementations may perform an unauthenticated read through a separately
    approved transport.  They must return an observation with the caller's
    wall-clock ``observed_at`` and must not be constructed implicitly.
    """

    def observe(self, *, observed_at: datetime) -> ServerTimeObservation: ...


class ServerTimeFetchError(ServerTimeParseError):
    """Fixed-text failure for an unavailable or non-200 public response."""

    def __init__(self) -> None:
        super().__init__("server-time response is unavailable")


class ServerTimeStaleError(ServerTimeParseError):
    """Typed failure for a response too far from the observing wall clock."""

    def __init__(self) -> None:
        super().__init__("server-time response is stale")


class PublicHttpGetter(Protocol):
    """Narrow getter contract; only the fixed public endpoint is requested."""

    def get_public(self, path: str) -> HttpSenderResponse: ...


class BybitDemoServerTimeSource:
    """Unauthenticated server-time source over an injected public getter.

    The getter must expose ``get_public`` and must itself be restricted to the
    fixed demo host and the exact ``/v5/market/time`` path.  This class never
    constructs a sender, reads a credential, or samples a clock by itself.

    Time responsibility:
    - ``observed_at`` is the caller's wall-clock time at receipt.
    - ``as_callable`` measures local elapsed time with an injected monotonic
      source and projects the receipt time from the start wall clock.  This
      measures local call duration only; one-way network latency is not measured.
    - ``max_acceptable_skew`` is a defensive local-vs-server comparison so a
      grossly delayed or invalid response becomes a typed failure.  Transport
      clock policy remains the primary freshness/skew decision.
    """

    def __init__(
        self,
        getter: PublicHttpGetter,
        *,
        max_acceptable_skew: timedelta = timedelta(seconds=5),
    ) -> None:
        if getter is None or not callable(getattr(getter, "get_public", None)):
            raise TypeError("an explicit public HTTP getter is required")
        if not isinstance(max_acceptable_skew, timedelta) or max_acceptable_skew <= timedelta(0):
            raise ValueError("max_acceptable_skew must be a positive timedelta")
        self._getter = getter
        self._max_skew = max_acceptable_skew

    def __repr__(self) -> str:
        return "BybitDemoServerTimeSource(<fixed demo server-time>)"

    def _fetch_body(self) -> Mapping[str, Any]:
        try:
            response = self._getter.get_public(BYBIT_SERVER_TIME_PATH)
        except Exception:
            raise ServerTimeFetchError() from None
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise ServerTimeFetchError()
        body_bytes = getattr(response, "body", None)
        if not isinstance(body_bytes, (bytes, bytearray)):
            raise ServerTimeFetchError()
        try:
            text = bytes(body_bytes).decode("utf-8", "strict")
            body = json.loads(text)
        except (UnicodeDecodeError, ValueError):
            raise ServerTimeParseError("server-time response is malformed") from None
        if not isinstance(body, dict):
            raise ServerTimeParseError("server-time response is malformed")
        return body

    def _validated(self, observation: ServerTimeObservation) -> ServerTimeObservation:
        delta = observation.observed_at - observation.server_time
        if abs(delta) > self._max_skew:
            raise ServerTimeStaleError()
        return observation

    def observe(self, *, observed_at: datetime) -> ServerTimeObservation:
        observed = _utc("observed_at", observed_at)
        body = self._fetch_body()
        try:
            observation = parse_server_time_response(body, observed_at=observed)
        except ServerTimeParseError:
            raise
        return self._validated(observation)

    def as_callable(
        self,
        clock: object,
        *,
        monotonic: Optional[Callable[[], float]] = None,
    ) -> Callable[[], ServerTimeObservation]:
        """Return the zero-argument callable the signed transport expects."""

        if clock is None or not callable(getattr(clock, "now", None)):
            raise TypeError("an explicit wall clock is required")
        mono = monotonic if monotonic is not None else time.monotonic
        if not callable(mono):
            raise TypeError("monotonic must be callable")

        def _observe() -> ServerTimeObservation:
            start_wall = _utc("clock.now()", clock.now())
            try:
                started = float(mono())
            except Exception:
                raise ServerTimeFetchError() from None
            body = self._fetch_body()
            try:
                raw = parse_server_time_response(body, observed_at=start_wall)
            except ServerTimeParseError:
                raise
            try:
                elapsed = float(mono()) - started
            except Exception:
                raise ServerTimeFetchError() from None
            observed_at = start_wall + timedelta(seconds=max(elapsed, 0.0))
            return self._validated(ServerTimeObservation(raw.server_time, observed_at))

        return _observe
