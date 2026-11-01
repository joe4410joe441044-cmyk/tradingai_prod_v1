"""Signed read-only transport for the fixed Bybit Demo V5 profile.

The transport only talks to an explicitly injected HTTP sender.  It contains no
socket, requests, httpx, urllib client, default sender, proxy handling, proxy
environment lookup, retry sleep, or order path.  Authentication headers and the
signature live only inside the sender request and are redacted from its repr.

Except for the key-info bootstrap path, every request requires an injected
``GeneralReadAuthorizationGate``.  The gate verifies current account binding,
readiness freshness, revisions, credential reference, and resolved generation
before send; generation and readiness are checked again after the response so a
rotated or disabled binding is not returned as current data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import time
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple

from backend.accounts.models import AccountType, ExecutionMode, ExecutionVenue
from backend.execution.bybit_v5_signing import (
    canonical_query,
    sign_get,
    validate_recv_window,
)
from backend.execution.bybit_key_info import (
    KEY_INFO_PATH,
    GeneralReadAuthorizationGate,
)
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadOnlyAdapterConfiguration,
)
from backend.execution.read_only_credentials import (
    CredentialProviderError,
    CredentialScope,
    ReadOnlyCredential,
    ReadOnlyCredentialProvider,
)
from backend.execution.read_only_policy import (
    BYBIT_DEMO_HOST,
    ClockPolicy,
    PolicyErrorCode,
    ReadOnlyPolicyError,
    ReadOnlySafetyPolicy,
    RequestBudget,
    ServerTimeObservation,
)
from backend.execution.read_only_transport import (
    ReadOnlyClock,
    ReadOnlyRequest,
    ReadOnlyResponse,
    ReadTransportError,
    ReadTransportFailureKind,
)


_HEADER_API_KEY = "X-BAPI-API-KEY"
_HEADER_TIMESTAMP = "X-BAPI-TIMESTAMP"
_HEADER_RECV_WINDOW = "X-BAPI-RECV-WINDOW"
_HEADER_SIGN = "X-BAPI-SIGN"
_AUTH_HEADER_NAMES = frozenset(
    {_HEADER_API_KEY, _HEADER_TIMESTAMP, _HEADER_RECV_WINDOW, _HEADER_SIGN}
)
# Optional, non-auth headers are allowed only from this explicit allowlist.  The
# official HMAC guide uses the four auth headers only; these entries are optional
# interoperability headers, not required fields.  Host/Cookie/Authorization and
# any other caller-injected header are rejected.
NON_AUTH_HEADER_ALLOWLIST = frozenset({"content-type", "x-bapi-sign-type"})
# Only these response headers may be retained for retry/rate diagnostics.  The
# raw response header set is never copied into the public response DTO.
SAFE_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "content-length",
        "retry-after",
        "x-bapi-limit-status",
        "x-bapi-limit",
        "x-bapi-limit-reset-timestamp",
    }
)
_MAX_SAFE_HEADER_VALUE = 256
_HEX = frozenset("0123456789abcdef")


class HttpSenderFailureKind(str, Enum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    TLS_FAILED = "TLS_FAILED"
    PROXY_FAILED = "PROXY_FAILED"
    SENDER_REJECTED = "SENDER_REJECTED"
    # Added for the offline HTTP sender's streaming boundary.  These are additive
    # members: existing senders that only raise the original kinds are unaffected.
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


_SENDER_MESSAGES = {
    HttpSenderFailureKind.CONNECTION_FAILED: "http sender connection failed",
    HttpSenderFailureKind.TIMEOUT: "http sender timed out",
    HttpSenderFailureKind.TLS_FAILED: "http sender TLS failed",
    HttpSenderFailureKind.PROXY_FAILED: "http sender proxy failed",
    HttpSenderFailureKind.SENDER_REJECTED: "http sender rejected the request",
    HttpSenderFailureKind.RESPONSE_TOO_LARGE: "http sender response exceeded the limit",
    HttpSenderFailureKind.INVALID_RESPONSE: "http sender received an invalid response",
}


class HttpSenderError(Exception):
    """Fixed-text sender failure; no request/response content is retained."""

    def __init__(self, kind: HttpSenderFailureKind) -> None:
        try:
            normalized = (
                kind if isinstance(kind, HttpSenderFailureKind) else HttpSenderFailureKind(kind)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown http sender failure kind") from exc
        self.kind = normalized
        super().__init__(_SENDER_MESSAGES[normalized])


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _safe_text(name: str, value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    if not allow_empty and not value:
        raise ValueError(f"{name} must be non-empty")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError(f"{name} must be printable ASCII without spaces")
    return value


@dataclass(frozen=True)
class SignedReadRequest:
    """Exact sender contract.  Auth headers are never rendered by repr/str."""

    method: str
    host: str
    path: str
    query: str
    headers: Tuple[Tuple[str, str], ...] = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int
    allow_redirects: bool = False
    allow_proxy: bool = False

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise ValueError("signed read request method must be GET")
        if self.host != BYBIT_DEMO_HOST:
            raise ValueError("signed read request host must be the demo host")
        path = _safe_text("path", self.path)
        if not path.startswith("/v5/"):
            raise ValueError("signed read request path must be a Bybit V5 path")
        if any(token in path for token in ("://", "?", "#", "\\", "..", "%")):
            raise ValueError("signed read request path must be canonical")
        if any(ord(char) > 126 for char in path):
            raise ValueError("signed read request path must be printable ASCII")
        query = self.query
        if not isinstance(query, str):
            raise TypeError("query must be text")
        if query.startswith("?") or "#" in query or any(ord(char) < 32 or ord(char) > 126 for char in query):
            raise ValueError("query must be a canonical encoded string")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be numeric")
        if not 0 < float(self.timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be in (0, 30]")
        if isinstance(self.max_response_bytes, bool) or not isinstance(
            self.max_response_bytes, int
        ):
            raise ValueError("max_response_bytes must be an integer")
        if not 1 <= self.max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be in [1, 10000000]")
        if self.allow_redirects is not False:
            raise ValueError("signed read request must forbid redirects")
        if self.allow_proxy is not False:
            raise ValueError("signed read request must forbid proxies")

        try:
            entries = tuple(self.headers)
        except TypeError as exc:
            raise TypeError("headers must be a tuple of (name, value) pairs") from exc
        names: list[str] = []
        normalized_names: set[str] = set()
        values: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("headers must be a tuple of (name, value) pairs")
            name, value = entry
            name = _safe_text("header name", name)
            value = _safe_text("header value", value)
            lowered = name.lower()
            if lowered in normalized_names:
                raise ValueError("header names must not repeat")
            normalized_names.add(lowered)
            names.append(name)
            values[name] = value
        if not _AUTH_HEADER_NAMES <= set(names):
            raise ValueError("signed read request must carry the fixed auth headers")
        extra_names = set(names) - _AUTH_HEADER_NAMES
        for name in extra_names:
            if name.lower() not in NON_AUTH_HEADER_ALLOWLIST:
                raise ValueError("signed read request non-auth header is not allowed")
        signature = values[_HEADER_SIGN]
        if len(signature) != 64 or any(char not in _HEX for char in signature):
            raise ValueError("signature must be a lowercase SHA-256 hex digest")
        for name in (_HEADER_TIMESTAMP, _HEADER_RECV_WINDOW):
            if not values[name].isdigit():
                raise ValueError("timestamp and recv window must be decimal digits")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "headers", tuple(entries))

    def header(self, name: str) -> str:
        for key, value in self.headers:
            if key == name:
                return value
        raise KeyError(name)

    def header_dict(self) -> dict[str, str]:
        return {key: value for key, value in self.headers}

    @property
    def url(self) -> str:
        base = f"https://{self.host}{self.path}"
        return f"{base}?{self.query}" if self.query else base

    def __repr__(self) -> str:
        return (
            "SignedReadRequest("
            f"method={self.method!r}, host={self.host!r}, path={self.path!r}, "
            f"query_length={len(self.query)}, headers=<redacted>, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_response_bytes={self.max_response_bytes!r}, "
            f"allow_redirects=False, allow_proxy=False)"
        )


@dataclass(frozen=True)
class HttpSenderResponse:
    status_code: int
    body: bytes
    received_at: datetime
    headers: Tuple[Tuple[str, str], ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise TypeError("status_code must be an integer")
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if not isinstance(self.body, bytes):
            raise TypeError("body must be bytes")
        object.__setattr__(self, "received_at", _utc("received_at", self.received_at))
        try:
            entries = tuple(self.headers)
        except TypeError as exc:
            raise TypeError("headers must be a tuple of (name, value) pairs") from exc
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("headers must be a tuple of (name, value) pairs")
            name, value = entry
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("response header names and values must be text")
            lowered = name.lower()
            if lowered not in SAFE_RESPONSE_HEADER_ALLOWLIST:
                raise ValueError("response header is not on the safe allowlist")
            if lowered in seen:
                raise ValueError("response header names must not repeat")
            if not value or len(value) > _MAX_SAFE_HEADER_VALUE:
                raise ValueError("response header value is invalid")
            if any(ord(char) < 32 or ord(char) > 126 for char in value):
                raise ValueError("response header value is not printable ASCII")
            seen.add(lowered)
        object.__setattr__(self, "headers", entries)

    def safe_header(self, name: str) -> Optional[str]:
        if not isinstance(name, str):
            return None
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None


class HttpRequestSender(Protocol):
    def send(self, request: SignedReadRequest) -> HttpSenderResponse: ...


_POLICY_FAILURE_MAP = {
    PolicyErrorCode.INVALID_POLICY: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.INVALID_REQUEST: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.HOST_NOT_ALLOWED: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.PATH_NOT_ALLOWED: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.METHOD_NOT_ALLOWED: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.REDIRECTS_FORBIDDEN: ReadTransportFailureKind.REDIRECT_REJECTED,
    PolicyErrorCode.PROXY_FORBIDDEN: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.RESPONSE_TOO_LARGE: ReadTransportFailureKind.RESPONSE_TOO_LARGE,
    PolicyErrorCode.REQUEST_BUDGET_EXHAUSTED: ReadTransportFailureKind.POLICY_REJECTED,
    PolicyErrorCode.CLOCK_OBSERVATION_UNAVAILABLE: ReadTransportFailureKind.CLOCK_REJECTED,
    PolicyErrorCode.CLOCK_OBSERVATION_STALE: ReadTransportFailureKind.CLOCK_REJECTED,
    PolicyErrorCode.CLOCK_SKEW_EXCEEDED: ReadTransportFailureKind.CLOCK_REJECTED,
}

_SENDER_FAILURE_MAP = {
    HttpSenderFailureKind.CONNECTION_FAILED: ReadTransportFailureKind.CONNECTION_FAILED,
    HttpSenderFailureKind.TIMEOUT: ReadTransportFailureKind.TIMEOUT,
    HttpSenderFailureKind.TLS_FAILED: ReadTransportFailureKind.STATE_UNKNOWN,
    HttpSenderFailureKind.PROXY_FAILED: ReadTransportFailureKind.STATE_UNKNOWN,
    HttpSenderFailureKind.SENDER_REJECTED: ReadTransportFailureKind.STATE_UNKNOWN,
    HttpSenderFailureKind.RESPONSE_TOO_LARGE: ReadTransportFailureKind.RESPONSE_TOO_LARGE,
    HttpSenderFailureKind.INVALID_RESPONSE: ReadTransportFailureKind.INVALID_RESPONSE,
}


class BybitV5SignedReadTransport:
    """Demo-host, GET-only signed transport over an injected sender."""

    def __init__(
        self,
        binding: ReadOnlyAdapterConfiguration,
        sender: HttpRequestSender,
        credential_provider: ReadOnlyCredentialProvider,
        clock: ReadOnlyClock,
        *,
        policy: ReadOnlySafetyPolicy,
        server_time_source: Optional[Callable[[], ServerTimeObservation]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        budget: Optional[RequestBudget] = None,
        monotonic: Optional[Callable[[], float]] = None,
        general_read_gate: Optional[GeneralReadAuthorizationGate] = None,
    ) -> None:
        if not isinstance(binding, ReadOnlyAdapterConfiguration):
            raise TypeError("binding must be ReadOnlyAdapterConfiguration")
        if binding.account_type is not AccountType.PROP:
            raise ValueError("signed read transport only supports PROP accounts")
        if binding.execution_mode is not ExecutionMode.EXTERNAL_SIMULATION:
            raise ValueError("signed read transport requires EXTERNAL_SIMULATION")
        if binding.execution_venue is not ExecutionVenue.BYBIT_DEMO:
            raise ValueError("signed read transport requires BYBIT_DEMO")
        if binding.endpoint_profile is not EndpointProfile.BYBIT_DEMO_V5:
            raise ValueError("signed read transport requires the BYBIT_DEMO_V5 profile")
        if binding.credential_reference is None:
            raise ValueError("signed read transport requires a credential reference")
        if sender is None or not callable(getattr(sender, "send", None)):
            raise TypeError("an explicit HTTP sender is required")
        if credential_provider is None or not callable(
            getattr(credential_provider, "resolve", None)
        ):
            raise TypeError("an explicit credential provider is required")
        if clock is None or not callable(getattr(clock, "now", None)):
            raise TypeError("an explicit clock is required")
        if not isinstance(policy, ReadOnlySafetyPolicy):
            raise TypeError("policy must be ReadOnlySafetyPolicy")
        if not isinstance(policy.clock, ClockPolicy):
            raise TypeError("policy.clock must be ClockPolicy")
        if server_time_source is not None and not callable(server_time_source):
            raise TypeError("server_time_source must be callable or None")
        if sleep is not None and not callable(sleep):
            raise TypeError("sleep must be callable or None")
        if policy.retry.retry_delay_seconds > 0 and sleep is None:
            raise ValueError("a retry delay requires an explicitly injected sleep callable")
        if budget is not None and not isinstance(budget, RequestBudget):
            raise TypeError("budget must be a RequestBudget or None")
        if monotonic is not None and not callable(monotonic):
            raise TypeError("monotonic must be callable or None")
        if general_read_gate is not None and not isinstance(
            general_read_gate, GeneralReadAuthorizationGate
        ):
            raise TypeError(
                "general_read_gate must be GeneralReadAuthorizationGate or None"
            )
        validate_recv_window(policy.recv_window_ms)
        self._binding = binding
        self._sender = sender
        self._provider = credential_provider
        self._clock = clock
        self._policy = policy
        self._server_time_source = server_time_source
        self._sleep = sleep
        self._budget = budget if budget is not None else policy.new_budget()
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._general_read_gate = general_read_gate
        self._last_credential_generation: Optional[str] = None
        self._scope = CredentialScope(
            binding.account_id,
            binding.execution_mode,
            binding.execution_venue,
            binding.endpoint_profile,
        )

    @property
    def binding(self) -> ReadOnlyAdapterConfiguration:
        return self._binding

    @property
    def budget(self) -> RequestBudget:
        return self._budget

    @property
    def clock(self) -> ReadOnlyClock:
        return self._clock

    @property
    def last_credential_generation(self) -> Optional[str]:
        """Opaque, non-secret rotation identifier of the last resolved credential."""

        return self._last_credential_generation

    @property
    def policy(self) -> ReadOnlySafetyPolicy:
        return self._policy

    @property
    def egress_host(self) -> str:
        return self._policy.egress.host

    def _now(self) -> datetime:
        return self._policy.clock.now_utc(self._clock)

    def _acquire_clock(self, recv_window_ms: int) -> tuple[datetime, int]:
        try:
            now = self._now()
        except ReadOnlyPolicyError:
            raise ReadTransportError(ReadTransportFailureKind.CLOCK_REJECTED) from None
        except Exception:
            raise ReadTransportError(ReadTransportFailureKind.CLOCK_REJECTED) from None
        timestamp_ms = int(now.timestamp() * 1000)
        policy = self._policy.clock
        observation: Optional[ServerTimeObservation] = None
        if policy.require_server_time:
            if self._server_time_source is None:
                raise ReadTransportError(ReadTransportFailureKind.CLOCK_REJECTED)
            try:
                observation = self._server_time_source()
            except Exception:
                raise ReadTransportError(ReadTransportFailureKind.CLOCK_REJECTED) from None
        elif self._server_time_source is not None:
            try:
                observation = self._server_time_source()
            except Exception:
                observation = None
        if observation is not None:
            try:
                policy.require_fresh(
                    observation,
                    now,
                    timestamp_ms=timestamp_ms,
                    recv_window_ms=recv_window_ms,
                )
            except ReadOnlyPolicyError as exc:
                raise ReadTransportError(
                    _POLICY_FAILURE_MAP.get(exc.code, ReadTransportFailureKind.CLOCK_REJECTED)
                ) from None
        elif policy.require_server_time:
            raise ReadTransportError(ReadTransportFailureKind.CLOCK_REJECTED)
        return now, timestamp_ms

    def _resolve_credential(self) -> ReadOnlyCredential:
        try:
            credential = self._provider.resolve(
                self._binding.credential_reference, self._scope
            )
        except CredentialProviderError:
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED) from None
        except Exception:
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED) from None
        if not isinstance(credential, ReadOnlyCredential):
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED)
        if credential.reference != self._binding.credential_reference:
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED)
        if credential.scope is None or credential.scope != self._scope:
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED)
        if not isinstance(credential.credential_generation, str):
            raise ReadTransportError(ReadTransportFailureKind.CREDENTIAL_REJECTED)
        return credential

    def _authorize_general_read(
        self, request: ReadOnlyRequest, credential_generation: str
    ) -> None:
        if request.path == KEY_INFO_PATH:
            return
        gate = self._general_read_gate
        if gate is None:
            raise ReadTransportError(ReadTransportFailureKind.READINESS_REJECTED)
        try:
            gate.authorize(
                binding=self._binding,
                credential_generation=credential_generation,
                now=self._now(),
            )
        except Exception:
            raise ReadTransportError(
                ReadTransportFailureKind.READINESS_REJECTED
            ) from None

    def _build_signed_request(
        self, request: ReadOnlyRequest, *, started_at: float
    ) -> tuple[SignedReadRequest, str]:
        recv_window = validate_recv_window(self._policy.recv_window_ms)
        query = canonical_query(request.query)
        credential = self._resolve_credential()
        credential_generation = credential.credential_generation
        self._authorize_general_read(request, credential_generation)
        _now, timestamp_ms = self._acquire_clock(recv_window)
        api_key, api_secret = credential.signing_material()
        try:
            signature = sign_get(
                api_secret=api_secret,
                api_key=api_key,
                timestamp_ms=timestamp_ms,
                recv_window_ms=recv_window,
                encoded_query=query,
            )
        finally:
            del api_secret
            del credential
        headers = (
            (_HEADER_API_KEY, api_key),
            (_HEADER_TIMESTAMP, str(timestamp_ms)),
            (_HEADER_RECV_WINDOW, str(recv_window)),
            (_HEADER_SIGN, signature),
        )
        try:
            self._policy.egress.validate_signed_parts(
                method=request.method, host=BYBIT_DEMO_HOST, path=request.path
            )
        except ReadOnlyPolicyError as exc:
            raise ReadTransportError(
                _POLICY_FAILURE_MAP.get(exc.code, ReadTransportFailureKind.POLICY_REJECTED)
            ) from None
        remaining = self._remaining_deadline(started_at)
        signed = SignedReadRequest(
            method=request.method,
            host=BYBIT_DEMO_HOST,
            path=request.path,
            query=query,
            headers=headers,
            timeout_seconds=min(float(self._policy.egress.timeout_seconds), remaining),
            max_response_bytes=self._policy.egress.max_response_bytes,
            allow_redirects=False,
            allow_proxy=False,
        )
        return signed, credential_generation

    def _maybe_sleep(self, delay: object = None) -> None:
        value = (
            float(self._policy.retry.retry_delay_seconds)
            if delay is None
            else self._policy.retry.bound_delay(delay)
        )
        if value > 0 and self._sleep is not None:
            self._sleep(value)

    def _monotonic_now(self) -> float:
        try:
            return float(self._monotonic())
        except Exception:
            raise ReadTransportError(ReadTransportFailureKind.STATE_UNKNOWN) from None

    def _deadline_exceeded(self, started_at: float) -> bool:
        deadline = float(self._policy.retry.total_deadline_seconds)
        return (self._monotonic_now() - started_at) >= deadline

    def _remaining_deadline(self, started_at: float) -> float:
        remaining = float(self._policy.retry.total_deadline_seconds) - (
            self._monotonic_now() - started_at
        )
        if remaining <= 0:
            raise ReadTransportError(ReadTransportFailureKind.TIMEOUT)
        return remaining

    def _revalidate_generation_and_readiness(
        self, request: ReadOnlyRequest, expected_generation: str
    ) -> None:
        credential = self._resolve_credential()
        try:
            current_generation = credential.credential_generation
        finally:
            del credential
        if current_generation != expected_generation:
            raise ReadTransportError(ReadTransportFailureKind.READINESS_REJECTED)
        self._authorize_general_read(request, current_generation)

    def _retry_delay_for(self, response: HttpSenderResponse) -> float:
        """Use a bounded rate-reset/Retry-After hint, else the configured delay."""

        candidates: list[float] = [float(self._policy.retry.retry_delay_seconds)]
        reset_raw = response.safe_header("X-Bapi-Limit-Reset-Timestamp")
        if reset_raw is not None and reset_raw.isdigit():
            try:
                now_ms = int(self._now().timestamp() * 1000)
                candidates.append(max((int(reset_raw) - now_ms) / 1000.0, 0.0))
            except Exception:
                pass
        retry_after = response.safe_header("Retry-After")
        if retry_after is not None and retry_after.isdigit():
            candidates.append(float(retry_after))
        return self._policy.retry.bound_delay(max(candidates))

    def _parse_body(self, body: bytes) -> Optional[Mapping[str, Any]]:
        try:
            decoded = body.decode("utf-8")
            parsed = json.loads(decoded)
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None

    def send(self, request: ReadOnlyRequest) -> ReadOnlyResponse:
        try:
            self._policy.egress.validate_request(request)
        except ReadOnlyPolicyError as exc:
            raise ReadTransportError(
                _POLICY_FAILURE_MAP.get(exc.code, ReadTransportFailureKind.POLICY_REJECTED)
            ) from None

        started_at = self._monotonic_now()
        attempt = 0
        while True:
            attempt += 1
            if attempt > 1 and self._deadline_exceeded(started_at):
                raise ReadTransportError(ReadTransportFailureKind.TIMEOUT)
            try:
                self._budget.consume()
            except ReadOnlyPolicyError as exc:
                raise ReadTransportError(
                    _POLICY_FAILURE_MAP.get(exc.code, ReadTransportFailureKind.POLICY_REJECTED)
                ) from None
            try:
                signed, credential_generation = self._build_signed_request(
                    request, started_at=started_at
                )
            except ReadTransportError:
                raise
            except Exception:
                raise ReadTransportError(ReadTransportFailureKind.POLICY_REJECTED) from None
            try:
                raw = self._sender.send(signed)
            except HttpSenderError as exc:
                kind = _SENDER_FAILURE_MAP.get(
                    exc.kind, ReadTransportFailureKind.STATE_UNKNOWN
                )
                if self._policy.retry.should_retry_failure(kind, attempt):
                    if self._deadline_exceeded(started_at):
                        raise ReadTransportError(ReadTransportFailureKind.TIMEOUT) from None
                    self._maybe_sleep()
                    continue
                raise ReadTransportError(kind) from None
            except Exception:
                raise ReadTransportError(ReadTransportFailureKind.STATE_UNKNOWN) from None
            self._remaining_deadline(started_at)
            if not isinstance(raw, HttpSenderResponse):
                raise ReadTransportError(ReadTransportFailureKind.INVALID_RESPONSE)
            self._revalidate_generation_and_readiness(
                request, credential_generation
            )
            self._last_credential_generation = credential_generation
            if len(raw.body) > self._policy.egress.max_response_bytes:
                raise ReadTransportError(ReadTransportFailureKind.RESPONSE_TOO_LARGE)
            if 300 <= raw.status_code < 400:
                raise ReadTransportError(ReadTransportFailureKind.REDIRECT_REJECTED)
            if self._policy.retry.should_retry_status(raw.status_code, attempt):
                if self._deadline_exceeded(started_at):
                    raise ReadTransportError(ReadTransportFailureKind.TIMEOUT)
                self._maybe_sleep()
                continue
            body = self._parse_body(raw.body)
            if body is None:
                if 200 <= raw.status_code < 300:
                    raise ReadTransportError(ReadTransportFailureKind.INVALID_RESPONSE)
                body = {}
            ret_code = body.get("retCode")
            if 200 <= raw.status_code < 300 and self._policy.retry.should_retry_ret_code(
                ret_code,
                attempt,
                clock_source_available=self._server_time_source is not None,
            ):
                if self._deadline_exceeded(started_at):
                    raise ReadTransportError(ReadTransportFailureKind.TIMEOUT)
                self._maybe_sleep(self._retry_delay_for(raw))
                continue
            self._remaining_deadline(started_at)
            return ReadOnlyResponse(raw.status_code, body, raw.received_at)
