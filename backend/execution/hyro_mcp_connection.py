"""Fail-closed connection boundary for the offline Hyro MCP read adapter.

Official Hyro endpoint, transport, authentication and tool contracts are not
encoded here. Callers must supply an explicit profile after verifying them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Callable, Mapping, cast
from urllib.parse import urlsplit

from backend.execution.hyro_mcp_read_adapter import (
    HyroMcpAccountScope,
    HyroMcpObservation,
    HyroMcpReadAdapter,
    HyroMcpReadTransport,
    HyroMcpToolProfile,
)

_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_REQUIRED_FIELDS = (
    "server_url",
    "transport",
    "auth_scheme",
    "credential_reference",
    "account_scope",
    "tools",
    "response_schema_id",
    "read_access_enabled",
    "trading_access_enabled",
)


class HyroMcpConnectionStatus(str, Enum):
    READY = "READY"
    BLOCKED_MISSING = "BLOCKED_MISSING"
    BLOCKED_UNSAFE = "BLOCKED_UNSAFE"
    TRANSPORT_FAILED = "TRANSPORT_FAILED"


@dataclass(frozen=True)
class HyroMcpConnectionValidation:
    status: HyroMcpConnectionStatus
    missing_fields: tuple[str, ...] = ()
    unsafe_fields: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status is HyroMcpConnectionStatus.READY


@dataclass(frozen=True)
class HyroMcpConnectionConfig:
    server_url: str | None = None
    transport: str | None = None
    auth_scheme: str | None = None
    credential_reference: str | None = field(default=None, repr=False)
    account_scope: HyroMcpAccountScope | None = None
    tools: HyroMcpToolProfile | None = None
    response_schema_id: str | None = None
    read_access_enabled: bool | None = None
    trading_access_enabled: bool | None = None

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        account_scope: HyroMcpAccountScope | None = None,
        tools: HyroMcpToolProfile | None = None,
    ) -> "HyroMcpConnectionConfig":
        """Load non-secret connection settings; credentials remain an opaque reference."""
        return cls(
            server_url=_optional_text(values.get("server_url")),
            transport=_optional_text(values.get("transport")),
            auth_scheme=_optional_text(values.get("auth_scheme")),
            credential_reference=_optional_text(values.get("credential_reference")),
            account_scope=account_scope,
            tools=tools,
            response_schema_id=_optional_text(values.get("response_schema_id")),
            read_access_enabled=_optional_bool(values.get("read_access_enabled")),
            trading_access_enabled=_optional_bool(values.get("trading_access_enabled")),
        )

    def validate(self) -> HyroMcpConnectionValidation:
        missing = tuple(name for name in _REQUIRED_FIELDS if _missing(getattr(self, name)))
        if missing:
            return HyroMcpConnectionValidation(
                HyroMcpConnectionStatus.BLOCKED_MISSING,
                missing_fields=missing,
            )

        unsafe: list[str] = []
        parsed = urlsplit(self.server_url or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            unsafe.append("server_url")
        for name in ("transport", "auth_scheme", "credential_reference", "response_schema_id"):
            if not _SAFE_ID.fullmatch(getattr(self, name) or ""):
                unsafe.append(name)
        if not isinstance(self.account_scope, HyroMcpAccountScope):
            unsafe.append("account_scope")
        if not isinstance(self.tools, HyroMcpToolProfile):
            unsafe.append("tools")
        if self.read_access_enabled is not True:
            unsafe.append("read_access_enabled")
        if self.trading_access_enabled is not False:
            unsafe.append("trading_access_enabled")
        if unsafe:
            return HyroMcpConnectionValidation(
                HyroMcpConnectionStatus.BLOCKED_UNSAFE,
                unsafe_fields=tuple(dict.fromkeys(unsafe)),
            )
        return HyroMcpConnectionValidation(HyroMcpConnectionStatus.READY)


@dataclass(frozen=True)
class HyroMcpConnectionAttempt:
    validation: HyroMcpConnectionValidation
    observation: HyroMcpObservation | None
    safe_error_code: str | None = None


HyroMcpTransportFactory = Callable[[HyroMcpConnectionConfig], HyroMcpReadTransport]


class HyroMcpConnectionBoundary:
    """Validate everything before constructing a transport or resolving a credential."""

    def __init__(self, transport_factory: HyroMcpTransportFactory) -> None:
        self._transport_factory = transport_factory

    def read(
        self,
        config: HyroMcpConnectionConfig,
        *,
        now: datetime | None = None,
    ) -> HyroMcpConnectionAttempt:
        validation = config.validate()
        if not validation.ready:
            return HyroMcpConnectionAttempt(validation, None, "CONNECTION_CONFIG_BLOCKED")
        try:
            tools = cast(HyroMcpToolProfile, config.tools)
            scope = cast(HyroMcpAccountScope, config.account_scope)
            transport = self._transport_factory(config)
            adapter = HyroMcpReadAdapter(transport, tools=tools)
            observation = adapter.read(scope, now=now)
        except Exception:
            failed = HyroMcpConnectionValidation(HyroMcpConnectionStatus.TRANSPORT_FAILED)
            return HyroMcpConnectionAttempt(failed, None, "MCP_TRANSPORT_FAILURE")
        return HyroMcpConnectionAttempt(validation, observation)


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
