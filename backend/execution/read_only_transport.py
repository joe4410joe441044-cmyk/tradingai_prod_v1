"""Narrow read-only transport boundary for offline venue adapters.

This module defines request/response values and a protocol only.  It never
imports an HTTP client, resolves a credential, signs a request, opens a socket,
or creates a default network transport.  A concrete transport must be injected
explicitly by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, Tuple


_ALLOWED_METHODS = frozenset({"GET"})


def _safe_text(name: str, value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    text = value.strip()
    if not allow_empty and not text:
        raise ValueError(f"{name} must be non-empty")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{name} must not contain control characters")
    return text


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class ReadTransportFailureKind(str, Enum):
    """Transport-level failure classification; no venue payload is retained."""

    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REDIRECT_REJECTED = "REDIRECT_REJECTED"
    POLICY_REJECTED = "POLICY_REJECTED"
    CREDENTIAL_REJECTED = "CREDENTIAL_REJECTED"
    READINESS_REJECTED = "READINESS_REJECTED"
    CLOCK_REJECTED = "CLOCK_REJECTED"
    STATE_UNKNOWN = "STATE_UNKNOWN"


class ReadTransportError(Exception):
    """Raised by an injected transport when no response could be obtained."""

    def __init__(self, kind: ReadTransportFailureKind, message: str = "read transport failure") -> None:
        try:
            normalized = kind if isinstance(kind, ReadTransportFailureKind) else ReadTransportFailureKind(kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown read transport failure kind") from exc
        self.kind = normalized
        super().__init__(message)


@dataclass(frozen=True)
class ReadOnlyRequest:
    """A credential-free, host-free, GET-only read request specification."""

    method: str
    path: str
    query: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        method = _safe_text("method", self.method)
        if method not in _ALLOWED_METHODS:
            raise ValueError("read-only request method must be GET")
        path = _safe_text("path", self.path)
        if not path.startswith("/v5/"):
            raise ValueError("read-only request path must be a Bybit V5 path")
        if "://" in path or "?" in path or "#" in path or "\\" in path or ".." in path:
            raise ValueError("read-only request path must not carry a host, query, fragment or traversal")
        if "%" in path:
            raise ValueError("read-only request path must not carry percent-encoding")
        if any(ord(char) > 126 for char in path):
            raise ValueError("read-only request path must be printable ASCII")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "path", path)
        query = tuple(self.query)
        normalized: list[Tuple[str, str]] = []
        for pair in query:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("query entries must be (key, value) tuples")
            key = _safe_text("query key", pair[0])
            value = _safe_text("query value", pair[1], allow_empty=True)
            if "&" in key or "=" in key or "?" in key or "#" in key:
                raise ValueError("query key must not contain delimiters")
            normalized.append((key, value))
        keys = [key for key, _ in normalized]
        if len(set(keys)) != len(keys):
            raise ValueError("query keys must not repeat")
        object.__setattr__(self, "query", tuple(normalized))

    def query_dict(self) -> dict[str, str]:
        return {key: value for key, value in self.query}


@dataclass(frozen=True)
class ReadOnlyResponse:
    """Raw injected response; the body is never logged or persisted by this layer."""

    status_code: int
    body: Mapping[str, Any]
    received_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise TypeError("status_code must be an integer")
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be a valid HTTP status")
        if not isinstance(self.body, Mapping):
            raise TypeError("response body must be a mapping")
        object.__setattr__(self, "received_at", _utc("received_at", self.received_at))


class ReadOnlyClock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Injected by explicit choice only; never constructed implicitly by an adapter."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ReadOnlyTransport(Protocol):
    def send(self, request: ReadOnlyRequest) -> ReadOnlyResponse: ...
