"""Explicit credential-provider boundary for read-only venue access.

This module defines contracts only.  It never reads an environment variable, a
secret file, a vault, or a registry.  It does not provide a default production
provider.  A caller must inject a provider explicitly, and a provider must
reject an unknown reference or a scope mismatch instead of falling back to
another credential.

Only the signing boundary may use :meth:`ReadOnlyCredential.signing_material`.
The credential object deliberately has no ``to_dict``/serialization surface and
its ``repr``/``str`` never contain the key or secret.  Python cannot guarantee
secure memory erasure; the guarantee is limited to "never rendered, never
serialized, and dropped as soon as the transport finishes signing".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, Tuple, runtime_checkable

from backend.accounts.models import AccountId, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import CredentialBundleReference
from backend.execution.read_only_adapter_contracts import EndpointProfile


class CredentialProviderErrorCode(str, Enum):
    REFERENCE_UNKNOWN = "REFERENCE_UNKNOWN"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"


_SAFE_PROVIDER_MESSAGES = {
    CredentialProviderErrorCode.REFERENCE_UNKNOWN: "credential reference is unknown",
    CredentialProviderErrorCode.SCOPE_MISMATCH: "credential scope does not match",
    CredentialProviderErrorCode.UNAVAILABLE: "credential is unavailable",
    CredentialProviderErrorCode.INVALID_CREDENTIAL: "credential material is invalid",
}


class CredentialProviderError(Exception):
    """Fixed-text provider failure; provider free-form text is not propagated."""

    def __init__(self, code: CredentialProviderErrorCode) -> None:
        try:
            normalized = (
                code
                if isinstance(code, CredentialProviderErrorCode)
                else CredentialProviderErrorCode(code)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown credential provider error code") from exc
        self.code = normalized
        super().__init__(_SAFE_PROVIDER_MESSAGES[normalized])

    @property
    def safe_message(self) -> str:
        return _SAFE_PROVIDER_MESSAGES[self.code]


def _safe_material(name: str, value: object, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError(f"{name} must be printable ASCII without spaces")
    return value


@dataclass(frozen=True)
class CredentialScope:
    """The exact account/venue/mode/profile a credential reference is bound to."""

    account_id: AccountId
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    endpoint_profile: EndpointProfile

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be ExecutionMode")
        if not isinstance(self.execution_venue, ExecutionVenue):
            raise TypeError("execution_venue must be ExecutionVenue")
        if not isinstance(self.endpoint_profile, EndpointProfile):
            raise TypeError("endpoint_profile must be EndpointProfile")
        if self.endpoint_profile is not EndpointProfile.BYBIT_DEMO_V5:
            raise ValueError("only the BYBIT_DEMO_V5 credential scope is supported")
        if self.execution_mode is not ExecutionMode.EXTERNAL_SIMULATION:
            raise ValueError("BYBIT_DEMO_V5 credentials require EXTERNAL_SIMULATION")
        if self.execution_venue is not ExecutionVenue.BYBIT_DEMO:
            raise ValueError("BYBIT_DEMO_V5 credentials require BYBIT_DEMO")


def _safe_generation(value: object) -> str:
    """Validate an opaque, non-secret credential generation identifier."""

    if not isinstance(value, str) or not value:
        raise ValueError("credential_generation must be non-empty text")
    if len(value) > 128:
        raise ValueError("credential_generation is too long")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError("credential_generation must be printable ASCII without spaces")
    return value


@dataclass(frozen=True)
class ReadOnlyCredential:
    """Opaque secret-bearing value used only at the signing boundary.

    A provider must echo the scope it resolved so the transport can reject a
    credential that matches the reference but belongs to a different account or
    endpoint profile.  ``credential_generation`` is an optional opaque,
    non-secret rotation identifier; it is never rendered or serialized.
    """

    reference: CredentialBundleReference = field(repr=False)
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    scope: Optional[CredentialScope] = field(default=None, repr=False)
    credential_generation: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.reference, CredentialBundleReference):
            raise TypeError("reference must be CredentialBundleReference")
        if self.scope is not None and not isinstance(self.scope, CredentialScope):
            raise TypeError("scope must be CredentialScope or None")
        object.__setattr__(self, "api_key", _safe_material("api_key", self.api_key))
        object.__setattr__(self, "api_secret", _safe_material("api_secret", self.api_secret))
        if self.credential_generation is not None:
            object.__setattr__(
                self,
                "credential_generation",
                _safe_generation(self.credential_generation),
            )

    def signing_material(self) -> Tuple[str, str]:
        """Return key/secret for the immediate signing call only."""

        return self.api_key, self.api_secret

    def __repr__(self) -> str:
        return "ReadOnlyCredential(<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()

    def __reduce__(self):
        raise TypeError("read-only credentials are not serializable")

    def __copy__(self):
        raise TypeError("read-only credentials are not copyable")

    def __deepcopy__(self, memo):
        raise TypeError("read-only credentials are not copyable")


@runtime_checkable
class ReadOnlyCredentialProvider(Protocol):
    """Provider contract; no implicit/default implementation exists.

    The returned credential must carry a ``scope`` equal to the requested scope
    (scope echo) and should carry an opaque ``credential_generation`` that
    changes on rotation.  The transport re-validates the echo and rejects a
    missing or mismatched scope.
    """

    def resolve(
        self, reference: CredentialBundleReference, scope: CredentialScope
    ) -> ReadOnlyCredential: ...
