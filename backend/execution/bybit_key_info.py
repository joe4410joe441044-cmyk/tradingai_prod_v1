"""Safe Bybit ``GET /v5/user/query-api`` projection and read-only readiness.

The parser never retains ``apiKey``, ``secret``, raw response text, or raw IP
addresses in its public repr/serialization.  Readiness is an offline evaluation
of a fabricated or real response shape; it does not authenticate an account and
never by itself proves an external account binding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any, Callable, Mapping, Optional, Tuple

from backend.accounts.models import AccountId
from backend.accounts.registry_models import CredentialBundleReference
from backend.execution.adapter_contracts import CapabilityState
from backend.execution.read_only_adapter_contracts import ReadOnlyAdapterConfiguration
from backend.execution.read_only_observations import ReadEndpoint
from backend.execution.read_only_transport import ReadOnlyClock


KEY_INFO_PATH = "/v5/user/query-api"
BYBIT_DEMO_KEY_INFO_SUPPORT = CapabilityState.SUPPORTED

_DOCUMENTED_PERMISSIONS: Mapping[str, frozenset[str]] = {
    "ContractTrade": frozenset({"Order", "Position"}),
    "Spot": frozenset({"SpotTrade"}),
    "Wallet": frozenset(
        {"AccountTransfer", "SubMemberTransfer", "SubMemberTransferList", "Withdraw"}
    ),
    "Options": frozenset({"OptionsTrade"}),
    "Derivatives": frozenset({"DerivativesTrade"}),
    "Exchange": frozenset({"ExchangeHistory"}),
    "Earn": frozenset({"Earn"}),
    "FiatP2P": frozenset({"FiatP2POrder", "Advertising"}),
    "FiatBitPay": frozenset({"FaitPayOrder"}),
    "FiatConvertBroker": frozenset({"FiatConvertBrokerOrder"}),
    "FiatGlobalPay": frozenset(),
    "BitCard": frozenset({"BitCard"}),
    "ByXPost": frozenset({"ByXPost"}),
    "Affiliate": frozenset({"Affiliate"}),
    "BlockTrade": frozenset({"BlockTrade"}),
    "NFT": frozenset(),
    "CopyTrading": frozenset(),
}

# Conservative offline policy; Bybit documents the permission categories but not
# a per-endpoint requirement.  This must be confirmed before a real connection.
_ENDPOINT_PERMISSION_REQUIREMENTS = {
    ReadEndpoint.ACCOUNT_SUMMARY: ("Wallet", None),
    ReadEndpoint.POSITIONS: ("ContractTrade", "Position"),
    ReadEndpoint.OPEN_ORDERS: ("ContractTrade", "Order"),
}

_EPOCH_PLACEHOLDER = datetime(1970, 1, 2, tzinfo=timezone.utc)


class KeyInfoParseError(ValueError):
    """Fixed-text parse failure; raw response text is discarded."""


class KeyInfoEnvelopeError(KeyInfoParseError):
    def __init__(self, ret_code: int) -> None:
        if isinstance(ret_code, bool) or not isinstance(ret_code, int):
            ret_code = -1
        self.ret_code = ret_code
        super().__init__("key-info request was rejected")


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _optional_int(value: object) -> Tuple[Optional[int], bool]:
    if value is None:
        return None, False
    if isinstance(value, bool) or not isinstance(value, int):
        return None, True
    return value, False


def _optional_bool(value: object) -> Tuple[Optional[bool], bool]:
    if value is None:
        return None, False
    if type(value) is not bool:
        return None, True
    return value, False


def _optional_text(value: object) -> Tuple[Optional[str], bool]:
    if value is None:
        return None, False
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None, True
    text = value.strip()
    return (text or None), False


def _optional_time(value: object) -> Tuple[Optional[datetime], bool]:
    if value is None or value == "":
        return None, False
    if not isinstance(value, str):
        return None, True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, True
    if parsed.tzinfo is None:
        return None, True
    return parsed.astimezone(timezone.utc), False


_SAFE_GENERATION = re.compile(r"[\x21-\x7e]{1,128}")


def _positive_revision(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class ReadinessBinding:
    """Snapshot of the account/credential revisions a readiness result belongs to.

    ``registry_revision`` and ``record_revision`` are kept separately: an
    unrelated account may advance the registry revision while this record stays
    unchanged.  ``credential_generation`` is an opaque non-secret rotation id and
    lets a caller distinguish a rotated credential that reuses the same
    reference.
    """

    account_id: AccountId
    credential_reference: CredentialBundleReference = field(repr=False)
    registry_revision: int
    record_revision: int
    credential_generation: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        if not isinstance(self.credential_reference, CredentialBundleReference):
            raise TypeError("credential_reference must be CredentialBundleReference")
        _positive_revision("registry_revision", self.registry_revision)
        _positive_revision("record_revision", self.record_revision)
        if self.credential_generation is not None:
            if not isinstance(self.credential_generation, str) or (
                _SAFE_GENERATION.fullmatch(self.credential_generation) is None
            ):
                raise ValueError("credential_generation must be a safe opaque identifier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id.value,
            "credential_reference": self.credential_reference.to_dict(),
            "registry_revision": self.registry_revision,
            "record_revision": self.record_revision,
            "credential_generation": self.credential_generation,
        }


class ReadinessReuseStatus(str, Enum):
    REUSABLE = "REUSABLE"
    UNBOUND = "UNBOUND"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    STALE = "STALE"


_READINESS_REUSE_MESSAGES = {
    ReadinessReuseStatus.REUSABLE: "readiness is reusable",
    ReadinessReuseStatus.UNBOUND: "readiness is not bound to an account",
    ReadinessReuseStatus.BINDING_MISMATCH: "readiness binding does not match",
    ReadinessReuseStatus.STALE: "readiness observation is stale",
}


class ReadinessBindingError(ValueError):
    """Fixed-text readiness reuse failure; no account or credential values leak."""

    def __init__(self, status: ReadinessReuseStatus) -> None:
        try:
            normalized = (
                status
                if isinstance(status, ReadinessReuseStatus)
                else ReadinessReuseStatus(status)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown readiness reuse status") from exc
        self.status = normalized
        super().__init__(_READINESS_REUSE_MESSAGES[normalized])


def assess_readiness_reuse(
    readiness: "KeyInfoReadiness",
    expected_binding: ReadinessBinding,
    *,
    now: datetime,
    max_age: timedelta = timedelta(seconds=5),
    allow_registry_revision_advance: bool = False,
) -> ReadinessReuseStatus:
    """Pure reuse check; never resolves a credential or contacts a venue.

    ``allow_registry_revision_advance=True`` permits a higher registry revision
    when the target record revision, account, credential reference and credential
    generation are unchanged.  That models an unrelated account update.  The
    default is strict equality.  A lower registry revision is always rejected.
    """

    if not isinstance(readiness, KeyInfoReadiness):
        raise TypeError("readiness must be KeyInfoReadiness")
    if not isinstance(expected_binding, ReadinessBinding):
        raise TypeError("expected_binding must be ReadinessBinding")
    if type(allow_registry_revision_advance) is not bool:
        raise TypeError("allow_registry_revision_advance must be bool")
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise ValueError("max_age must be a positive timedelta")
    current = _utc("now", now)
    actual = readiness.binding
    if actual is None or readiness.observed_at is None:
        return ReadinessReuseStatus.UNBOUND
    if actual.account_id != expected_binding.account_id:
        return ReadinessReuseStatus.BINDING_MISMATCH
    if actual.credential_reference != expected_binding.credential_reference:
        return ReadinessReuseStatus.BINDING_MISMATCH
    if actual.credential_generation != expected_binding.credential_generation:
        return ReadinessReuseStatus.BINDING_MISMATCH
    if actual.record_revision != expected_binding.record_revision:
        return ReadinessReuseStatus.BINDING_MISMATCH
    if actual.registry_revision != expected_binding.registry_revision:
        if not allow_registry_revision_advance:
            return ReadinessReuseStatus.BINDING_MISMATCH
        if actual.registry_revision > expected_binding.registry_revision:
            return ReadinessReuseStatus.BINDING_MISMATCH
    age = current - readiness.observed_at
    if age > max_age or age < -max_age:
        return ReadinessReuseStatus.STALE
    if readiness.source_time is not None and readiness.source_time > current + max_age:
        return ReadinessReuseStatus.STALE
    return ReadinessReuseStatus.REUSABLE


def require_reusable_readiness(
    readiness: "KeyInfoReadiness",
    expected_binding: ReadinessBinding,
    *,
    now: datetime,
    max_age: timedelta = timedelta(seconds=5),
    allow_registry_revision_advance: bool = False,
) -> "KeyInfoReadiness":
    status = assess_readiness_reuse(
        readiness,
        expected_binding,
        now=now,
        max_age=max_age,
        allow_registry_revision_advance=allow_registry_revision_advance,
    )
    if status is not ReadinessReuseStatus.REUSABLE:
        raise ReadinessBindingError(status)
    return readiness


@dataclass(frozen=True)
class KeyInfoProjection:
    read_only: Optional[int]
    uta: Optional[int]
    user_id: Optional[int] = field(repr=False)
    parent_uid: Optional[str] = field(repr=False)
    is_master: Optional[bool]
    key_type: Optional[int]
    permissions: Tuple[Tuple[str, Tuple[str, ...]], ...]
    unknown_scopes: Tuple[str, ...]
    unknown_permission_tokens: Tuple[str, ...]
    ip_restricted: Optional[bool]
    ip_count: Optional[int]
    ips: Tuple[str, ...] = field(default=(), repr=False)
    expires_at: Optional[datetime] = None
    expiry_reported: bool = False
    deadline_days: Optional[int] = None
    created_at: Optional[datetime] = None
    missing_fields: Tuple[str, ...] = ()
    invalid_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.read_only is not None and self.read_only not in (0, 1):
            raise ValueError("read_only must be 0, 1 or None")
        for name in ("expires_at", "created_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _utc(name, value))
        if type(self.expiry_reported) is not bool:
            raise TypeError("expiry_reported must be bool")

    def to_dict(self, *, include_external_identifiers: bool = False) -> dict[str, Any]:
        """Serialise the projection; raw UIDs are omitted unless explicitly opted in.

        ``user_id`` / ``parent_uid`` remain available as internal matching fields
        for readiness, but they are not evidence by default.  They are not
        secrets, yet they are account identifiers and should not leak into logs.
        """

        if type(include_external_identifiers) is not bool:
            raise TypeError("include_external_identifiers must be bool")
        include = include_external_identifiers
        return {
            "read_only": self.read_only,
            "uta": self.uta,
            "user_id": self.user_id if include else None,
            "parent_uid": self.parent_uid if include else None,
            "external_identifiers_redacted": not include,
            "is_master": self.is_master,
            "key_type": self.key_type,
            "permissions": {
                scope: list(tokens) for scope, tokens in self.permissions
            },
            "unknown_scopes": list(self.unknown_scopes),
            "unknown_permission_tokens": list(self.unknown_permission_tokens),
            "ip_restricted": self.ip_restricted,
            "ip_count": self.ip_count,
            "expires_at": (
                self.expires_at.isoformat().replace("+00:00", "Z")
                if self.expires_at is not None
                else None
            ),
            "expiry_reported": self.expiry_reported,
            "deadline_days": self.deadline_days,
            "created_at": (
                self.created_at.isoformat().replace("+00:00", "Z")
                if self.created_at is not None
                else None
            ),
            "missing_fields": list(self.missing_fields),
            "invalid_fields": list(self.invalid_fields),
        }


def parse_key_info_response(body: Mapping[str, Any]) -> KeyInfoProjection:
    if not isinstance(body, Mapping):
        raise KeyInfoParseError("key-info response must be a mapping")
    ret_code = body.get("retCode")
    if isinstance(ret_code, bool) or not isinstance(ret_code, int):
        raise KeyInfoParseError("key-info response envelope is malformed")
    if not isinstance(body.get("retMsg"), str):
        raise KeyInfoParseError("key-info response envelope is malformed")
    if ret_code != 0:
        raise KeyInfoEnvelopeError(ret_code)
    result = body.get("result")
    if not isinstance(result, Mapping):
        raise KeyInfoParseError("key-info result is malformed")
    return project_key_info_result(result)


def project_key_info_result(result: Mapping[str, Any]) -> KeyInfoProjection:
    if not isinstance(result, Mapping):
        raise KeyInfoParseError("key-info result must be a mapping")

    missing: list[str] = []
    invalid: list[str] = []

    def field_value(name: str) -> object:
        if name not in result:
            missing.append(name)
            return None
        return result[name]

    read_only, bad = _optional_int(field_value("readOnly"))
    if bad:
        invalid.append("readOnly")
    if read_only is not None and read_only not in (0, 1):
        invalid.append("readOnly")
        read_only = None

    uta, bad = _optional_int(field_value("uta"))
    if bad:
        invalid.append("uta")

    user_id, bad = _optional_int(field_value("userID"))
    if bad:
        invalid.append("userID")

    parent_uid, bad = _optional_text(field_value("parentUid"))
    if bad:
        invalid.append("parentUid")

    is_master, bad = _optional_bool(field_value("isMaster"))
    if bad:
        invalid.append("isMaster")

    key_type, bad = _optional_int(field_value("type"))
    if bad:
        invalid.append("type")

    permissions: list[Tuple[str, Tuple[str, ...]]] = []
    unknown_scopes: list[str] = []
    unknown_tokens: list[str] = []
    raw_permissions = field_value("permissions")
    if raw_permissions is not None:
        if not isinstance(raw_permissions, Mapping):
            invalid.append("permissions")
        else:
            for scope in sorted(raw_permissions):
                if not isinstance(scope, str):
                    invalid.append("permissions")
                    continue
                tokens_raw = raw_permissions[scope]
                if not isinstance(tokens_raw, list) or any(
                    not isinstance(token, str) for token in tokens_raw
                ):
                    invalid.append("permissions")
                    continue
                tokens = tuple(sorted(tokens_raw))
                permissions.append((scope, tokens))
                known_tokens = _DOCUMENTED_PERMISSIONS.get(scope)
                if known_tokens is None:
                    unknown_scopes.append(scope)
                    continue
                for token in tokens:
                    if token not in known_tokens:
                        unknown_tokens.append(f"{scope}:{token}")

    ip_restricted: Optional[bool] = None
    ip_count: Optional[int] = None
    ips: Tuple[str, ...] = ()
    raw_ips = field_value("ips")
    if raw_ips is not None:
        if not isinstance(raw_ips, list) or any(
            not isinstance(item, str) or not item for item in raw_ips
        ):
            invalid.append("ips")
        else:
            ips = tuple(raw_ips)
            ip_count = len(ips)
            ip_restricted = ip_count > 0

    expires_raw = field_value("expiredAt")
    expires_at, bad = _optional_time(expires_raw)
    if bad:
        invalid.append("expiredAt")
        expires_at = None
    expiry_reported = expires_at is not None and expires_at > _EPOCH_PLACEHOLDER
    if not expiry_reported:
        expires_at = None

    deadline_days, bad = _optional_int(field_value("deadlineDay"))
    if bad:
        invalid.append("deadlineDay")

    created_raw = field_value("createdAt")
    created_at, bad = _optional_time(created_raw)
    if bad:
        invalid.append("createdAt")
        created_at = None

    # ``apiKey`` and ``secret`` are intentionally never read into the projection.

    return KeyInfoProjection(
        read_only=read_only,
        uta=uta,
        user_id=user_id,
        parent_uid=parent_uid,
        is_master=is_master,
        key_type=key_type,
        permissions=tuple(permissions),
        unknown_scopes=tuple(unknown_scopes),
        unknown_permission_tokens=tuple(unknown_tokens),
        ip_restricted=ip_restricted,
        ip_count=ip_count,
        ips=ips,
        expires_at=expires_at,
        expiry_reported=expiry_reported,
        deadline_days=deadline_days,
        created_at=created_at,
        missing_fields=tuple(dict.fromkeys(missing)),
        invalid_fields=tuple(dict.fromkeys(invalid)),
    )


class ReadinessStatus(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


class ExternalBindingCheck(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class KeyReadinessPolicy:
    required_endpoints: frozenset[ReadEndpoint] = frozenset(
        {ReadEndpoint.ACCOUNT_SUMMARY, ReadEndpoint.POSITIONS, ReadEndpoint.OPEN_ORDERS}
    )
    blocked_permission_tokens: frozenset[str] = frozenset({"Withdraw"})
    review_permission_tokens: frozenset[str] = frozenset(
        {"AccountTransfer", "SubMemberTransfer", "SubMemberTransferList"}
    )
    require_read_only: bool = True
    require_unified_account: bool = True
    require_expiry_information: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.required_endpoints, frozenset) or not (
            self.required_endpoints <= set(ReadEndpoint)
        ):
            raise ValueError("required_endpoints is invalid")
        if not isinstance(self.blocked_permission_tokens, frozenset):
            raise ValueError("blocked_permission_tokens must be a frozenset")
        if not isinstance(self.review_permission_tokens, frozenset):
            raise ValueError("review_permission_tokens must be a frozenset")
        for name in (
            "require_read_only",
            "require_unified_account",
            "require_expiry_information",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")


@dataclass(frozen=True)
class KeyInfoReadiness:
    key_level_status: ReadinessStatus
    read_only_status: ReadinessStatus
    unified_account_status: ReadinessStatus
    permission_status: ReadinessStatus
    expiry_status: ReadinessStatus
    demo_support_status: ReadinessStatus
    ip_status: ReadinessStatus
    external_binding_check: ExternalBindingCheck
    authenticated_read_ready: bool
    reasons: Tuple[str, ...] = ()
    demo_key_info_support: CapabilityState = BYBIT_DEMO_KEY_INFO_SUPPORT
    policy_basis: str = "CONSERVATIVE_OFFLINE_POLICY"
    external_binding_basis: str = "CALLER_SUPPLIED_EXPECTATION"
    binding: Optional[ReadinessBinding] = None
    observed_at: Optional[datetime] = None
    source_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        for name in (
            "key_level_status",
            "read_only_status",
            "unified_account_status",
            "permission_status",
            "expiry_status",
            "demo_support_status",
            "ip_status",
        ):
            if not isinstance(getattr(self, name), ReadinessStatus):
                raise TypeError(f"{name} must be ReadinessStatus")
        if not isinstance(self.external_binding_check, ExternalBindingCheck):
            raise TypeError("external_binding_check must be ExternalBindingCheck")
        if type(self.authenticated_read_ready) is not bool:
            raise TypeError("authenticated_read_ready must be bool")
        if not isinstance(self.demo_key_info_support, CapabilityState):
            raise TypeError("demo_key_info_support must be CapabilityState")
        if self.binding is not None and not isinstance(self.binding, ReadinessBinding):
            raise TypeError("binding must be ReadinessBinding or None")
        for name in ("observed_at", "source_time"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _utc(name, value))
        if self.binding is not None and self.observed_at is None:
            raise ValueError("a bound readiness requires observed_at")

    @property
    def key_level_pass(self) -> bool:
        return self.key_level_status is ReadinessStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_level_status": self.key_level_status.value,
            "read_only_status": self.read_only_status.value,
            "unified_account_status": self.unified_account_status.value,
            "permission_status": self.permission_status.value,
            "expiry_status": self.expiry_status.value,
            "demo_support_status": self.demo_support_status.value,
            "ip_status": self.ip_status.value,
            "external_binding_check": self.external_binding_check.value,
            "authenticated_read_ready": self.authenticated_read_ready,
            "reasons": list(self.reasons),
            "demo_key_info_support": self.demo_key_info_support.value,
            "policy_basis": self.policy_basis,
            "external_binding_basis": self.external_binding_basis,
            "binding": self.binding.to_dict() if self.binding is not None else None,
            "observed_at": (
                self.observed_at.isoformat().replace("+00:00", "Z")
                if self.observed_at is not None
                else None
            ),
            "source_time": (
                self.source_time.isoformat().replace("+00:00", "Z")
                if self.source_time is not None
                else None
            ),
        }

    @classmethod
    def without_projection(
        cls, *, demo_key_info_support: CapabilityState
    ) -> "KeyInfoReadiness":
        if demo_key_info_support is CapabilityState.UNSUPPORTED:
            demo_status = ReadinessStatus.BLOCK
            reason = "DEMO_KEY_INFO_UNSUPPORTED"
        else:
            demo_status = ReadinessStatus.UNKNOWN
            reason = "DEMO_KEY_INFO_UNKNOWN"
        return cls(
            key_level_status=ReadinessStatus.UNKNOWN,
            read_only_status=ReadinessStatus.UNKNOWN,
            unified_account_status=ReadinessStatus.UNKNOWN,
            permission_status=ReadinessStatus.UNKNOWN,
            expiry_status=ReadinessStatus.UNKNOWN,
            demo_support_status=demo_status,
            ip_status=ReadinessStatus.UNKNOWN,
            external_binding_check=ExternalBindingCheck.NOT_CHECKED,
            authenticated_read_ready=False,
            reasons=(reason,),
            demo_key_info_support=demo_key_info_support,
        )


_WORST = {
    ReadinessStatus.PASS: 0,
    ReadinessStatus.UNKNOWN: 1,
    ReadinessStatus.BLOCK: 2,
}


def _worst(*statuses: ReadinessStatus) -> ReadinessStatus:
    return max(statuses, key=lambda status: _WORST[status])


def _permission_status(
    projection: KeyInfoProjection, policy: KeyReadinessPolicy, reasons: list[str]
) -> ReadinessStatus:
    if "permissions" in projection.missing_fields or "permissions" in projection.invalid_fields:
        reasons.append("PERMISSION_INFORMATION_MISSING")
        return ReadinessStatus.UNKNOWN
    if projection.unknown_scopes or projection.unknown_permission_tokens:
        reasons.append("PERMISSION_UNKNOWN")
        return ReadinessStatus.UNKNOWN
    tokens = {token for _, scope_tokens in projection.permissions for token in scope_tokens}
    if tokens & set(policy.blocked_permission_tokens):
        reasons.append("PERMISSION_BLOCKED")
        return ReadinessStatus.BLOCK
    by_scope = {scope: set(scope_tokens) for scope, scope_tokens in projection.permissions}
    missing_requirement = False
    for endpoint in sorted(policy.required_endpoints, key=lambda item: item.value):
        scope, token = _ENDPOINT_PERMISSION_REQUIREMENTS[endpoint]
        scope_tokens = by_scope.get(scope)
        if not scope_tokens:
            missing_requirement = True
            continue
        if token is not None and token not in scope_tokens:
            missing_requirement = True
    if missing_requirement:
        reasons.append("PERMISSION_REQUIRED_MISSING")
        return ReadinessStatus.BLOCK
    if tokens & set(policy.review_permission_tokens):
        reasons.append("TRANSFER_SCOPED_PERMISSION_PRESENT")
    return ReadinessStatus.PASS


def evaluate_key_info_readiness(
    projection: KeyInfoProjection,
    *,
    clock: ReadOnlyClock,
    demo_key_info_support: CapabilityState = BYBIT_DEMO_KEY_INFO_SUPPORT,
    policy: Optional[KeyReadinessPolicy] = None,
    expected_user_id: Optional[int] = None,
    expected_parent_uid: Optional[str] = None,
    expected_egress_ip: Optional[str] = None,
    binding: Optional[ReadinessBinding] = None,
    source_time: Optional[datetime] = None,
) -> KeyInfoReadiness:
    if not isinstance(projection, KeyInfoProjection):
        raise TypeError("projection must be KeyInfoProjection")
    if clock is None or not callable(getattr(clock, "now", None)):
        raise TypeError("an explicit clock is required")
    if not isinstance(demo_key_info_support, CapabilityState):
        raise TypeError("demo_key_info_support must be CapabilityState")
    if binding is not None and not isinstance(binding, ReadinessBinding):
        raise TypeError("binding must be ReadinessBinding or None")
    effective_policy = policy if policy is not None else KeyReadinessPolicy()
    if not isinstance(effective_policy, KeyReadinessPolicy):
        raise TypeError("policy must be KeyReadinessPolicy")
    now = _utc("clock.now()", clock.now())
    if source_time is not None:
        source_time = _utc("source_time", source_time)
    reasons: list[str] = []

    if projection.read_only is None:
        read_only_status = ReadinessStatus.UNKNOWN
        reasons.append("READ_ONLY_INFORMATION_MISSING")
    elif projection.read_only == 1:
        read_only_status = ReadinessStatus.PASS
    else:
        read_only_status = ReadinessStatus.BLOCK
        reasons.append("READ_ONLY_NOT_ENABLED")
    if read_only_status is ReadinessStatus.UNKNOWN and not effective_policy.require_read_only:
        read_only_status = ReadinessStatus.PASS

    if projection.uta is None:
        unified_status = ReadinessStatus.UNKNOWN
        reasons.append("UTA_INFORMATION_MISSING")
    elif projection.uta == 1:
        unified_status = ReadinessStatus.PASS
    else:
        unified_status = ReadinessStatus.BLOCK
        reasons.append("UTA_NOT_UNIFIED")
    if unified_status is ReadinessStatus.UNKNOWN and not effective_policy.require_unified_account:
        unified_status = ReadinessStatus.PASS

    permission_status = _permission_status(projection, effective_policy, reasons)

    if "expiredAt" in projection.invalid_fields:
        expiry_status = ReadinessStatus.UNKNOWN
        reasons.append("EXPIRY_INFORMATION_INVALID")
    elif projection.expiry_reported and projection.expires_at is not None:
        if projection.expires_at <= now:
            expiry_status = ReadinessStatus.BLOCK
            reasons.append("KEY_EXPIRED")
        else:
            expiry_status = ReadinessStatus.PASS
    else:
        expiry_status = ReadinessStatus.UNKNOWN
        reasons.append("EXPIRY_INFORMATION_MISSING")
        if not effective_policy.require_expiry_information:
            expiry_status = ReadinessStatus.PASS

    if demo_key_info_support is CapabilityState.SUPPORTED:
        demo_status = ReadinessStatus.PASS
    elif demo_key_info_support is CapabilityState.UNSUPPORTED:
        demo_status = ReadinessStatus.BLOCK
        reasons.append("DEMO_KEY_INFO_UNSUPPORTED")
    else:
        demo_status = ReadinessStatus.UNKNOWN
        reasons.append("DEMO_KEY_INFO_UNKNOWN")

    if projection.ip_restricted is None:
        ip_status = ReadinessStatus.UNKNOWN
        reasons.append("IP_INFORMATION_MISSING")
    elif projection.ip_restricted is False:
        ip_status = ReadinessStatus.PASS
    elif expected_egress_ip is None:
        ip_status = ReadinessStatus.UNKNOWN
        reasons.append("EGRESS_IP_NOT_PROVIDED")
    elif expected_egress_ip in projection.ips:
        ip_status = ReadinessStatus.PASS
    else:
        ip_status = ReadinessStatus.BLOCK
        reasons.append("EGRESS_IP_MISMATCH")

    if expected_user_id is None and expected_parent_uid is None:
        external_check = ExternalBindingCheck.NOT_CHECKED
        reasons.append("EXTERNAL_BINDING_NOT_CHECKED")
    elif projection.user_id is None:
        external_check = ExternalBindingCheck.UNKNOWN
        reasons.append("EXTERNAL_BINDING_INFORMATION_MISSING")
    else:
        matched = True
        if expected_user_id is not None and projection.user_id != expected_user_id:
            matched = False
        if expected_parent_uid is not None:
            normalized = (projection.parent_uid or "").strip()
            if normalized != str(expected_parent_uid).strip():
                matched = False
        if matched:
            external_check = ExternalBindingCheck.MATCHED
        else:
            external_check = ExternalBindingCheck.MISMATCH
            reasons.append("EXTERNAL_BINDING_MISMATCH")

    key_level_status = _worst(
        read_only_status, unified_status, permission_status, expiry_status, demo_status
    )
    authenticated_ready = (
        key_level_status is ReadinessStatus.PASS
        and ip_status is ReadinessStatus.PASS
        and external_check is ExternalBindingCheck.MATCHED
    )
    return KeyInfoReadiness(
        key_level_status=key_level_status,
        read_only_status=read_only_status,
        unified_account_status=unified_status,
        permission_status=permission_status,
        expiry_status=expiry_status,
        demo_support_status=demo_status,
        ip_status=ip_status,
        external_binding_check=external_check,
        authenticated_read_ready=authenticated_ready,
        reasons=tuple(dict.fromkeys(reasons)),
        demo_key_info_support=demo_key_info_support,
        binding=binding,
        observed_at=now,
        source_time=source_time,
    )


class GeneralReadAuthorizationError(ValueError):
    """Fixed-text failure for unavailable, stale, or mismatched read authority."""

    def __init__(self) -> None:
        super().__init__("general read authorization is unavailable")


class GeneralReadAuthorizationGate:
    """Fail-closed current binding/readiness gate for non-bootstrap reads.

    Both sources are invoked for every authorization check.  The binding source
    must return the latest resolved, REGISTERED configuration; a disabled account
    or a snapshot failure must therefore raise or return no configuration.  The
    readiness source must return the latest key-info result, bound to the exact
    credential generation resolved for the request.
    """

    def __init__(
        self,
        readiness_source: Callable[[], KeyInfoReadiness],
        current_binding_source: Callable[[], ReadOnlyAdapterConfiguration],
        *,
        max_age: timedelta = timedelta(seconds=5),
    ) -> None:
        if not callable(readiness_source):
            raise TypeError("readiness_source must be callable")
        if not callable(current_binding_source):
            raise TypeError("current_binding_source must be callable")
        if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
            raise ValueError("max_age must be a positive timedelta")
        self._readiness_source = readiness_source
        self._current_binding_source = current_binding_source
        self._max_age = max_age

    def __repr__(self) -> str:
        return "GeneralReadAuthorizationGate(<redacted sources>)"

    def authorize(
        self,
        *,
        binding: ReadOnlyAdapterConfiguration,
        credential_generation: str,
        now: datetime,
    ) -> KeyInfoReadiness:
        if not isinstance(binding, ReadOnlyAdapterConfiguration):
            raise TypeError("binding must be ReadOnlyAdapterConfiguration")
        current = _utc("now", now)
        try:
            latest_binding = self._current_binding_source()
            readiness = self._readiness_source()
        except Exception:
            raise GeneralReadAuthorizationError() from None
        if not isinstance(latest_binding, ReadOnlyAdapterConfiguration):
            raise GeneralReadAuthorizationError()
        if latest_binding != binding:
            raise GeneralReadAuthorizationError()
        if not isinstance(readiness, KeyInfoReadiness):
            raise GeneralReadAuthorizationError()
        if readiness.authenticated_read_ready is not True:
            raise GeneralReadAuthorizationError()
        try:
            expected = ReadinessBinding(
                account_id=latest_binding.account_id,
                credential_reference=latest_binding.credential_reference,
                registry_revision=latest_binding.registry_revision,
                record_revision=latest_binding.record_revision,
                credential_generation=credential_generation,
            )
            return require_reusable_readiness(
                readiness,
                expected,
                now=current,
                max_age=self._max_age,
            )
        except Exception:
            raise GeneralReadAuthorizationError() from None
