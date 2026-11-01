"""Explicit clock, rate, retry, egress and redaction policies.

These values are conservative offline defaults.  Passing policy validation is
not approval for a real connection.  No policy here calls the network, changes
the OS clock, sleeps implicitly, or creates a transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import threading
from typing import Optional

from backend.execution.read_only_transport import (
    ReadOnlyClock,
    ReadOnlyRequest,
    ReadTransportFailureKind,
)


BYBIT_DEMO_HOST = "api-demo.bybit.com"
BYBIT_DEMO_READ_PATHS = frozenset(
    {
        "/v5/account/wallet-balance",
        "/v5/position/list",
        "/v5/order/realtime",
    }
)
BYBIT_DEMO_KEY_INFO_PATH = "/v5/user/query-api"
BYBIT_DEMO_AUTH_PATHS = BYBIT_DEMO_READ_PATHS | {BYBIT_DEMO_KEY_INFO_PATH}

DEFAULT_RECV_WINDOW_MS = 5_000
MIN_RECV_WINDOW_MS = 1_000
MAX_RECV_WINDOW_MS = 60_000
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000

# Official Bybit condition (checked 2026-10-31 JST):
#   server_time - recv_window <= timestamp < server_time + 1000
# The forward allowance is fixed by the venue at 1000 ms.  It is not loosened by
# policy; only a conservative margin is subtracted from both bounds.
OFFICIAL_MAX_FUTURE_SKEW_MS = 1_000
DEFAULT_TIMESTAMP_MARGIN_MS = 100
DEFAULT_OBSERVATION_UNCERTAINTY_MS = 0


class PolicyErrorCode(str, Enum):
    INVALID_POLICY = "INVALID_POLICY"
    INVALID_REQUEST = "INVALID_REQUEST"
    HOST_NOT_ALLOWED = "HOST_NOT_ALLOWED"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    REDIRECTS_FORBIDDEN = "REDIRECTS_FORBIDDEN"
    PROXY_FORBIDDEN = "PROXY_FORBIDDEN"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REQUEST_BUDGET_EXHAUSTED = "REQUEST_BUDGET_EXHAUSTED"
    CLOCK_OBSERVATION_UNAVAILABLE = "CLOCK_OBSERVATION_UNAVAILABLE"
    CLOCK_OBSERVATION_STALE = "CLOCK_OBSERVATION_STALE"
    CLOCK_SKEW_EXCEEDED = "CLOCK_SKEW_EXCEEDED"


_SAFE_POLICY_MESSAGES = {
    PolicyErrorCode.INVALID_POLICY: "read-only policy is invalid",
    PolicyErrorCode.INVALID_REQUEST: "read-only request violates policy",
    PolicyErrorCode.HOST_NOT_ALLOWED: "request host is not allowed",
    PolicyErrorCode.PATH_NOT_ALLOWED: "request path is not allowed",
    PolicyErrorCode.METHOD_NOT_ALLOWED: "request method is not allowed",
    PolicyErrorCode.REDIRECTS_FORBIDDEN: "redirects are forbidden",
    PolicyErrorCode.PROXY_FORBIDDEN: "proxy use is forbidden",
    PolicyErrorCode.RESPONSE_TOO_LARGE: "response exceeds the configured limit",
    PolicyErrorCode.REQUEST_BUDGET_EXHAUSTED: "read request budget is exhausted",
    PolicyErrorCode.CLOCK_OBSERVATION_UNAVAILABLE: "server-time observation is unavailable",
    PolicyErrorCode.CLOCK_OBSERVATION_STALE: "server-time observation is stale",
    PolicyErrorCode.CLOCK_SKEW_EXCEEDED: "clock skew exceeds the configured limit",
}


class ReadOnlyPolicyError(Exception):
    def __init__(self, code: PolicyErrorCode) -> None:
        try:
            normalized = code if isinstance(code, PolicyErrorCode) else PolicyErrorCode(code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown read-only policy error code") from exc
        self.code = normalized
        super().__init__(_SAFE_POLICY_MESSAGES[normalized])

    @property
    def safe_message(self) -> str:
        return _SAFE_POLICY_MESSAGES[self.code]


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class EgressPolicy:
    """Fixed demo host, GET-only allowlist, no redirects, no proxy."""

    allowed_paths: frozenset[str] = BYBIT_DEMO_AUTH_PATHS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_paths, frozenset) or not self.allowed_paths:
            raise ValueError("allowed_paths must be a non-empty frozenset")
        if not self.allowed_paths <= BYBIT_DEMO_AUTH_PATHS:
            raise ValueError("allowed_paths must be a subset of the demo read paths")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be numeric")
        if not 0 < float(self.timeout_seconds) <= 30.0:
            raise ValueError("timeout_seconds must be in (0, 30]")
        if isinstance(self.max_response_bytes, bool) or not isinstance(
            self.max_response_bytes, int
        ):
            raise ValueError("max_response_bytes must be an integer")
        if not 1 <= self.max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be in [1, 10000000]")

    @property
    def host(self) -> str:
        return BYBIT_DEMO_HOST

    @property
    def method(self) -> str:
        return "GET"

    @property
    def allow_redirects(self) -> bool:
        return False

    @property
    def allow_proxy(self) -> bool:
        return False

    def validate_request(self, request: ReadOnlyRequest) -> None:
        if not isinstance(request, ReadOnlyRequest):
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_REQUEST)
        if request.method != self.method:
            raise ReadOnlyPolicyError(PolicyErrorCode.METHOD_NOT_ALLOWED)
        if request.path not in self.allowed_paths:
            raise ReadOnlyPolicyError(PolicyErrorCode.PATH_NOT_ALLOWED)

    def validate_signed_parts(self, *, method: str, host: str, path: str) -> None:
        if method != self.method:
            raise ReadOnlyPolicyError(PolicyErrorCode.METHOD_NOT_ALLOWED)
        if host != self.host:
            raise ReadOnlyPolicyError(PolicyErrorCode.HOST_NOT_ALLOWED)
        if path not in self.allowed_paths:
            raise ReadOnlyPolicyError(PolicyErrorCode.PATH_NOT_ALLOWED)


class ClockAssessmentStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    SKEW = "SKEW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ServerTimeObservation:
    server_time: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "server_time", _utc("server_time", self.server_time))
        object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))


@dataclass(frozen=True)
class ClockAssessment:
    status: ClockAssessmentStatus
    observation_age: Optional[timedelta] = None
    skew: Optional[timedelta] = None
    ahead_ms: Optional[int] = None
    behind_ms: Optional[int] = None
    effective_recv_window_ms: Optional[int] = None
    effective_margin_ms: Optional[int] = None

    @property
    def fresh(self) -> bool:
        return self.status is ClockAssessmentStatus.FRESH


@dataclass(frozen=True)
class ClockPolicy:
    """Asymmetric, projected server-time validation for an injected observation.

    The local timestamp is checked against the official Bybit condition using an
    estimate of server time projected from the observation, not by comparing an
    old observation directly with the current local clock.  The estimate assumes
    both clocks advance at the same rate; one-way network delay and clock drift
    are not measured.  ``observation_uncertainty_ms`` lets the caller reserve a
    delay/uncertainty allowance, and ``timestamp_margin_ms`` reserves a fixed
    safety margin inside both official bounds.

    ``require_server_time=False`` disables server-time validation entirely and
    relies on the local wall clock.  That mode is not approved for a real
    connection.  This policy still requires a fresh observation when enabled.
    """

    max_server_time_age: timedelta = timedelta(seconds=5)
    timestamp_margin_ms: int = DEFAULT_TIMESTAMP_MARGIN_MS
    observation_uncertainty_ms: int = DEFAULT_OBSERVATION_UNCERTAINTY_MS
    require_server_time: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.max_server_time_age, timedelta) or self.max_server_time_age <= timedelta(0):
            raise ValueError("max_server_time_age must be a positive timedelta")
        for name in ("timestamp_margin_ms", "observation_uncertainty_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.effective_margin_ms >= OFFICIAL_MAX_FUTURE_SKEW_MS:
            raise ValueError("timestamp margin and uncertainty leave no future allowance")
        if type(self.require_server_time) is not bool:
            raise TypeError("require_server_time must be bool")

    @property
    def effective_margin_ms(self) -> int:
        return self.timestamp_margin_ms + self.observation_uncertainty_ms

    def now_utc(self, clock: ReadOnlyClock) -> datetime:
        if clock is None or not callable(getattr(clock, "now", None)):
            raise ReadOnlyPolicyError(PolicyErrorCode.CLOCK_OBSERVATION_UNAVAILABLE)
        return _utc("clock.now()", clock.now())

    def _validated_bounds(
        self, timestamp_ms: object, recv_window_ms: object
    ) -> tuple[int, int, int]:
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        if timestamp_ms < 0:
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        if isinstance(recv_window_ms, bool) or not isinstance(recv_window_ms, int):
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        if not MIN_RECV_WINDOW_MS <= recv_window_ms <= MAX_RECV_WINDOW_MS:
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        if self.effective_margin_ms >= recv_window_ms:
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        future_limit_ms = OFFICIAL_MAX_FUTURE_SKEW_MS - self.effective_margin_ms
        behind_limit_ms = recv_window_ms - self.effective_margin_ms
        if future_limit_ms <= 0 or behind_limit_ms <= 0:
            raise ReadOnlyPolicyError(PolicyErrorCode.INVALID_POLICY)
        return future_limit_ms, behind_limit_ms, self.effective_margin_ms

    def assess(
        self,
        observation: Optional[ServerTimeObservation],
        now: datetime,
        *,
        timestamp_ms: Optional[int] = None,
        recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
    ) -> ClockAssessment:
        current = _utc("now", now)
        if timestamp_ms is None:
            timestamp_ms = int(current.timestamp() * 1000)
        future_limit_ms, behind_limit_ms, margin_ms = self._validated_bounds(
            timestamp_ms, recv_window_ms
        )
        if observation is None:
            return ClockAssessment(ClockAssessmentStatus.UNKNOWN)
        if not isinstance(observation, ServerTimeObservation):
            return ClockAssessment(ClockAssessmentStatus.UNKNOWN)
        age = current - observation.observed_at
        if age > self.max_server_time_age or age < -self.max_server_time_age:
            return ClockAssessment(
                ClockAssessmentStatus.STALE,
                observation_age=age,
                effective_recv_window_ms=recv_window_ms,
                effective_margin_ms=margin_ms,
            )
        # Compare the exact signed timestamp with server time projected to the
        # signed timestamp's wall-clock position.  The projection uses the
        # observation's age; it does not treat the old observation as "now".
        estimated_server_at_now = observation.server_time + age
        estimated_server_ms = int(estimated_server_at_now.timestamp() * 1000)
        offset_ms = timestamp_ms - estimated_server_ms
        skew = timedelta(milliseconds=offset_ms)
        ahead_ms = max(offset_ms, 0)
        behind_ms = max(-offset_ms, 0)
        too_far_ahead = offset_ms >= future_limit_ms
        too_far_behind = -offset_ms > behind_limit_ms
        if too_far_ahead or too_far_behind:
            return ClockAssessment(
                ClockAssessmentStatus.SKEW,
                observation_age=age,
                skew=skew,
                ahead_ms=ahead_ms,
                behind_ms=behind_ms,
                effective_recv_window_ms=recv_window_ms,
                effective_margin_ms=margin_ms,
            )
        return ClockAssessment(
            ClockAssessmentStatus.FRESH,
            observation_age=age,
            skew=skew,
            ahead_ms=ahead_ms,
            behind_ms=behind_ms,
            effective_recv_window_ms=recv_window_ms,
            effective_margin_ms=margin_ms,
        )

    def require_fresh(
        self,
        observation: Optional[ServerTimeObservation],
        now: datetime,
        *,
        timestamp_ms: Optional[int] = None,
        recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
    ) -> ClockAssessment:
        assessment = self.assess(
            observation,
            now,
            timestamp_ms=timestamp_ms,
            recv_window_ms=recv_window_ms,
        )
        if assessment.status is ClockAssessmentStatus.STALE:
            raise ReadOnlyPolicyError(PolicyErrorCode.CLOCK_OBSERVATION_STALE)
        if assessment.status is ClockAssessmentStatus.SKEW:
            raise ReadOnlyPolicyError(PolicyErrorCode.CLOCK_SKEW_EXCEEDED)
        if assessment.status is ClockAssessmentStatus.UNKNOWN:
            raise ReadOnlyPolicyError(PolicyErrorCode.CLOCK_OBSERVATION_UNAVAILABLE)
        return assessment


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retries; authentication/permission failures are never retried.

    HTTP status and HTTP 200 + venue ``retCode`` are both handled here so there
    is exactly one retry owner.  Only the two documented venue codes (10002
    clock/recv-window and 10006 rate limit) are retryable.  A 10002 retry is
    attempted only when a server-time source is available, because retrying
    without new clock information cannot improve the request.
    """

    max_attempts: int = 2
    retry_delay_seconds: float = 0.0
    retryable_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    retryable_failure_kinds: frozenset[ReadTransportFailureKind] = frozenset(
        {ReadTransportFailureKind.TIMEOUT, ReadTransportFailureKind.CONNECTION_FAILED}
    )
    retryable_ret_codes: frozenset[int] = frozenset({10002, 10006})
    total_deadline_seconds: float = 10.0
    max_retry_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise ValueError("max_attempts must be an integer")
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be in [1, 3]")
        for name in ("retry_delay_seconds", "total_deadline_seconds", "max_retry_delay_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
        if not 0 <= float(self.retry_delay_seconds) <= 5:
            raise ValueError("retry_delay_seconds must be in [0, 5]")
        if not 0 < float(self.total_deadline_seconds) <= 60:
            raise ValueError("total_deadline_seconds must be in (0, 60]")
        if not 0 <= float(self.max_retry_delay_seconds) <= 30:
            raise ValueError("max_retry_delay_seconds must be in [0, 30]")
        if float(self.retry_delay_seconds) > float(self.max_retry_delay_seconds):
            raise ValueError("retry_delay_seconds must not exceed max_retry_delay_seconds")
        if not isinstance(self.retryable_statuses, frozenset) or not self.retryable_statuses <= {
            429,
            500,
            502,
            503,
            504,
        }:
            raise ValueError("retryable statuses are not allowed")
        if not isinstance(self.retryable_failure_kinds, frozenset) or not (
            self.retryable_failure_kinds
            <= {
                ReadTransportFailureKind.TIMEOUT,
                ReadTransportFailureKind.CONNECTION_FAILED,
            }
        ):
            raise ValueError("retryable failure kinds are not allowed")
        if not isinstance(self.retryable_ret_codes, frozenset) or not (
            self.retryable_ret_codes <= {10002, 10006}
        ):
            raise ValueError("retryable venue return codes are not allowed")

    @property
    def max_retries(self) -> int:
        return self.max_attempts - 1

    def should_retry_failure(
        self, kind: ReadTransportFailureKind, attempt: int
    ) -> bool:
        return attempt < self.max_attempts and kind in self.retryable_failure_kinds

    def should_retry_status(self, status_code: int, attempt: int) -> bool:
        if status_code in (401, 403):
            return False
        return attempt < self.max_attempts and status_code in self.retryable_statuses

    def should_retry_ret_code(
        self, ret_code: object, attempt: int, *, clock_source_available: bool
    ) -> bool:
        if isinstance(ret_code, bool) or not isinstance(ret_code, int):
            return False
        if ret_code not in self.retryable_ret_codes:
            return False
        if attempt >= self.max_attempts:
            return False
        if ret_code == 10002 and not clock_source_available:
            return False
        return True

    def bound_delay(self, seconds: object) -> float:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            return 0.0
        value = float(seconds)
        if value <= 0:
            return 0.0
        return min(value, float(self.max_retry_delay_seconds))


class RequestBudget:
    """Thread-safe, caller-owned request counter; it does not sleep or refill.

    The scope is one transport instance (``TRANSPORT_LOCAL``).  Callers may share
    one instance between transports to obtain a process-local bound.  Cross
    process budget sharing is not implemented; a process restart or a second
    process gets a separate counter.
    """

    scope = "TRANSPORT_LOCAL"

    def __init__(self, max_requests: int) -> None:
        if isinstance(max_requests, bool) or not isinstance(max_requests, int):
            raise ValueError("max_requests must be an integer")
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self._max_requests = max_requests
        self._used = 0
        self._lock = threading.Lock()

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._max_requests - self._used

    def consume(self) -> None:
        with self._lock:
            if self._used >= self._max_requests:
                raise ReadOnlyPolicyError(PolicyErrorCode.REQUEST_BUDGET_EXHAUSTED)
            self._used += 1


@dataclass(frozen=True)
class ReadOnlySafetyPolicy:
    egress: EgressPolicy = field(default_factory=EgressPolicy)
    clock: ClockPolicy = field(default_factory=ClockPolicy)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    max_requests: int = 50
    recv_window_ms: int = DEFAULT_RECV_WINDOW_MS

    def __post_init__(self) -> None:
        if not isinstance(self.egress, EgressPolicy):
            raise TypeError("egress must be EgressPolicy")
        if not isinstance(self.clock, ClockPolicy):
            raise TypeError("clock must be ClockPolicy")
        if not isinstance(self.retry, RetryPolicy):
            raise TypeError("retry must be RetryPolicy")
        if isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int):
            raise ValueError("max_requests must be an integer")
        if not 1 <= self.max_requests <= 1_000:
            raise ValueError("max_requests must be in [1, 1000]")
        if isinstance(self.recv_window_ms, bool) or not isinstance(self.recv_window_ms, int):
            raise ValueError("recv_window_ms must be an integer")
        if not MIN_RECV_WINDOW_MS <= self.recv_window_ms <= MAX_RECV_WINDOW_MS:
            raise ValueError("recv_window_ms is outside the supported range")
        if self.clock.effective_margin_ms >= self.recv_window_ms:
            raise ValueError(
                "clock timestamp margin and uncertainty must be smaller than recv_window_ms"
            )

    def new_budget(self) -> RequestBudget:
        return RequestBudget(self.max_requests)
