"""Typed contracts for a future durable account registry; no implementation or I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Optional, Protocol

from .models import (
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from .registry_models import (
    CredentialBundleReference,
    ExternalAccountBinding,
    ExternalBindingEnvironment,
    RegistrationSource,
    RegistryEventType,
)

_REGISTRATION_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUEST_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class RegistryFailureCode(str, Enum):
    NONE = "NONE"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    RECORD_REVISION_MISMATCH = "RECORD_REVISION_MISMATCH"
    DUPLICATE_ACCOUNT_ID = "DUPLICATE_ACCOUNT_ID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    UNSAFE_STORAGE = "UNSAFE_STORAGE"
    LOCK_FAILED = "LOCK_FAILED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


_SAFE_MESSAGES = {
    RegistryFailureCode.NONE: "",
    RegistryFailureCode.NOT_INITIALIZED: "Account registry is not initialized.",
    RegistryFailureCode.REVISION_MISMATCH: "Account registry revision does not match.",
    RegistryFailureCode.RECORD_REVISION_MISMATCH: "Account record revision does not match.",
    RegistryFailureCode.DUPLICATE_ACCOUNT_ID: "Issued account identifier already exists.",
    RegistryFailureCode.IDEMPOTENCY_CONFLICT: "Operation identifier conflicts with a different request.",
    RegistryFailureCode.INVALID_TRANSITION: "Requested account lifecycle transition is invalid.",
    RegistryFailureCode.INVALID_DOCUMENT: "Account registry document is invalid.",
    RegistryFailureCode.UNSAFE_STORAGE: "Account registry storage is unsafe.",
    RegistryFailureCode.LOCK_FAILED: "Account registry lock could not be acquired.",
    RegistryFailureCode.LOCK_TIMEOUT: "Account registry lock acquisition timed out.",
    RegistryFailureCode.SIZE_LIMIT_EXCEEDED: "Account registry document would exceed the maximum size.",
    RegistryFailureCode.PERSISTENCE_FAILED: "Account registry persistence failed before commit.",
    RegistryFailureCode.COMMIT_STATE_UNKNOWN: "Account registry commit state is unknown; reload before retrying.",
}


@dataclass(frozen=True)
class AccountRegistrationDraft:
    """Caller input without registry-owned IDs, revisions, lifecycle, or timestamps."""

    registration_request_id: str
    account_type: AccountType
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    prop_program: Optional[PropProgram] = None
    prop_phase: Optional[PropPhase] = None
    display_label: str = "Unnamed account"
    registration_source: RegistrationSource = RegistrationSource.EXPLICIT_OPERATOR
    credential_reference: Optional[CredentialBundleReference] = field(default=None, repr=False)
    external_binding: Optional[ExternalAccountBinding] = field(default=None, repr=False)
    predecessor_account_id: Optional[AccountId] = None

    def __post_init__(self) -> None:
        if not isinstance(self.registration_request_id, str) or not _REGISTRATION_REQUEST_ID.fullmatch(
            self.registration_request_id
        ):
            raise ValueError("registration_request_id must be a safe opaque identifier")
        try:
            account_type = AccountType(self.account_type)
            execution_mode = ExecutionMode(self.execution_mode)
            execution_venue = ExecutionVenue(self.execution_venue)
            prop_program = None if self.prop_program is None else PropProgram(self.prop_program)
            prop_phase = None if self.prop_phase is None else PropPhase(self.prop_phase)
        except (TypeError, ValueError) as exc:
            raise ValueError("registration draft contains an unknown scope value") from exc
        object.__setattr__(self, "registration_request_id", self.registration_request_id.strip())
        object.__setattr__(self, "account_type", account_type)
        object.__setattr__(self, "execution_mode", execution_mode)
        object.__setattr__(self, "execution_venue", execution_venue)
        object.__setattr__(self, "prop_program", prop_program)
        object.__setattr__(self, "prop_phase", prop_phase)
        allowed_venues = {
            ExecutionMode.PAPER: {ExecutionVenue.INTERNAL_PAPER},
            ExecutionMode.EXTERNAL_SIMULATION: {
                ExecutionVenue.BYBIT_DEMO,
                ExecutionVenue.BLOFIN_DEMO,
                ExecutionVenue.HYRO_MCP,
            },
            ExecutionMode.LIVE: {ExecutionVenue.KUCOIN_FUTURES},
        }
        if execution_venue not in allowed_venues[execution_mode]:
            raise ValueError("registration draft execution scope is incompatible")
        if account_type is AccountType.NORMAL:
            if prop_program is not None or prop_phase is not None:
                raise ValueError("NORMAL registration draft must not declare PROP fields")
        elif prop_program is None or prop_phase is None:
            raise ValueError("PROP registration draft requires program and phase")
        if account_type is AccountType.PROP and execution_mode is ExecutionMode.LIVE:
            raise ValueError("PROP registration draft must not use real-capital LIVE")
        if (
            not isinstance(self.display_label, str)
            or not self.display_label.strip()
            or len(self.display_label.strip()) > 100
            or any(ord(character) < 32 for character in self.display_label.strip())
        ):
            raise ValueError("display_label must contain 1 to 100 safe characters")
        object.__setattr__(self, "display_label", self.display_label.strip())
        try:
            object.__setattr__(self, "registration_source", RegistrationSource(self.registration_source))
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registration source") from exc
        if self.credential_reference is not None and not isinstance(
            self.credential_reference, CredentialBundleReference
        ):
            raise TypeError("credential_reference has an invalid type")
        if self.external_binding is not None:
            if not isinstance(self.external_binding, ExternalAccountBinding):
                raise TypeError("external_binding has an invalid type")
            if self.external_binding.venue is not execution_venue:
                raise ValueError("external binding venue does not match registration scope")
            expected_environment = {
                ExecutionMode.PAPER: ExternalBindingEnvironment.PAPER_LOCAL,
                ExecutionMode.EXTERNAL_SIMULATION: ExternalBindingEnvironment.DEMO,
                ExecutionMode.LIVE: ExternalBindingEnvironment.LIVE,
            }[execution_mode]
            if self.external_binding.environment is not expected_environment:
                raise ValueError("external binding environment does not match registration scope")
        if self.predecessor_account_id is not None and not isinstance(
            self.predecessor_account_id, AccountId
        ):
            raise TypeError("predecessor_account_id must be AccountId")


class RegistryLookupStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"


class RegistryRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    CONFLICT = "CONFLICT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    INVALID = "INVALID"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    FAILED = "FAILED"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


def _registry_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("registry_revision must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class AccountLookupResult:
    status: RegistryLookupStatus
    identity: Optional[AccountIdentity]
    registry_revision: int

    def __post_init__(self) -> None:
        try:
            status = RegistryLookupStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry lookup status") from exc
        object.__setattr__(self, "status", status)
        _registry_revision(self.registry_revision)
        if status is RegistryLookupStatus.FOUND:
            if not isinstance(self.identity, AccountIdentity):
                raise ValueError("FOUND lookup requires an identity")
        elif self.identity is not None:
            raise ValueError("non-FOUND lookup must not contain an identity")


@dataclass(frozen=True)
class AccountRegistrationResult:
    status: RegistryRegistrationStatus
    identity: Optional[AccountIdentity]
    registry_revision: int
    operation_id: Optional[str] = None
    request_fingerprint: Optional[str] = None
    original_registry_revision: Optional[int] = None
    failure_code: RegistryFailureCode = RegistryFailureCode.NONE

    def __post_init__(self) -> None:
        try:
            status = RegistryRegistrationStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry registration status") from exc
        object.__setattr__(self, "status", status)
        _registry_revision(self.registry_revision)
        try:
            failure_code = RegistryFailureCode(self.failure_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry failure code") from exc
        object.__setattr__(self, "failure_code", failure_code)
        if self.request_fingerprint is not None and not _REQUEST_FINGERPRINT.fullmatch(
            self.request_fingerprint
        ):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 hex digest")
        if self.original_registry_revision is not None:
            _registry_revision(self.original_registry_revision)
        succeeded = status in {
            RegistryRegistrationStatus.REGISTERED,
            RegistryRegistrationStatus.IDEMPOTENT_REPLAY,
        }
        if succeeded and not isinstance(self.identity, AccountIdentity):
            raise ValueError("successful registration requires an issued identity")
        if not succeeded and self.identity is not None:
            raise ValueError("failed registration must not contain an identity")

    @property
    def safe_message(self) -> str:
        return _SAFE_MESSAGES[self.failure_code]


class RegistryOperationLookupStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RegistryOperationReceipt:
    """Read-only receipt separating the original operation from the current snapshot."""

    status: RegistryOperationLookupStatus
    current_registry_revision: int = 0
    operation_id: Optional[str] = None
    request_fingerprint: Optional[str] = None
    event_type: Optional[RegistryEventType] = None
    account_id: Optional[AccountId] = None
    original_registry_revision: Optional[int] = None
    record_revision_at_event: Optional[int] = None
    identity_revision_at_event: Optional[int] = None
    occurred_at: Optional[datetime] = None
    current_record_revision: Optional[int] = None
    current_lifecycle_state: Optional[AccountLifecycleState] = None
    failure_code: RegistryFailureCode = RegistryFailureCode.NONE

    def __post_init__(self) -> None:
        try:
            status = RegistryOperationLookupStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown operation lookup status") from exc
        object.__setattr__(self, "status", status)
        _registry_revision(self.current_registry_revision)
        try:
            failure_code = RegistryFailureCode(self.failure_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry failure code") from exc
        object.__setattr__(self, "failure_code", failure_code)
        if self.request_fingerprint is not None and not _REQUEST_FINGERPRINT.fullmatch(
            self.request_fingerprint
        ):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 hex digest")
        if self.event_type is not None:
            try:
                object.__setattr__(self, "event_type", RegistryEventType(self.event_type))
            except (TypeError, ValueError) as exc:
                raise ValueError("unknown event type") from exc
        if self.account_id is not None and not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId or None")
        if self.current_lifecycle_state is not None:
            try:
                object.__setattr__(
                    self,
                    "current_lifecycle_state",
                    AccountLifecycleState(self.current_lifecycle_state),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("unknown lifecycle state") from exc
        for name in (
            "original_registry_revision",
            "record_revision_at_event",
            "identity_revision_at_event",
            "current_record_revision",
        ):
            value = getattr(self, name)
            if value is not None:
                _registry_revision(value)
        if self.occurred_at is not None:
            if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
                raise TypeError("occurred_at must be a timezone-aware datetime")
            object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))
        if status is RegistryOperationLookupStatus.FOUND:
            if (
                self.operation_id is None
                or self.request_fingerprint is None
                or self.event_type is None
                or self.original_registry_revision is None
            ):
                raise ValueError("FOUND operation receipt requires durable operation details")
        elif status is RegistryOperationLookupStatus.NOT_FOUND:
            if self.failure_code is not RegistryFailureCode.NONE:
                raise ValueError("NOT_FOUND operation receipt must not carry a failure")
        elif self.failure_code is RegistryFailureCode.NONE:
            raise ValueError("INVALID operation receipt requires a failure code")

    @property
    def safe_message(self) -> str:
        return _SAFE_MESSAGES[self.failure_code]


class AccountRegistry(Protocol):
    """CAS-aware boundary. The future implementation owns identity issuance."""

    def get(
        self, account_id: AccountId, *, expected_registry_revision: Optional[int] = None
    ) -> AccountLookupResult: ...

    def find_by_external_ref(
        self,
        execution_venue: ExecutionVenue,
        external_account_ref: str,
        *,
        expected_registry_revision: Optional[int] = None,
    ) -> AccountLookupResult: ...

    def register(
        self,
        draft: AccountRegistrationDraft,
        *,
        expected_registry_revision: int,
    ) -> AccountRegistrationResult: ...
