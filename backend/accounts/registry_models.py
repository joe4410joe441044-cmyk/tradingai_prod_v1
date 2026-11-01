"""Immutable, secret-free durable account-registry documents."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Optional

from .models import AccountId, AccountIdentity, ExecutionMode, ExecutionVenue


REGISTRY_SCHEMA_VERSION = "tradingai-account-registry/v2"
REGISTRY_RECORD_SCHEMA_VERSION = "tradingai-account-registry-record/v1"
REGISTRY_EVENT_SCHEMA_VERSION = "tradingai-account-registry-event/v2"
CREDENTIAL_REFERENCE_SCHEMA_VERSION = "tradingai-credential-bundle-reference/v1"
REGISTRY_ENVELOPE_SCHEMA_VERSION = "tradingai-account-registry-envelope/v2"

class UnsupportedRegistryVersion(RuntimeError):
    """Raised when a persisted registry document declares an unsupported version."""


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^evt_[0-9a-f]{32}$")


def _enum(kind, name: str, value: Any):
    try:
        return value if isinstance(value, kind) else kind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown {name}") from exc


def _positive(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be RFC3339 text")
    try:
        return _utc(name, datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{name} must be RFC3339 text") from exc


def _opaque(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque identifier")
    return value


def _operation_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _OPERATION_ID.fullmatch(value):
        raise ValueError(f"{name} must be a safe opaque operation identifier")
    return value


def _fingerprint(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _exact(data: Mapping[str, Any], model: type) -> None:
    if not isinstance(data, Mapping):
        raise TypeError("registry document must be a mapping")
    expected = {item.name for item in fields(model)}
    if set(data) != expected:
        raise ValueError("registry document fields do not match the schema")


class RegistrationSource(str, Enum):
    EXPLICIT_OPERATOR = "EXPLICIT_OPERATOR"
    LEGACY_MIGRATION = "LEGACY_MIGRATION"
    INJECTED_TEST = "INJECTED_TEST"


class CredentialReferenceSource(str, Enum):
    ENVIRONMENT_BUNDLE = "ENVIRONMENT_BUNDLE"
    SYSTEMD_CREDENTIAL_BUNDLE = "SYSTEMD_CREDENTIAL_BUNDLE"
    INJECTED_TEST = "INJECTED_TEST"


class ExternalBindingEnvironment(str, Enum):
    PAPER_LOCAL = "PAPER_LOCAL"
    DEMO = "DEMO"
    LIVE = "LIVE"


class ExternalBindingStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    REVOKED = "REVOKED"


class RegistryEventType(str, Enum):
    INITIALIZED = "INITIALIZED"
    REGISTERED = "REGISTERED"
    LABEL_UPDATED = "LABEL_UPDATED"
    CREDENTIAL_REFERENCE_UPDATED = "CREDENTIAL_REFERENCE_UPDATED"
    EXTERNAL_BINDING_UPDATED = "EXTERNAL_BINDING_UPDATED"
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class CredentialBundleReference:
    schema_version: str
    source: CredentialReferenceSource
    credential_id: str = field(repr=False)
    bundle_kind: str

    def __post_init__(self) -> None:
        if self.schema_version != CREDENTIAL_REFERENCE_SCHEMA_VERSION:
            raise UnsupportedRegistryVersion("unsupported credential reference schema")
        object.__setattr__(self, "source", _enum(CredentialReferenceSource, "credential source", self.source))
        object.__setattr__(self, "credential_id", _opaque("credential_id", self.credential_id))
        object.__setattr__(self, "bundle_kind", _opaque("bundle_kind", self.bundle_kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source.value,
            "credential_id": self.credential_id,
            "bundle_kind": self.bundle_kind,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CredentialBundleReference":
        _exact(data, cls)
        return cls(**data)


@dataclass(frozen=True)
class ExternalAccountBinding:
    venue: ExecutionVenue
    environment: ExternalBindingEnvironment
    status: ExternalBindingStatus
    binding_key: str = field(repr=False)
    verified_fingerprint: Optional[str] = field(default=None, repr=False)
    verified_at: Optional[datetime] = None
    verification_source: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _enum(ExecutionVenue, "binding venue", self.venue))
        object.__setattr__(self, "environment", _enum(ExternalBindingEnvironment, "binding environment", self.environment))
        status = _enum(ExternalBindingStatus, "binding status", self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "binding_key", _opaque("binding_key", self.binding_key))
        proof = (self.verified_fingerprint, self.verified_at, self.verification_source)
        if status is ExternalBindingStatus.VERIFIED:
            if any(item is None for item in proof):
                raise ValueError("VERIFIED binding requires complete verification evidence")
            object.__setattr__(self, "verified_fingerprint", _opaque("verified_fingerprint", self.verified_fingerprint))
            object.__setattr__(self, "verified_at", _utc("verified_at", self.verified_at))
            object.__setattr__(self, "verification_source", _opaque("verification_source", self.verification_source))
        elif any(item is not None for item in proof):
            raise ValueError("unverified binding must not contain verification evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue.value,
            "environment": self.environment.value,
            "status": self.status.value,
            "binding_key": self.binding_key,
            "verified_fingerprint": self.verified_fingerprint,
            "verified_at": _time_text(self.verified_at) if self.verified_at else None,
            "verification_source": self.verification_source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExternalAccountBinding":
        _exact(data, cls)
        values = dict(data)
        if values["verified_at"] is not None:
            values["verified_at"] = _parse_time("verified_at", values["verified_at"])
        return cls(**values)


_ENVIRONMENT_BY_MODE = {
    ExecutionMode.PAPER: ExternalBindingEnvironment.PAPER_LOCAL,
    ExecutionMode.EXTERNAL_SIMULATION: ExternalBindingEnvironment.DEMO,
    ExecutionMode.LIVE: ExternalBindingEnvironment.LIVE,
}


@dataclass(frozen=True)
class AccountRegistryRecord:
    schema_version: str
    identity: AccountIdentity
    display_label: str
    credential_reference: Optional[CredentialBundleReference] = field(repr=False)
    external_binding: Optional[ExternalAccountBinding] = field(repr=False)
    registration_source: RegistrationSource
    registration_request_id: str = field(repr=False)
    record_revision: int
    created_at: datetime
    updated_at: datetime
    predecessor_account_id: Optional[AccountId] = None

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_RECORD_SCHEMA_VERSION:
            raise UnsupportedRegistryVersion("unsupported registry record schema")
        if not isinstance(self.identity, AccountIdentity):
            raise TypeError("identity must be AccountIdentity")
        if not isinstance(self.display_label, str) or not self.display_label.strip() or len(self.display_label.strip()) > 100:
            raise ValueError("display_label must contain 1 to 100 characters")
        label = self.display_label.strip()
        if any(ord(char) < 32 for char in label):
            raise ValueError("display_label must not contain control characters")
        object.__setattr__(self, "display_label", label)
        if self.credential_reference is not None and not isinstance(self.credential_reference, CredentialBundleReference):
            raise TypeError("credential_reference has an invalid type")
        if self.external_binding is not None:
            if not isinstance(self.external_binding, ExternalAccountBinding):
                raise TypeError("external_binding has an invalid type")
            if self.external_binding.venue is not self.identity.execution_venue:
                raise ValueError("external binding venue does not match identity")
            if self.external_binding.environment is not _ENVIRONMENT_BY_MODE[self.identity.execution_mode]:
                raise ValueError("external binding environment does not match identity")
        object.__setattr__(self, "registration_source", _enum(RegistrationSource, "registration source", self.registration_source))
        object.__setattr__(self, "registration_request_id", _opaque("registration_request_id", self.registration_request_id))
        _positive("record_revision", self.record_revision)
        created = _utc("created_at", self.created_at)
        updated = _utc("updated_at", self.updated_at)
        if (
            updated < created
            or created != self.identity.created_at
            or updated < self.identity.updated_at
        ):
            raise ValueError("record timestamps are inconsistent with identity timestamps")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        if self.predecessor_account_id is not None:
            if not isinstance(self.predecessor_account_id, AccountId):
                raise TypeError("predecessor_account_id must be AccountId")
            if self.predecessor_account_id == self.identity.account_id:
                raise ValueError("account cannot be its own predecessor")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "display_label": self.display_label,
            "credential_reference": self.credential_reference.to_dict() if self.credential_reference else None,
            "external_binding": self.external_binding.to_dict() if self.external_binding else None,
            "registration_source": self.registration_source.value,
            "registration_request_id": self.registration_request_id,
            "record_revision": self.record_revision,
            "created_at": _time_text(self.created_at),
            "updated_at": _time_text(self.updated_at),
            "predecessor_account_id": self.predecessor_account_id.value if self.predecessor_account_id else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccountRegistryRecord":
        _exact(data, cls)
        values = dict(data)
        values["identity"] = AccountIdentity.from_dict(values["identity"])
        values["credential_reference"] = (
            CredentialBundleReference.from_dict(values["credential_reference"])
            if values["credential_reference"] is not None else None
        )
        values["external_binding"] = (
            ExternalAccountBinding.from_dict(values["external_binding"])
            if values["external_binding"] is not None else None
        )
        values["created_at"] = _parse_time("created_at", values["created_at"])
        values["updated_at"] = _parse_time("updated_at", values["updated_at"])
        values["predecessor_account_id"] = (
            AccountId(values["predecessor_account_id"]) if values["predecessor_account_id"] else None
        )
        return cls(**values)


_EVENT_CHANGED_FIELDS = {
    RegistryEventType.INITIALIZED: (),
    RegistryEventType.REGISTERED: (
        "identity",
        "display_label",
        "credential_reference",
        "external_binding",
    ),
    RegistryEventType.LABEL_UPDATED: ("display_label",),
    RegistryEventType.CREDENTIAL_REFERENCE_UPDATED: ("credential_reference",),
    RegistryEventType.EXTERNAL_BINDING_UPDATED: ("external_binding",),
    RegistryEventType.DISABLED: ("lifecycle_state",),
    RegistryEventType.ENABLED: ("lifecycle_state",),
    RegistryEventType.RETIRED: ("lifecycle_state",),
}

_LIFECYCLE_EVENTS = frozenset(
    {
        RegistryEventType.DISABLED,
        RegistryEventType.ENABLED,
        RegistryEventType.RETIRED,
    }
)


@dataclass(frozen=True)
class AccountRegistryEvent:
    schema_version: str
    event_id: str
    event_type: RegistryEventType
    operation_id: str
    request_fingerprint: str
    registry_revision: int
    account_id: Optional[AccountId]
    record_revision: Optional[int]
    identity_revision: Optional[int]
    changed_fields: tuple[str, ...]
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_EVENT_SCHEMA_VERSION:
            raise UnsupportedRegistryVersion("unsupported registry event schema")
        if not isinstance(self.event_id, str) or not _EVENT_ID.fullmatch(self.event_id):
            raise ValueError("event_id has an invalid format")
        object.__setattr__(self, "event_type", _enum(RegistryEventType, "event type", self.event_type))
        object.__setattr__(self, "operation_id", _operation_id("operation_id", self.operation_id))
        object.__setattr__(
            self, "request_fingerprint", _fingerprint("request_fingerprint", self.request_fingerprint)
        )
        _positive("registry_revision", self.registry_revision)
        if self.account_id is not None and not isinstance(self.account_id, AccountId):
            raise TypeError("event account_id must be AccountId")
        for name in ("record_revision", "identity_revision"):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        if not isinstance(self.changed_fields, tuple) or any(not _OPAQUE_ID.fullmatch(x) for x in self.changed_fields):
            raise ValueError("changed_fields must contain safe field names")
        object.__setattr__(self, "occurred_at", _utc("occurred_at", self.occurred_at))
        if self.changed_fields != _EVENT_CHANGED_FIELDS[self.event_type]:
            raise ValueError("event changed_fields do not match the event type")
        if self.event_type is RegistryEventType.INITIALIZED:
            if self.account_id is not None or self.registry_revision != 1:
                raise ValueError("INITIALIZED event must be registry-scoped revision 1")
            if self.record_revision is not None or self.identity_revision is not None:
                raise ValueError("INITIALIZED event must not reference a record")
        else:
            if self.account_id is None:
                raise ValueError("account event requires account_id")
            if self.record_revision is None or self.identity_revision is None:
                raise ValueError("account event requires record and identity revisions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "operation_id": self.operation_id,
            "request_fingerprint": self.request_fingerprint,
            "registry_revision": self.registry_revision,
            "account_id": self.account_id.value if self.account_id else None,
            "record_revision": self.record_revision,
            "identity_revision": self.identity_revision,
            "changed_fields": list(self.changed_fields),
            "occurred_at": _time_text(self.occurred_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccountRegistryEvent":
        _exact(data, cls)
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"]) if values["account_id"] else None
        if not isinstance(values["changed_fields"], list):
            raise TypeError("changed_fields must be a list")
        values["changed_fields"] = tuple(values["changed_fields"])
        values["occurred_at"] = _parse_time("occurred_at", values["occurred_at"])
        return cls(**values)


@dataclass(frozen=True)
class AccountRegistrySnapshot:
    schema_version: str
    registry_revision: int
    records: tuple[AccountRegistryRecord, ...]
    events: tuple[AccountRegistryEvent, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_SCHEMA_VERSION:
            raise UnsupportedRegistryVersion("unsupported registry schema")
        _positive("registry_revision", self.registry_revision)
        if not isinstance(self.records, tuple) or not all(isinstance(x, AccountRegistryRecord) for x in self.records):
            raise TypeError("records must be an immutable record tuple")
        if not isinstance(self.events, tuple) or not all(isinstance(x, AccountRegistryEvent) for x in self.events):
            raise TypeError("events must be an immutable event tuple")
        account_ids = [x.identity.account_id for x in self.records]
        request_ids = [x.registration_request_id for x in self.records]
        event_ids = [x.event_id for x in self.events]
        event_revisions = [x.registry_revision for x in self.events]
        operation_ids = [x.operation_id for x in self.events]
        if len(set(account_ids)) != len(account_ids) or len(set(request_ids)) != len(request_ids):
            raise ValueError("registry contains duplicate account or registration request IDs")
        if len(set(event_ids)) != len(event_ids) or len(set(event_revisions)) != len(event_revisions):
            raise ValueError("registry contains duplicate event IDs or revisions")
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("registry contains duplicate operation IDs")
        if not self.events or self.events[0].event_type is not RegistryEventType.INITIALIZED:
            raise ValueError("registry history must begin with INITIALIZED")
        if event_revisions != list(range(1, self.registry_revision + 1)):
            raise ValueError("registry event history must be contiguous and ordered through current revision")
        self._validate_event_history()
        fingerprints = [
            (x.external_binding.venue, x.external_binding.environment, x.external_binding.verified_fingerprint)
            for x in self.records
            if x.external_binding and x.external_binding.status is ExternalBindingStatus.VERIFIED
        ]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("verified external binding fingerprint must be unique")
        created = _utc("created_at", self.created_at)
        updated = _utc("updated_at", self.updated_at)
        if updated < created:
            raise ValueError("registry updated_at must not precede created_at")
        if self.events[0].occurred_at != created or self.events[-1].occurred_at != updated:
            raise ValueError("registry timestamps do not match the event history boundaries")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)

    def _validate_event_history(self) -> None:
        records = {x.identity.account_id: x for x in self.records}
        record_revisions: dict[AccountId, int] = {}
        identity_revisions: dict[AccountId, int] = {}
        last_occurred_at = self.events[0].occurred_at
        for event in self.events:
            if event.occurred_at < last_occurred_at:
                raise ValueError("registry event timestamps must be nondecreasing")
            last_occurred_at = event.occurred_at
            if event.event_type is RegistryEventType.INITIALIZED:
                if event is not self.events[0]:
                    raise ValueError("INITIALIZED may only appear once at revision 1")
                continue
            account_id = event.account_id
            if account_id not in records:
                raise ValueError("event references an account absent from the registry")
            if event.event_type is RegistryEventType.REGISTERED:
                if account_id in record_revisions:
                    raise ValueError("account has more than one registration event")
                if event.record_revision != 1 or event.identity_revision != 1:
                    raise ValueError("registration event must start at record and identity revision 1")
                record_revisions[account_id] = 1
                identity_revisions[account_id] = 1
                continue
            if account_id not in record_revisions:
                raise ValueError("account event precedes its registration event")
            expected_record = record_revisions[account_id] + 1
            if event.record_revision != expected_record:
                raise ValueError("record revisions are not contiguous for the account")
            if event.event_type in _LIFECYCLE_EVENTS:
                expected_identity = identity_revisions[account_id] + 1
                if event.identity_revision != expected_identity:
                    raise ValueError("identity revisions do not advance with lifecycle events")
                identity_revisions[account_id] = expected_identity
            elif event.identity_revision != identity_revisions[account_id]:
                raise ValueError("non-lifecycle events must not advance identity revision")
            record_revisions[account_id] = expected_record
        for account_id, record in records.items():
            if record_revisions.get(account_id) != record.record_revision:
                raise ValueError("record revision does not match its event history")
            if identity_revisions.get(account_id) != record.identity.revision:
                raise ValueError("identity revision does not match its event history")

    def find(self, account_id: AccountId) -> Optional[AccountRegistryRecord]:
        return next((record for record in self.records if record.identity.account_id == account_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_revision": self.registry_revision,
            "records": [item.to_dict() for item in self.records],
            "events": [item.to_dict() for item in self.events],
            "created_at": _time_text(self.created_at),
            "updated_at": _time_text(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccountRegistrySnapshot":
        _exact(data, cls)
        if not isinstance(data["records"], list) or not isinstance(data["events"], list):
            raise TypeError("registry records and events must be lists")
        return cls(
            schema_version=data["schema_version"],
            registry_revision=data["registry_revision"],
            records=tuple(AccountRegistryRecord.from_dict(x) for x in data["records"]),
            events=tuple(AccountRegistryEvent.from_dict(x) for x in data["events"]),
            created_at=_parse_time("created_at", data["created_at"]),
            updated_at=_parse_time("updated_at", data["updated_at"]),
        )
