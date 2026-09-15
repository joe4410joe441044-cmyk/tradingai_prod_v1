"""Read-only runtime parameter snapshot registry (E-PARAM-4).

This registry retains the *observed* runtime parameter snapshot that the live
trading runtime actually resolved for a scope.  It is deliberately small:

- scope-specific: one snapshot per canonical scope (PAPER / LIVE);
- bounded: at most ``max_entries`` scope snapshots are retained;
- in-memory: it never persists and never becomes a second configuration
  authority;
- read-only through the API: the PARAMETER SETTINGS API only reads it.

The registry is populated by the runtime authority (``BotManager``) at the
moment a cycle resolves its parameter set.  Read endpoints never record a
snapshot, so ``GET /runtime`` cannot fabricate an observed snapshot from a
fresh resolver call.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Optional

from .model import ParameterScope

_MAX_SCOPES = 8

_SCOPE_ALIASES = {
    "PAPER": ParameterScope.PAPER.value,
    "PAPER_ONLY": ParameterScope.PAPER.value,
    "LIVE": ParameterScope.LIVE.value,
    "LIVE_ONLY": ParameterScope.LIVE.value,
}


def normalize_runtime_scope(scope: Any) -> Optional[str]:
    """Return the canonical scope value (``PAPER``/``LIVE``) or ``None``."""

    if isinstance(scope, ParameterScope):
        return scope.value if scope in (
            ParameterScope.PAPER,
            ParameterScope.LIVE,
        ) else None
    if not isinstance(scope, str):
        return None
    return _SCOPE_ALIASES.get(scope.strip().upper())


def _snapshot_payload(snapshot: Any) -> Optional[dict]:
    if snapshot is None:
        return None
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    to_dict = getattr(snapshot, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


class RuntimeParameterSnapshotRegistry:
    """Bounded, scope-specific, in-memory observed snapshot registry."""

    def __init__(self, max_entries: int = _MAX_SCOPES):
        try:
            bound = int(max_entries)
        except (TypeError, ValueError):
            bound = _MAX_SCOPES
        self._max_entries = max(1, bound)
        self._lock = threading.Lock()
        self._snapshots: dict = {}

    def record(self, scope: Any, snapshot: Any) -> bool:
        normalized = normalize_runtime_scope(scope)
        if normalized is None:
            return False
        payload = _snapshot_payload(snapshot)
        if payload is None:
            return False
        with self._lock:
            if (
                normalized not in self._snapshots
                and len(self._snapshots) >= self._max_entries
            ):
                oldest = next(iter(self._snapshots))
                self._snapshots.pop(oldest, None)
            self._snapshots[normalized] = payload
        return True

    def get(self, scope: Any) -> Optional[dict]:
        normalized = normalize_runtime_scope(scope)
        if normalized is None:
            return None
        with self._lock:
            payload = self._snapshots.get(normalized)
        return dict(payload) if payload is not None else None

    def available(self, scope: Any) -> bool:
        return self.get(scope) is not None

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()

    def scopes(self) -> tuple:
        with self._lock:
            return tuple(sorted(self._snapshots))


_DEFAULT_REGISTRY = RuntimeParameterSnapshotRegistry()


def record_runtime_snapshot(scope: Any, snapshot: Any) -> bool:
    return _DEFAULT_REGISTRY.record(scope, snapshot)


def get_runtime_snapshot(scope: Any) -> Optional[dict]:
    return _DEFAULT_REGISTRY.get(scope)


def runtime_snapshot_available(scope: Any) -> bool:
    return _DEFAULT_REGISTRY.available(scope)


def reset_runtime_snapshots() -> None:
    _DEFAULT_REGISTRY.clear()


def default_runtime_snapshot_registry() -> RuntimeParameterSnapshotRegistry:
    return _DEFAULT_REGISTRY
