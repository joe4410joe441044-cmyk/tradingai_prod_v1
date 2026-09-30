"""Server-side Supervisor capability authority.

This resolves the former ``AUTHORIZATION_AUTHORITY=UNRESOLVED`` gate using
option B: the existing trusted authentication layer supplies a stable,
HMAC-verified principal identity, and this module supplies a **server-configured
capability mapping**.  Authorization is never derived from the request body, an
untrusted header, the constant ``"operator"`` string by itself, source IP,
User-Agent, the CSRF token or authentication alone.

Fail-closed rules:

- no permissive default; the capability allowlist must be explicitly configured;
- missing configuration denies access;
- malformed configuration denies access;
- empty allowlist denies access;
- duplicate entries are deterministically deduplicated and sorted;
- configuration is bounded in entry count and entry length;
- secret-like entries are rejected;
- no secret value is ever returned or logged.

The capability vocabulary is shared with the Phase 3D-1 security model
(``SUPERVISOR_MONITORING_RUN_ONCE`` and its strictly stronger
``..._RUN_ONCE_PERSIST``).  This module never reads the process environment; the
environment mapping is injected by trusted server composition.
"""
from __future__ import annotations

import re
from typing import Mapping

from .monitoring_models import Contract, Token
from .monitoring_trigger_security import (
    TRIGGER_CAPABILITY,
    TRIGGER_PERSIST_CAPABILITY,
    AuthorizationDecision,
    AuthorizationInput,
    authorize,
)

AUTHORIZED_PRINCIPALS_ENV = "AI_SUPERVISOR_AUTHORIZED_PRINCIPALS"
AUTHORIZED_PERSIST_PRINCIPALS_ENV = "AI_SUPERVISOR_AUTHORIZED_PERSIST_PRINCIPALS"

MAX_PRINCIPALS = 64
MAX_PRINCIPAL_LENGTH = 128
MAX_CONFIG_LENGTH = 8192

Availability = str  # "AVAILABLE" | "NOT_CONFIGURED" | "INVALID"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*$")
_SECRET_MARKERS = (
    "API_KEY", "APIKEY", "PASSWORD", "PRIVATE_KEY", "SECRET", "BEARER", "TOKEN",
)


class AuthorizationConfig(Contract):
    """Bounded, secret-free authorization configuration snapshot."""

    authorized_principals: tuple[Token, ...] = ()
    persist_principals: tuple[Token, ...] = ()
    principals_present: bool = False
    persist_present: bool = False
    valid: bool = True
    reason_code: Token = "AUTHORIZATION_CONFIG_MISSING"


def _parse_principal_list(raw: object) -> tuple[tuple[str, ...], bool, bool, str]:
    """Return (principals, present, valid, reason).  Fail closed."""

    if raw is None:
        return (), False, True, "MISSING"
    if not isinstance(raw, str):
        return (), True, False, "CONFIG_INVALID"
    text = raw
    if len(text) > MAX_CONFIG_LENGTH:
        return (), True, False, "CONFIG_OVERSIZED"
    parts = [part.strip() for part in text.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return (), True, True, "EMPTY"
    if len(parts) > MAX_PRINCIPALS:
        return (), True, False, "CONFIG_OVERSIZED"
    cleaned: list[str] = []
    for part in parts:
        if len(part) > MAX_PRINCIPAL_LENGTH:
            return (), True, False, "CONFIG_INVALID"
        if any(ord(character) < 32 for character in part):
            return (), True, False, "CONFIG_INVALID"
        if not _TOKEN_RE.match(part):
            return (), True, False, "CONFIG_INVALID"
        upper = part.upper()
        if any(marker in upper for marker in _SECRET_MARKERS):
            return (), True, False, "CONFIG_UNSAFE"
        if part.startswith(("sk-", "eyJ")):
            return (), True, False, "CONFIG_UNSAFE"
        cleaned.append(part)
    return tuple(sorted(set(cleaned))), True, True, "OK"


def load_supervisor_authorization_config(
    environ: Mapping[str, str] | None = None,
) -> AuthorizationConfig:
    """Parse the server-configured principal/capability allowlists."""

    if environ is None:
        authorized_raw = None
        persist_raw = None
    else:
        try:
            authorized_raw = environ.get(AUTHORIZED_PRINCIPALS_ENV)
            persist_raw = environ.get(AUTHORIZED_PERSIST_PRINCIPALS_ENV)
        except Exception:  # noqa: BLE001 - unusable mapping behaves as unset
            authorized_raw = None
            persist_raw = None

    authorized, authorized_present, authorized_valid, authorized_reason = (
        _parse_principal_list(authorized_raw)
    )
    persist, persist_present, persist_valid, persist_reason = _parse_principal_list(persist_raw)

    if not authorized_valid:
        return AuthorizationConfig(
            principals_present=authorized_present, persist_present=persist_present,
            valid=False, reason_code=f"AUTHORIZATION_{authorized_reason}",
        )
    if not persist_valid:
        return AuthorizationConfig(
            authorized_principals=authorized, principals_present=authorized_present,
            persist_present=persist_present, valid=False,
            reason_code=f"AUTHORIZATION_PERSIST_{persist_reason}",
        )
    if not authorized:
        reason = "AUTHORIZATION_ALLOWLIST_EMPTY" if authorized_present \
            else "AUTHORIZATION_CONFIG_MISSING"
        return AuthorizationConfig(
            persist_principals=persist, principals_present=authorized_present,
            persist_present=persist_present, valid=True, reason_code=reason,
        )
    return AuthorizationConfig(
        authorized_principals=authorized, persist_principals=persist,
        principals_present=authorized_present, persist_present=persist_present,
        valid=True, reason_code="AUTHORIZATION_CONFIGURED",
    )


class SupervisorAuthorizationAuthority:
    """Deterministic, server-configured capability decision authority."""

    def __init__(self, config: AuthorizationConfig) -> None:
        if not isinstance(config, AuthorizationConfig):
            raise TypeError("config must be an AuthorizationConfig")
        self._config = config

    @property
    def config(self) -> AuthorizationConfig:
        return self._config

    @property
    def availability(self) -> str:
        if not self._config.valid:
            return "INVALID"
        if not self._config.authorized_principals:
            return "NOT_CONFIGURED"
        return "AVAILABLE"

    @property
    def configured(self) -> bool:
        return self.availability == "AVAILABLE"

    def capabilities_for(self, principal_id: str) -> tuple[str, ...]:
        """Bounded capability projection for an authenticated principal."""

        if not isinstance(principal_id, str) or not principal_id:
            return ()
        capabilities: list[str] = []
        if principal_id in self._config.authorized_principals:
            capabilities.append(TRIGGER_CAPABILITY)
        if principal_id in self._config.persist_principals:
            capabilities.append(TRIGGER_PERSIST_CAPABILITY)
        return tuple(capabilities)

    def build_input(self, principal_id: str) -> AuthorizationInput:
        source_available = self.configured
        return AuthorizationInput(
            authenticated=True,
            principal_id=principal_id if isinstance(principal_id, str) else None,
            capabilities=self.capabilities_for(principal_id),
            capability_source="VERIFIED_ADAPTER" if source_available else "UNAVAILABLE",
            source_available=source_available,
            source_freshness="FRESH" if source_available else "UNKNOWN",
            source_version=self._config.reason_code,
        )

    def decide(
        self, principal_id: str, *, capability: str = TRIGGER_CAPABILITY
    ) -> AuthorizationDecision:
        """Decide one capability.  Every uncertainty denies (fail closed)."""

        return authorize(self.build_input(principal_id), capability=capability)

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "SupervisorAuthorizationAuthority":
        return cls(load_supervisor_authorization_config(environ))


__all__ = [
    "AUTHORIZED_PERSIST_PRINCIPALS_ENV",
    "AUTHORIZED_PRINCIPALS_ENV",
    "AuthorizationConfig",
    "MAX_PRINCIPALS",
    "MAX_PRINCIPAL_LENGTH",
    "SupervisorAuthorizationAuthority",
    "load_supervisor_authorization_config",
]
