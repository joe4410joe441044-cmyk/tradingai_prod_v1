"""Frozen, secret-free registry-to-read-adapter binding contracts.

This module is a pure boundary: importing it or constructing its values never
reads a file, resolves a credential, opens a connection, or derives runtime
authority.  The binding is a snapshot of registry state, not a promise that the
snapshot is still current.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Optional

from backend.accounts.models import (
    AccountId,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
)
from backend.accounts.registry_models import (
    AccountRegistryRecord,
    AccountRegistrySnapshot,
    CredentialBundleReference,
    ExternalBindingStatus,
)
from backend.accounts.resolver import (
    AccountResolutionResult,
    AccountResolutionStatus,
    ResolvedAccountDescriptor,
)
from backend.execution.adapter_contracts import CapabilityState

READ_ONLY_NORMALIZATION_SCHEMA_VERSION = "tradingai-read-only-adapter-normalization/v1"

_FINGERPRINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ReadPurpose(str, Enum):
    CONNECTION_READINESS = "CONNECTION_READINESS"
    ACCOUNT_OBSERVATION = "ACCOUNT_OBSERVATION"
    POSITIONS_READ = "POSITIONS_READ"
    ORDERS_READ = "ORDERS_READ"


class EndpointProfile(str, Enum):
    BYBIT_DEMO_V5 = "BYBIT_DEMO_V5"
    BLOFIN_DEMO_V1 = "BLOFIN_DEMO_V1"
    INTERNAL_PAPER_V1 = "INTERNAL_PAPER_V1"


class ReadBindingCurrentness(str, Enum):
    CURRENT = "CURRENT"
    CURRENT_WITH_NEWER_REGISTRY_REVISION = "CURRENT_WITH_NEWER_REGISTRY_REVISION"
    REGISTRY_ROLLED_BACK = "REGISTRY_ROLLED_BACK"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCOUNT_RETIRED = "ACCOUNT_RETIRED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    CREDENTIAL_REFERENCE_CHANGED = "CREDENTIAL_REFERENCE_CHANGED"
    EXTERNAL_BINDING_CHANGED = "EXTERNAL_BINDING_CHANGED"
    RECORD_UPDATED = "RECORD_UPDATED"


_CURRENTNESS_MESSAGES = {
    ReadBindingCurrentness.CURRENT: "Read binding matches the current registry snapshot.",
    ReadBindingCurrentness.CURRENT_WITH_NEWER_REGISTRY_REVISION: (
        "Read binding account state is unchanged; the registry advanced for another account."
    ),
    ReadBindingCurrentness.REGISTRY_ROLLED_BACK: "Read binding registry revision is newer than the snapshot.",
    ReadBindingCurrentness.ACCOUNT_NOT_FOUND: "Read binding account is absent from the snapshot.",
    ReadBindingCurrentness.ACCOUNT_DISABLED: "Read binding account is disabled.",
    ReadBindingCurrentness.ACCOUNT_RETIRED: "Read binding account is retired.",
    ReadBindingCurrentness.SCOPE_MISMATCH: "Read binding account scope no longer matches.",
    ReadBindingCurrentness.CREDENTIAL_REFERENCE_CHANGED: "Read binding credential reference changed.",
    ReadBindingCurrentness.EXTERNAL_BINDING_CHANGED: "Read binding external binding changed.",
    ReadBindingCurrentness.RECORD_UPDATED: "Read binding account record was updated.",
}


def _exact_enum(enum_type, name: str, value: Any) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")


def _optional_enum(enum_type, name: str, value: Any) -> None:
    if value is not None:
        _exact_enum(enum_type, name, value)


def _positive(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _exact_bool(name: str, value: Any) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")


def _parse_enum(enum_type, name: str, value: Any):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text or {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _parse_optional_enum(enum_type, name: str, value: Any):
    if value is None:
        return None
    return _parse_enum(enum_type, name, value)


def _parse_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")
    return value


@dataclass(frozen=True)
class ReadCapabilities:
    account_read: CapabilityState = CapabilityState.UNKNOWN
    positions_read: CapabilityState = CapabilityState.UNKNOWN
    orders_read: CapabilityState = CapabilityState.UNKNOWN
    server_time: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            try:
                normalized = value if isinstance(value, CapabilityState) else CapabilityState(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown read capability state for {name}") from exc
            object.__setattr__(self, name, normalized)

    def require(self, name: str) -> None:
        if name not in self.__dataclass_fields__:
            raise ValueError(f"unknown read capability: {name}")
        state = getattr(self, name)
        if state is CapabilityState.UNSUPPORTED:
            raise RuntimeError("UNSUPPORTED_CAPABILITY")
        if state is CapabilityState.UNKNOWN:
            raise RuntimeError("CAPABILITY_UNKNOWN")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name).value for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadCapabilities":
        if not isinstance(data, Mapping):
            raise TypeError("read capabilities must be a mapping")
        expected = {item.name for item in fields(cls)}
        if set(data) != expected:
            raise ValueError("read capability fields do not match the schema")
        return cls(**{name: _parse_enum(CapabilityState, name, data[name]) for name in expected})


_ENDPOINT_CAPABILITY = {
    (ExecutionMode.EXTERNAL_SIMULATION, ExecutionVenue.BYBIT_DEMO): EndpointProfile.BYBIT_DEMO_V5,
    (ExecutionMode.EXTERNAL_SIMULATION, ExecutionVenue.BLOFIN_DEMO): EndpointProfile.BLOFIN_DEMO_V1,
    (ExecutionMode.PAPER, ExecutionVenue.INTERNAL_PAPER): EndpointProfile.INTERNAL_PAPER_V1,
}


@dataclass(frozen=True)
class ReadOnlyAdapterConfiguration:
    """Typed revisioned read binding. It does not grant execution authority."""

    account_id: AccountId
    account_type: AccountType
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    record_lifecycle: AccountLifecycleState
    registry_revision: int
    record_revision: int
    credential_reference: Optional[CredentialBundleReference] = field(repr=False)
    external_binding_status: Optional[ExternalBindingStatus]
    external_binding_verified: bool
    external_binding_fingerprint: Optional[str] = field(default=None, repr=False)
    endpoint_profile: EndpointProfile = EndpointProfile.BYBIT_DEMO_V5
    read_purpose: ReadPurpose = ReadPurpose.ACCOUNT_OBSERVATION
    capabilities: ReadCapabilities = field(default_factory=ReadCapabilities)
    normalization_schema_version: str = READ_ONLY_NORMALIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _exact_enum(AccountType, "account_type", self.account_type)
        _exact_enum(ExecutionMode, "execution_mode", self.execution_mode)
        _exact_enum(ExecutionVenue, "execution_venue", self.execution_venue)
        _exact_enum(AccountLifecycleState, "record_lifecycle", self.record_lifecycle)
        if self.record_lifecycle is not AccountLifecycleState.REGISTERED:
            raise ValueError("read binding requires a REGISTERED account")
        if (
            self.account_type is AccountType.PROP
            and self.execution_mode is ExecutionMode.LIVE
        ):
            raise ValueError("PROP read binding must not use real-capital LIVE")
        _positive("registry_revision", self.registry_revision)
        _positive("record_revision", self.record_revision)
        if self.credential_reference is not None and not isinstance(
            self.credential_reference, CredentialBundleReference
        ):
            raise TypeError("credential_reference has an invalid type")
        if self.execution_mode is ExecutionMode.PAPER:
            if self.credential_reference is not None:
                raise ValueError("PAPER read binding must not contain a credential reference")
        elif self.credential_reference is None:
            raise ValueError("external read binding requires a typed credential reference")
        _optional_enum(ExternalBindingStatus, "external_binding_status", self.external_binding_status)
        _exact_bool("external_binding_verified", self.external_binding_verified)
        if self.external_binding_verified is not (
            self.external_binding_status is ExternalBindingStatus.VERIFIED
        ):
            raise ValueError("external_binding_verified must match the binding status")
        if self.external_binding_fingerprint is not None and (
            not isinstance(self.external_binding_fingerprint, str)
            or not _FINGERPRINT.fullmatch(self.external_binding_fingerprint)
        ):
            raise ValueError("external_binding_fingerprint must be a safe opaque identifier")
        _exact_enum(EndpointProfile, "endpoint_profile", self.endpoint_profile)
        expected_profile = _ENDPOINT_CAPABILITY.get(
            (self.execution_mode, self.execution_venue)
        )
        if expected_profile is not self.endpoint_profile:
            raise ValueError("endpoint profile does not match execution mode and venue")
        _exact_enum(ReadPurpose, "read_purpose", self.read_purpose)
        if not isinstance(self.capabilities, ReadCapabilities):
            raise TypeError("capabilities must be ReadCapabilities")
        if self.normalization_schema_version != READ_ONLY_NORMALIZATION_SCHEMA_VERSION:
            raise ValueError("unsupported read-only normalization schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id.value,
            "account_type": self.account_type.value,
            "execution_mode": self.execution_mode.value,
            "execution_venue": self.execution_venue.value,
            "record_lifecycle": self.record_lifecycle.value,
            "registry_revision": self.registry_revision,
            "record_revision": self.record_revision,
            "credential_reference": (
                self.credential_reference.to_dict() if self.credential_reference else None
            ),
            "external_binding_status": (
                self.external_binding_status.value if self.external_binding_status else None
            ),
            "external_binding_verified": self.external_binding_verified,
            "external_binding_fingerprint": self.external_binding_fingerprint,
            "endpoint_profile": self.endpoint_profile.value,
            "read_purpose": self.read_purpose.value,
            "capabilities": self.capabilities.to_dict(),
            "normalization_schema_version": self.normalization_schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadOnlyAdapterConfiguration":
        if not isinstance(data, Mapping):
            raise TypeError("read-only adapter configuration must be a mapping")
        expected = {item.name for item in fields(cls)}
        if set(data) != expected:
            raise ValueError("read-only adapter configuration fields do not match the schema")
        credential = data["credential_reference"]
        if credential is not None:
            credential = CredentialBundleReference.from_dict(credential)
        capabilities = data["capabilities"]
        if not isinstance(capabilities, Mapping):
            raise TypeError("capabilities must be a mapping")
        capabilities = ReadCapabilities.from_dict(capabilities)
        return cls(
            account_id=AccountId(data["account_id"]),
            account_type=_parse_enum(AccountType, "account_type", data["account_type"]),
            execution_mode=_parse_enum(ExecutionMode, "execution_mode", data["execution_mode"]),
            execution_venue=_parse_enum(
                ExecutionVenue, "execution_venue", data["execution_venue"]
            ),
            record_lifecycle=_parse_enum(
                AccountLifecycleState, "record_lifecycle", data["record_lifecycle"]
            ),
            registry_revision=data["registry_revision"],
            record_revision=data["record_revision"],
            credential_reference=credential,
            external_binding_status=_parse_optional_enum(
                ExternalBindingStatus,
                "external_binding_status",
                data["external_binding_status"],
            ),
            external_binding_verified=_parse_bool(
                "external_binding_verified", data["external_binding_verified"]
            ),
            external_binding_fingerprint=data["external_binding_fingerprint"],
            endpoint_profile=_parse_enum(
                EndpointProfile, "endpoint_profile", data["endpoint_profile"]
            ),
            read_purpose=_parse_enum(ReadPurpose, "read_purpose", data["read_purpose"]),
            capabilities=capabilities,
            normalization_schema_version=data["normalization_schema_version"],
        )


def build_read_only_configuration(
    resolution: AccountResolutionResult,
    *,
    endpoint_profile: EndpointProfile,
    read_purpose: ReadPurpose,
    capabilities: ReadCapabilities,
    require_verified_external_binding: bool = False,
) -> ReadOnlyAdapterConfiguration:
    """Build a read binding from an already-resolved registry descriptor."""

    if not isinstance(resolution, AccountResolutionResult):
        raise TypeError("resolution must be AccountResolutionResult")
    if resolution.status is not AccountResolutionStatus.RESOLVED:
        raise ValueError("account resolution did not succeed")
    descriptor = resolution.descriptor
    if not isinstance(descriptor, ResolvedAccountDescriptor):
        raise ValueError("resolved account descriptor is missing")
    _exact_bool(
        "require_verified_external_binding", require_verified_external_binding
    )
    record = descriptor.record
    binding = descriptor.external_binding
    status = binding.status if binding is not None else None
    if require_verified_external_binding and status is not ExternalBindingStatus.VERIFIED:
        raise ValueError("verified external binding is required")
    return ReadOnlyAdapterConfiguration(
        account_id=record.identity.account_id,
        account_type=record.identity.account_type,
        execution_mode=record.identity.execution_mode,
        execution_venue=record.identity.execution_venue,
        record_lifecycle=record.identity.lifecycle_state,
        registry_revision=resolution.registry_revision,
        record_revision=record.record_revision,
        credential_reference=descriptor.credential_reference,
        external_binding_status=status,
        external_binding_verified=status is ExternalBindingStatus.VERIFIED,
        external_binding_fingerprint=(
            binding.verified_fingerprint if binding is not None else None
        ),
        endpoint_profile=endpoint_profile,
        read_purpose=read_purpose,
        capabilities=capabilities,
    )


@dataclass(frozen=True)
class ReadBindingEvaluation:
    currentness: ReadBindingCurrentness
    current_registry_revision: int
    current_record_revision: Optional[int] = None

    def __post_init__(self) -> None:
        _exact_enum(ReadBindingCurrentness, "currentness", self.currentness)
        if (
            isinstance(self.current_registry_revision, bool)
            or not isinstance(self.current_registry_revision, int)
            or self.current_registry_revision < 0
        ):
            raise ValueError("current_registry_revision must be a nonnegative integer")
        if self.current_record_revision is not None:
            _positive("current_record_revision", self.current_record_revision)

    @property
    def is_current(self) -> bool:
        return self.currentness in {
            ReadBindingCurrentness.CURRENT,
            ReadBindingCurrentness.CURRENT_WITH_NEWER_REGISTRY_REVISION,
        }

    @property
    def safe_message(self) -> str:
        return _CURRENTNESS_MESSAGES[self.currentness]


def evaluate_read_binding(
    binding: ReadOnlyAdapterConfiguration, snapshot: AccountRegistrySnapshot
) -> ReadBindingEvaluation:
    """Compare a binding snapshot with a later registry snapshot.

    A registry revision advance caused only by another account does not
    invalidate this binding; changes to the target record do.
    """

    if not isinstance(binding, ReadOnlyAdapterConfiguration):
        raise TypeError("binding must be ReadOnlyAdapterConfiguration")
    if not isinstance(snapshot, AccountRegistrySnapshot):
        raise TypeError("snapshot must be AccountRegistrySnapshot")
    current_revision = snapshot.registry_revision
    if current_revision < binding.registry_revision:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.REGISTRY_ROLLED_BACK, current_revision
        )
    record: Optional[AccountRegistryRecord] = snapshot.find(binding.account_id)
    if record is None:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.ACCOUNT_NOT_FOUND, current_revision
        )
    if (
        record.identity.account_type is not binding.account_type
        or record.identity.execution_mode is not binding.execution_mode
        or record.identity.execution_venue is not binding.execution_venue
    ):
        return ReadBindingEvaluation(
            ReadBindingCurrentness.SCOPE_MISMATCH,
            current_revision,
            record.record_revision,
        )
    if record.identity.lifecycle_state is AccountLifecycleState.DISABLED:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.ACCOUNT_DISABLED,
            current_revision,
            record.record_revision,
        )
    if record.identity.lifecycle_state is AccountLifecycleState.RETIRED:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.ACCOUNT_RETIRED,
            current_revision,
            record.record_revision,
        )
    if record.credential_reference != binding.credential_reference:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.CREDENTIAL_REFERENCE_CHANGED,
            current_revision,
            record.record_revision,
        )
    current_binding = record.external_binding
    current_status = current_binding.status if current_binding is not None else None
    current_fingerprint = (
        current_binding.verified_fingerprint if current_binding is not None else None
    )
    if (
        current_status is not binding.external_binding_status
        or current_fingerprint != binding.external_binding_fingerprint
    ):
        return ReadBindingEvaluation(
            ReadBindingCurrentness.EXTERNAL_BINDING_CHANGED,
            current_revision,
            record.record_revision,
        )
    if record.record_revision != binding.record_revision:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.RECORD_UPDATED,
            current_revision,
            record.record_revision,
        )
    if current_revision > binding.registry_revision:
        return ReadBindingEvaluation(
            ReadBindingCurrentness.CURRENT_WITH_NEWER_REGISTRY_REVISION,
            current_revision,
            record.record_revision,
        )
    return ReadBindingEvaluation(
        ReadBindingCurrentness.CURRENT, current_revision, record.record_revision
    )
