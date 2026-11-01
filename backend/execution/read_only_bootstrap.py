"""Key-info bootstrap boundary.

The bootstrap can read exactly one endpoint (``/v5/user/query-api``) before any
account observation, so a bounded readiness check does not require a credential
that has already been proven by the observation endpoints.  It cannot read
wallet, position, or order data, and a successful bootstrap does not grant
execution authority or prove an external account binding.

The real connection still requires separate operator approval; this module is
verified only with a mock sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from backend.execution.bybit_key_info import (
    BYBIT_DEMO_KEY_INFO_SUPPORT,
    KEY_INFO_PATH,
    KeyInfoEnvelopeError,
    KeyInfoParseError,
    KeyInfoProjection,
    KeyInfoReadiness,
    KeyReadinessPolicy,
    ReadinessBinding,
    evaluate_key_info_readiness,
    parse_key_info_response,
)
from backend.execution.bybit_v5_signed_transport import BybitV5SignedReadTransport
from backend.execution.read_only_observations import ReadErrorCode, ReadFailure
from backend.execution.read_only_transport import (
    ReadOnlyRequest,
    ReadTransportError,
    ReadTransportFailureKind,
)
from backend.execution.adapter_contracts import CapabilityState


_TRANSPORT_FAILURE_MAP = {
    ReadTransportFailureKind.TIMEOUT: ReadErrorCode.TIMEOUT,
    ReadTransportFailureKind.INVALID_RESPONSE: ReadErrorCode.MALFORMED_RESPONSE,
    ReadTransportFailureKind.RESPONSE_TOO_LARGE: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.REDIRECT_REJECTED: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.POLICY_REJECTED: ReadErrorCode.INVALID_REQUEST,
    ReadTransportFailureKind.CREDENTIAL_REJECTED: ReadErrorCode.AUTHENTICATION_FAILED,
    ReadTransportFailureKind.READINESS_REJECTED: ReadErrorCode.STALE_BINDING,
    ReadTransportFailureKind.CLOCK_REJECTED: ReadErrorCode.CLOCK_SKEW,
    ReadTransportFailureKind.CONNECTION_FAILED: ReadErrorCode.TRANSPORT_FAILURE,
    ReadTransportFailureKind.STATE_UNKNOWN: ReadErrorCode.STATE_UNKNOWN,
}

_VENUE_FAILURE_MAP = {
    10002: ReadErrorCode.CLOCK_SKEW,
    10003: ReadErrorCode.AUTHENTICATION_FAILED,
    10004: ReadErrorCode.AUTHENTICATION_FAILED,
    10005: ReadErrorCode.PERMISSION_DENIED,
    10006: ReadErrorCode.RATE_LIMITED,
    10007: ReadErrorCode.AUTHENTICATION_FAILED,
    10010: ReadErrorCode.PERMISSION_DENIED,
}


def _http_failure(status_code: int) -> ReadFailure:
    if status_code == 401:
        return ReadFailure(ReadErrorCode.AUTHENTICATION_FAILED)
    if status_code == 403:
        return ReadFailure(ReadErrorCode.PERMISSION_DENIED)
    if status_code == 429:
        return ReadFailure(ReadErrorCode.RATE_LIMITED)
    if 500 <= status_code <= 599:
        return ReadFailure(ReadErrorCode.TRANSPORT_FAILURE)
    return ReadFailure(ReadErrorCode.VENUE_REJECTED)


@dataclass(frozen=True)
class KeyInfoReadResult:
    failure: Optional[ReadFailure]
    projection: Optional[KeyInfoProjection]
    readiness: Optional[KeyInfoReadiness]
    binding: Optional[ReadinessBinding] = None

    def __post_init__(self) -> None:
        if self.failure is not None and not isinstance(self.failure, ReadFailure):
            raise TypeError("failure must be ReadFailure or None")
        if self.projection is not None and not isinstance(self.projection, KeyInfoProjection):
            raise TypeError("projection must be KeyInfoProjection or None")
        if self.readiness is not None and not isinstance(self.readiness, KeyInfoReadiness):
            raise TypeError("readiness must be KeyInfoReadiness or None")
        if self.binding is not None and not isinstance(self.binding, ReadinessBinding):
            raise TypeError("binding must be ReadinessBinding or None")
        if self.failure is None and (self.projection is None or self.readiness is None):
            raise ValueError("a successful key-info read requires projection and readiness")
        if self.failure is not None and self.projection is not None:
            raise ValueError("a failed key-info read must not expose a projection")

    @property
    def succeeded(self) -> bool:
        return self.failure is None

    @property
    def authenticated_read_ready(self) -> bool:
        return bool(self.readiness is not None and self.readiness.authenticated_read_ready)


class BybitDemoKeyInfoBootstrap:
    """Read-only bootstrap restricted to the key-info endpoint."""

    allowed_paths = frozenset({KEY_INFO_PATH})

    def __init__(
        self,
        transport: BybitV5SignedReadTransport,
        *,
        demo_key_info_support: CapabilityState = BYBIT_DEMO_KEY_INFO_SUPPORT,
        policy: Optional[KeyReadinessPolicy] = None,
        expected_user_id: Optional[int] = None,
        expected_parent_uid: Optional[str] = None,
        expected_egress_ip: Optional[str] = None,
    ) -> None:
        if transport is None or not callable(getattr(transport, "send", None)):
            raise TypeError("an explicit signed read-only transport is required")
        if not isinstance(demo_key_info_support, CapabilityState):
            raise TypeError("demo_key_info_support must be CapabilityState")
        if policy is not None and not isinstance(policy, KeyReadinessPolicy):
            raise TypeError("policy must be KeyReadinessPolicy or None")
        if expected_user_id is not None and (
            isinstance(expected_user_id, bool) or not isinstance(expected_user_id, int)
        ):
            raise TypeError("expected_user_id must be an integer or None")
        for name, value in (
            ("expected_parent_uid", expected_parent_uid),
            ("expected_egress_ip", expected_egress_ip),
        ):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be text or None")
        self._transport = transport
        self._demo_support = demo_key_info_support
        self._policy = policy
        self._expected_user_id = expected_user_id
        self._expected_parent_uid = expected_parent_uid
        self._expected_egress_ip = expected_egress_ip

    @property
    def demo_key_info_support(self) -> CapabilityState:
        return self._demo_support

    @staticmethod
    def require_allowed_path(path: str) -> None:
        if path not in BybitDemoKeyInfoBootstrap.allowed_paths:
            raise ValueError("bootstrap may only read the key-info endpoint")

    def _readiness_binding(self) -> ReadinessBinding:
        binding = self._transport.binding
        reference = binding.credential_reference
        if reference is None:
            raise ValueError("key-info readiness requires a credential reference")
        return ReadinessBinding(
            account_id=binding.account_id,
            credential_reference=reference,
            registry_revision=binding.registry_revision,
            record_revision=binding.record_revision,
            credential_generation=self._transport.last_credential_generation,
        )

    @staticmethod
    def _source_time(body: Mapping[str, Any]) -> Optional[datetime]:
        value = body.get("time")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        try:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    def read_key_info(self) -> KeyInfoReadResult:
        if self._demo_support is not CapabilityState.SUPPORTED:
            failure = ReadFailure(
                ReadErrorCode.CAPABILITY_UNKNOWN
                if self._demo_support is CapabilityState.UNKNOWN
                else ReadErrorCode.UNSUPPORTED_CAPABILITY
            )
            readiness = KeyInfoReadiness.without_projection(
                demo_key_info_support=self._demo_support
            )
            return KeyInfoReadResult(failure=failure, projection=None, readiness=readiness)

        self.require_allowed_path(KEY_INFO_PATH)
        request = ReadOnlyRequest(method="GET", path=KEY_INFO_PATH, query=())
        try:
            response = self._transport.send(request)
        except ReadTransportError as exc:
            code = _TRANSPORT_FAILURE_MAP.get(exc.kind, ReadErrorCode.STATE_UNKNOWN)
            return KeyInfoReadResult(failure=ReadFailure(code), projection=None, readiness=None)
        except Exception:
            return KeyInfoReadResult(
                failure=ReadFailure(ReadErrorCode.STATE_UNKNOWN),
                projection=None,
                readiness=None,
            )
        if response.status_code != 200:
            return KeyInfoReadResult(
                failure=_http_failure(response.status_code), projection=None, readiness=None
            )
        try:
            projection = parse_key_info_response(response.body)
        except KeyInfoEnvelopeError as exc:
            code = _VENUE_FAILURE_MAP.get(exc.ret_code, ReadErrorCode.VENUE_REJECTED)
            return KeyInfoReadResult(
                failure=ReadFailure(code, venue_ret_code=exc.ret_code),
                projection=None,
                readiness=None,
            )
        except KeyInfoParseError:
            return KeyInfoReadResult(
                failure=ReadFailure(ReadErrorCode.MALFORMED_RESPONSE),
                projection=None,
                readiness=None,
            )
        binding = self._readiness_binding()
        readiness = evaluate_key_info_readiness(
            projection,
            clock=self._transport.clock,
            demo_key_info_support=self._demo_support,
            policy=self._policy,
            expected_user_id=self._expected_user_id,
            expected_parent_uid=self._expected_parent_uid,
            expected_egress_ip=self._expected_egress_ip,
            binding=binding,
            source_time=self._source_time(response.body),
        )
        return KeyInfoReadResult(
            failure=None,
            projection=projection,
            readiness=readiness,
            binding=binding,
        )
