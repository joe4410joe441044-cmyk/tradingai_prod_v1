"""Explicit, secret-safe credential resolution for AI Advisor providers."""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Protocol

from pydantic import model_validator

from backend.ai_advisor.provider_config import (
    CredentialReference,
    CredentialSource,
    ProviderName,
)
from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class CredentialResolutionStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class CredentialFailureCode(str, Enum):
    CREDENTIAL_REFERENCE_INVALID = "CREDENTIAL_REFERENCE_INVALID"
    CREDENTIAL_SOURCE_NOT_ALLOWED = "CREDENTIAL_SOURCE_NOT_ALLOWED"
    CREDENTIAL_NOT_FOUND = "CREDENTIAL_NOT_FOUND"
    CREDENTIAL_EMPTY = "CREDENTIAL_EMPTY"
    CREDENTIAL_ACCESS_DENIED = "CREDENTIAL_ACCESS_DENIED"
    CREDENTIAL_INTERNAL_FAILURE = "CREDENTIAL_INTERNAL_FAILURE"


class CredentialResolutionInput(AdvisorProviderContractModel):
    credentialReference: CredentialReference
    provider: ProviderName
    allowEnvironmentRead: bool = False

    @model_validator(mode="after")
    def validate_provider(self) -> "CredentialResolutionInput":
        if self.provider is not ProviderName.OPENAI:
            raise ValueError("credential provider unsupported")
        return self


class EphemeralCredential:
    """Non-serializable internal credential handle with redacted display."""

    __slots__ = ("__value",)
    __hash__ = None

    def __init__(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("credential value unavailable")
        self.__value = value

    def __repr__(self) -> str:
        return "<EphemeralCredential redacted>"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return self is other

    @property
    def is_present(self) -> bool:
        return True

    def _consume(self) -> str:
        """Return the value only to the SDK client factory."""

        return self.__value

    def __reduce__(self):
        raise TypeError("credential serialization prohibited")


@dataclass(frozen=True)
class CredentialResolutionResult:
    status: CredentialResolutionStatus
    credential: EphemeralCredential | None = field(default=None, repr=False)
    failureCode: CredentialFailureCode | None = None
    safeMessage: str | None = None

    def __post_init__(self) -> None:
        succeeded = self.status is CredentialResolutionStatus.SUCCEEDED
        if succeeded != (self.credential is not None):
            raise ValueError("credential result invariant failed")
        if succeeded != (self.failureCode is None and self.safeMessage is None):
            raise ValueError("credential result invariant failed")
        if not succeeded and self.safeMessage != "advisor credential unavailable":
            raise ValueError("credential result invariant failed")


def _success(value: str) -> CredentialResolutionResult:
    return CredentialResolutionResult(
        status=CredentialResolutionStatus.SUCCEEDED,
        credential=EphemeralCredential(value),
    )


def _failure(code: CredentialFailureCode) -> CredentialResolutionResult:
    return CredentialResolutionResult(
        status=CredentialResolutionStatus.FAILED,
        failureCode=code,
        safeMessage="advisor credential unavailable",
    )


class CredentialLoader(Protocol):
    def resolve(
        self, resolution_input: CredentialResolutionInput
    ) -> CredentialResolutionResult:
        """Resolve one credential without exposing its value."""


@dataclass(frozen=True)
class EnvironmentCredentialLoader:
    allowedCredentialIds: tuple[str, ...]
    environmentReader: Callable[[str], str | None] = field(
        default=os.environ.get,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if (
            not self.allowedCredentialIds
            or len(set(self.allowedCredentialIds)) != len(self.allowedCredentialIds)
            or any(
                not value or not value.strip() for value in self.allowedCredentialIds
            )
        ):
            raise ValueError("credential allowlist invalid")

    def resolve(
        self, resolution_input: CredentialResolutionInput
    ) -> CredentialResolutionResult:
        try:
            trusted = CredentialResolutionInput.model_validate(
                resolution_input.model_dump(warnings=False)
            )
        except Exception:
            return _failure(CredentialFailureCode.CREDENTIAL_REFERENCE_INVALID)
        reference = trusted.credentialReference
        if reference.source is not CredentialSource.ENVIRONMENT:
            return _failure(CredentialFailureCode.CREDENTIAL_SOURCE_NOT_ALLOWED)
        if trusted.allowEnvironmentRead is not True:
            return _failure(CredentialFailureCode.CREDENTIAL_ACCESS_DENIED)
        if reference.credentialId not in self.allowedCredentialIds:
            return _failure(CredentialFailureCode.CREDENTIAL_ACCESS_DENIED)
        try:
            value = self.environmentReader(reference.credentialId)
        except Exception:
            return _failure(CredentialFailureCode.CREDENTIAL_INTERNAL_FAILURE)
        if value is None:
            return _failure(CredentialFailureCode.CREDENTIAL_NOT_FOUND)
        if not isinstance(value, str) or not value.strip():
            return _failure(CredentialFailureCode.CREDENTIAL_EMPTY)
        return _success(value)


@dataclass
class InjectedCredentialLoader:
    credentials: Mapping[str, str] = field(repr=False)
    fixedFailure: CredentialFailureCode | None = None
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.credentials = dict(self.credentials)

    def resolve(
        self, resolution_input: CredentialResolutionInput
    ) -> CredentialResolutionResult:
        self.calls += 1
        try:
            trusted = CredentialResolutionInput.model_validate(
                resolution_input.model_dump(warnings=False)
            )
        except Exception:
            return _failure(CredentialFailureCode.CREDENTIAL_REFERENCE_INVALID)
        if trusted.credentialReference.source is not CredentialSource.INJECTED:
            return _failure(CredentialFailureCode.CREDENTIAL_SOURCE_NOT_ALLOWED)
        if self.fixedFailure is not None:
            return _failure(self.fixedFailure)
        value = self.credentials.get(trusted.credentialReference.credentialId)
        if value is None:
            return _failure(CredentialFailureCode.CREDENTIAL_NOT_FOUND)
        if not isinstance(value, str) or not value.strip():
            return _failure(CredentialFailureCode.CREDENTIAL_EMPTY)
        return _success(value)
