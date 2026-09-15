"""Canonical, immutable StrategyParameterSet model (E-PARAM-1).

This module defines the frozen canonical model and its enums.  It is pure
data: it does not persist anything and is not imported by any Trading Cycle
consumer.

Revision architecture (approved):
- ``configuredRevision`` increments on every accepted CONFIGURED write.
- ``effectiveRevision`` increments when a configured set is promoted.
Runtime revision is intentionally NOT persisted as an independent mutable
counter in this task; it is the ``effectiveRevision`` captured at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

CANONICAL_SCHEMA_VERSION = 1


class ParameterScope(str, Enum):
    """Persistence scope of a canonical parameter set."""

    PAPER = "PAPER"
    LIVE = "LIVE"
    BOTH = "BOTH"


class ParameterStatus(str, Enum):
    """Lifecycle status of a canonical parameter set."""

    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ParameterSource(str, Enum):
    """Provenance of a canonical parameter set."""

    PARAMETER_SETTINGS = "PARAMETER_SETTINGS"
    MIGRATED_PAPER_CALIBRATION = "MIGRATED_PAPER_CALIBRATION"
    MIGRATED_CLASS_CONSTANT = "MIGRATED_CLASS_CONSTANT"
    DEFAULT = "DEFAULT"
    ROLLBACK = "ROLLBACK"


def _normalize_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not a valid ISO-8601 timestamp") from exc
    else:
        raise TypeError(f"{field} must be a datetime or ISO-8601 string")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_timestamp(moment: datetime) -> str:
    """Deterministic ISO-8601 UTC serialization with microseconds."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class StrategyParameterSet:
    """Immutable, validated canonical strategy parameter set."""

    parameterSetId: str
    schemaVersion: int
    scope: ParameterScope
    status: ParameterStatus
    createdAt: datetime
    updatedAt: datetime
    source: ParameterSource
    parameters: Mapping[str, float]
    effectiveFrom: Optional[datetime]
    configuredRevision: int
    effectiveRevision: int

    def __post_init__(self) -> None:
        if not isinstance(self.parameterSetId, str) or not self.parameterSetId:
            raise ValueError("parameterSetId must be a non-empty string")
        if self.schemaVersion != CANONICAL_SCHEMA_VERSION:
            raise ValueError(
                "unsupported schemaVersion "
                f"{self.schemaVersion!r}; expected {CANONICAL_SCHEMA_VERSION}"
            )
        if isinstance(self.configuredRevision, bool) or not isinstance(
            self.configuredRevision, int
        ):
            raise TypeError("configuredRevision must be an int")
        if isinstance(self.effectiveRevision, bool) or not isinstance(
            self.effectiveRevision, int
        ):
            raise TypeError("effectiveRevision must be an int")
        if self.configuredRevision < 0 or self.effectiveRevision < 0:
            raise ValueError("revisions must be non-negative")
        if self.effectiveRevision > self.configuredRevision:
            raise ValueError(
                "effectiveRevision must not exceed configuredRevision"
            )
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a mapping")

        object.__setattr__(self, "scope", ParameterScope(self.scope))
        object.__setattr__(self, "status", ParameterStatus(self.status))
        object.__setattr__(self, "source", ParameterSource(self.source))
        object.__setattr__(
            self, "createdAt", _normalize_datetime(self.createdAt, "createdAt")
        )
        object.__setattr__(
            self, "updatedAt", _normalize_datetime(self.updatedAt, "updatedAt")
        )
        if self.effectiveFrom is not None:
            object.__setattr__(
                self,
                "effectiveFrom",
                _normalize_datetime(self.effectiveFrom, "effectiveFrom"),
            )
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters))
        )

        from .registry import StrategyParameterRegistry
        from .validation import validate_parameters

        raw_result = validate_parameters(self.parameters, require_complete=True)
        if raw_result.errors:
            raise ValueError(
                "invalid strategy parameter set: "
                + "; ".join(issue.message for issue in raw_result.errors)
            )

        quantized = {}
        for name, value in self.parameters.items():
            metadata = StrategyParameterRegistry.get(name)
            quantized[name] = metadata.quantize(value)
        quantized_result = validate_parameters(
            quantized, require_complete=True
        )
        if quantized_result.errors:
            raise ValueError(
                "invalid strategy parameter set: "
                + "; ".join(issue.message for issue in quantized_result.errors)
            )
        object.__setattr__(
            self, "parameters", MappingProxyType(quantized)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.parameterSetId,
                self.schemaVersion,
                self.scope,
                self.status,
                self.createdAt,
                self.updatedAt,
                self.source,
                tuple(sorted(self.parameters.items())),
                self.effectiveFrom,
                self.configuredRevision,
                self.effectiveRevision,
            )
        )

    def parameter_value(self, name: str) -> float:
        """Return the canonical value for ``name`` (KeyError if absent)."""

        return self.parameters[name]

    def values(self) -> Mapping[str, float]:
        """Return a plain immutable copy of the name -> value map."""

        return MappingProxyType(dict(self.parameters))

    def to_dict(self) -> dict:
        """Deterministic plain-dict representation."""

        return {
            "parameterSetId": self.parameterSetId,
            "schemaVersion": self.schemaVersion,
            "scope": self.scope.value,
            "status": self.status.value,
            "createdAt": format_timestamp(self.createdAt),
            "updatedAt": format_timestamp(self.updatedAt),
            "source": self.source.value,
            "parameters": {
                name: self.parameters[name]
                for name in sorted(self.parameters)
            },
            "effectiveFrom": (
                format_timestamp(self.effectiveFrom)
                if self.effectiveFrom is not None
                else None
            ),
            "configuredRevision": self.configuredRevision,
            "effectiveRevision": self.effectiveRevision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategyParameterSet":
        """Build a validated set from a plain mapping."""

        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        return cls(
            parameterSetId=payload["parameterSetId"],
            schemaVersion=payload["schemaVersion"],
            scope=payload["scope"],
            status=payload["status"],
            createdAt=payload["createdAt"],
            updatedAt=payload["updatedAt"],
            source=payload["source"],
            parameters=payload["parameters"],
            effectiveFrom=payload.get("effectiveFrom"),
            configuredRevision=payload["configuredRevision"],
            effectiveRevision=payload["effectiveRevision"],
        )
