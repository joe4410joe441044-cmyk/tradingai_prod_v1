"""Pure explicit account resolution over an immutable registry read result."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Mapping, Optional

from .models import (
    AccountId,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
)
from .registry_models import (
    AccountRegistryRecord,
    CredentialBundleReference,
    ExternalAccountBinding,
    ExternalBindingStatus,
)
from .registry_store import RegistryLoadResult, RegistryLoadStatus


class CredentialRequirement(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REFERENCE_REQUIRED = "REFERENCE_REQUIRED"


class AccountResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class AccountResolutionError(str, Enum):
    ACCOUNT_ID_REQUIRED = "ACCOUNT_ID_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    REGISTRY_INVALID = "REGISTRY_INVALID"
    VERSION_UNSUPPORTED = "VERSION_UNSUPPORTED"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    CREDENTIAL_REFERENCE_MISSING = "CREDENTIAL_REFERENCE_MISSING"
    EXTERNAL_BINDING_UNVERIFIED = "EXTERNAL_BINDING_UNVERIFIED"


_MESSAGES = {
    AccountResolutionError.ACCOUNT_ID_REQUIRED: "An explicit account identifier is required.",
    AccountResolutionError.NOT_FOUND: "The requested account was not found.",
    AccountResolutionError.DISABLED: "The requested account is disabled.",
    AccountResolutionError.RETIRED: "The requested account is retired.",
    AccountResolutionError.SCOPE_MISMATCH: "The requested account does not match the required scope.",
    AccountResolutionError.REGISTRY_INVALID: "The account registry is unavailable or invalid.",
    AccountResolutionError.VERSION_UNSUPPORTED: "The account registry version is unsupported.",
    AccountResolutionError.REVISION_MISMATCH: "The account registry revision does not match.",
    AccountResolutionError.CREDENTIAL_REFERENCE_MISSING: "The requested account has no credential reference.",
    AccountResolutionError.EXTERNAL_BINDING_UNVERIFIED: "The requested account has no verified external binding.",
}


def _exact_enum(enum_type, name: str, value: Any) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be {enum_type.__name__}")


def _optional_enum(enum_type, name: str, value: Any) -> None:
    if value is not None:
        _exact_enum(enum_type, name, value)


def _optional_revision(name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be None or a positive integer")


def _registry_revision(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class AccountResolutionRequest:
    account_id: Optional[AccountId]
    expected_registry_revision: Optional[int] = None
    required_account_type: Optional[AccountType] = None
    required_execution_mode: Optional[ExecutionMode] = None
    required_execution_venue: Optional[ExecutionVenue] = None
    credential_requirement: CredentialRequirement = CredentialRequirement.NOT_REQUIRED
    require_verified_external_binding: bool = False

    def __post_init__(self) -> None:
        if self.account_id is not None and not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId or None")
        _optional_revision("expected_registry_revision", self.expected_registry_revision)
        _optional_enum(AccountType, "required_account_type", self.required_account_type)
        _optional_enum(ExecutionMode, "required_execution_mode", self.required_execution_mode)
        _optional_enum(
            ExecutionVenue, "required_execution_venue", self.required_execution_venue
        )
        _exact_enum(
            CredentialRequirement, "credential_requirement", self.credential_requirement
        )
        if type(self.require_verified_external_binding) is not bool:
            raise TypeError("require_verified_external_binding must be bool")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccountResolutionRequest":
        """Explicitly parse an allowed external representation; never coerce unknown values."""

        if not isinstance(data, Mapping):
            raise TypeError("account resolution request must be a mapping")
        allowed = {item.name for item in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError("unknown account resolution request fields")
        if "account_id" not in data:
            raise ValueError("account_id is required")
        account_id = data["account_id"]
        if account_id is not None and not isinstance(account_id, AccountId):
            if not isinstance(account_id, str):
                raise TypeError("account_id must be text or AccountId")
            account_id = AccountId(account_id)
        revision = data.get("expected_registry_revision")
        if revision is not None:
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise TypeError("expected_registry_revision must be an integer or None")
            _optional_revision("expected_registry_revision", revision)
        return cls(
            account_id=account_id,
            expected_registry_revision=revision,
            required_account_type=_parse_optional_enum(
                AccountType, "required_account_type", data.get("required_account_type")
            ),
            required_execution_mode=_parse_optional_enum(
                ExecutionMode, "required_execution_mode", data.get("required_execution_mode")
            ),
            required_execution_venue=_parse_optional_enum(
                ExecutionVenue, "required_execution_venue", data.get("required_execution_venue")
            ),
            credential_requirement=_parse_enum(
                CredentialRequirement,
                "credential_requirement",
                data.get("credential_requirement", CredentialRequirement.NOT_REQUIRED),
            ),
            require_verified_external_binding=_parse_bool(
                "require_verified_external_binding",
                data.get("require_verified_external_binding", False),
            ),
        )


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
class ResolvedAccountDescriptor:
    record: AccountRegistryRecord
    credential_reference: Optional[CredentialBundleReference] = field(repr=False)
    external_binding: Optional[ExternalAccountBinding] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.record, AccountRegistryRecord):
            raise TypeError("record must be AccountRegistryRecord")
        if self.credential_reference is not None and not isinstance(
            self.credential_reference, CredentialBundleReference
        ):
            raise TypeError("credential_reference has an invalid type")
        if self.external_binding is not None and not isinstance(
            self.external_binding, ExternalAccountBinding
        ):
            raise TypeError("external_binding has an invalid type")
        if self.credential_reference != self.record.credential_reference:
            raise ValueError("credential reference does not belong to the resolved record")
        if self.external_binding != self.record.external_binding:
            raise ValueError("external binding does not belong to the resolved record")

    @property
    def identity(self):
        return self.record.identity


@dataclass(frozen=True)
class AccountResolutionResult:
    status: AccountResolutionStatus
    registry_revision: int
    descriptor: Optional[ResolvedAccountDescriptor] = None
    error: Optional[AccountResolutionError] = None

    def __post_init__(self) -> None:
        _exact_enum(AccountResolutionStatus, "status", self.status)
        _registry_revision("registry_revision", self.registry_revision)
        if self.descriptor is not None and not isinstance(
            self.descriptor, ResolvedAccountDescriptor
        ):
            raise TypeError("descriptor must be ResolvedAccountDescriptor or None")
        if self.error is not None:
            _exact_enum(AccountResolutionError, "error", self.error)
        if self.status is AccountResolutionStatus.RESOLVED:
            if self.descriptor is None or self.error is not None:
                raise ValueError("RESOLVED requires a descriptor and no error")
        elif self.descriptor is not None or self.error is None:
            raise ValueError("REJECTED requires an error and no descriptor")

    @property
    def safe_message(self) -> str:
        return _MESSAGES[self.error] if self.error else ""


def resolve_account(
    request: AccountResolutionRequest, read_result: RegistryLoadResult
) -> AccountResolutionResult:
    """Resolve exactly one account; never selects or falls back to another."""

    if not isinstance(request, AccountResolutionRequest):
        raise TypeError("request must be AccountResolutionRequest")
    if not isinstance(read_result, RegistryLoadResult):
        raise TypeError("read_result must be RegistryLoadResult")
    if request.account_id is None:
        return _rejected(0, AccountResolutionError.ACCOUNT_ID_REQUIRED)
    if read_result.status is RegistryLoadStatus.INCOMPATIBLE_VERSION:
        return _rejected(0, AccountResolutionError.VERSION_UNSUPPORTED)
    if read_result.status is not RegistryLoadStatus.VALID or read_result.snapshot is None:
        return _rejected(0, AccountResolutionError.REGISTRY_INVALID)
    snapshot = read_result.snapshot
    if (
        request.expected_registry_revision is not None
        and request.expected_registry_revision != snapshot.registry_revision
    ):
        return _rejected(snapshot.registry_revision, AccountResolutionError.REVISION_MISMATCH)
    record = snapshot.find(request.account_id)
    if record is None:
        return _rejected(snapshot.registry_revision, AccountResolutionError.NOT_FOUND)
    state = record.identity.lifecycle_state
    if state is AccountLifecycleState.DISABLED:
        return _rejected(snapshot.registry_revision, AccountResolutionError.DISABLED)
    if state is AccountLifecycleState.RETIRED:
        return _rejected(snapshot.registry_revision, AccountResolutionError.RETIRED)
    identity = record.identity
    if (
        (request.required_account_type is not None
         and identity.account_type is not request.required_account_type)
        or (request.required_execution_mode is not None
            and identity.execution_mode is not request.required_execution_mode)
        or (request.required_execution_venue is not None
            and identity.execution_venue is not request.required_execution_venue)
    ):
        return _rejected(snapshot.registry_revision, AccountResolutionError.SCOPE_MISMATCH)
    if (
        request.credential_requirement is CredentialRequirement.REFERENCE_REQUIRED
        and record.credential_reference is None
    ):
        return _rejected(
            snapshot.registry_revision, AccountResolutionError.CREDENTIAL_REFERENCE_MISSING
        )
    if request.require_verified_external_binding and (
        record.external_binding is None
        or record.external_binding.status is not ExternalBindingStatus.VERIFIED
    ):
        return _rejected(
            snapshot.registry_revision, AccountResolutionError.EXTERNAL_BINDING_UNVERIFIED
        )
    return AccountResolutionResult(
        AccountResolutionStatus.RESOLVED,
        snapshot.registry_revision,
        ResolvedAccountDescriptor(
            record, record.credential_reference, record.external_binding
        ),
    )


def _rejected(revision: int, error: AccountResolutionError) -> AccountResolutionResult:
    return AccountResolutionResult(
        AccountResolutionStatus.REJECTED, revision, error=error
    )
