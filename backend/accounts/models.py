"""Immutable account identity values with no runtime or credential access."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4


ACCOUNT_IDENTITY_SCHEMA_VERSION = "tradingai-account-identity/v1"
_ACCOUNT_ID_RE = re.compile(r"^acc_[0-9a-f]{32}$")


class AccountType(str, Enum):
    NORMAL = "NORMAL"
    PROP = "PROP"


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    EXTERNAL_SIMULATION = "EXTERNAL_SIMULATION"
    LIVE = "LIVE"


class ExecutionVenue(str, Enum):
    INTERNAL_PAPER = "INTERNAL_PAPER"
    KUCOIN_FUTURES = "KUCOIN_FUTURES"
    BYBIT_DEMO = "BYBIT_DEMO"
    BLOFIN_DEMO = "BLOFIN_DEMO"
    HYRO_MCP = "HYRO_MCP"


class PropProgram(str, Enum):
    HYROTRADER = "HYROTRADER"


class PropPhase(str, Enum):
    FREE_TRIAL = "FREE_TRIAL"
    CHALLENGE = "CHALLENGE"
    VERIFICATION = "VERIFICATION"
    FUNDED = "FUNDED"
    UNKNOWN = "UNKNOWN"


class AccountLifecycleState(str, Enum):
    REGISTERED = "REGISTERED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


def _required_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _enum(enum_type, name: str, value: Any):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _exact_keys(data: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    if not isinstance(data, Mapping):
        raise TypeError("account identity must be a mapping")
    missing = required - set(data)
    unknown = set(data) - allowed
    if missing:
        raise ValueError("missing account identity fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("unknown account identity fields")


@dataclass(frozen=True, order=True)
class AccountId:
    """TradingAI-issued opaque ID; never derived from credentials or display data."""

    value: str

    def __post_init__(self) -> None:
        value = _required_text("account_id", self.value)
        if not _ACCOUNT_ID_RE.fullmatch(value):
            raise ValueError("account_id must match acc_<lowercase UUIDv4 hex>")
        parsed = UUID(hex=value[4:])
        if parsed.version != 4:
            raise ValueError("account_id must contain a UUIDv4 value")
        object.__setattr__(self, "value", value)

    @classmethod
    def new(cls) -> "AccountId":
        return cls(f"acc_{uuid4().hex}")

    def __str__(self) -> str:
        return self.value


_VENUES_BY_MODE = {
    ExecutionMode.PAPER: frozenset({ExecutionVenue.INTERNAL_PAPER}),
    ExecutionMode.EXTERNAL_SIMULATION: frozenset(
        {ExecutionVenue.BYBIT_DEMO, ExecutionVenue.BLOFIN_DEMO, ExecutionVenue.HYRO_MCP}
    ),
    ExecutionMode.LIVE: frozenset({ExecutionVenue.KUCOIN_FUTURES}),
}


@dataclass(frozen=True)
class AccountIdentity:
    schema_version: str
    account_id: AccountId
    account_type: AccountType
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    lifecycle_state: AccountLifecycleState
    revision: int
    created_at: datetime
    updated_at: datetime
    prop_program: Optional[PropProgram] = None
    prop_phase: Optional[PropPhase] = None

    def __post_init__(self) -> None:
        if self.schema_version != ACCOUNT_IDENTITY_SCHEMA_VERSION:
            raise ValueError("unsupported account identity schema")
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "account_type", _enum(AccountType, "account_type", self.account_type))
        object.__setattr__(self, "execution_mode", _enum(ExecutionMode, "execution_mode", self.execution_mode))
        object.__setattr__(self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue))
        object.__setattr__(self, "lifecycle_state", _enum(AccountLifecycleState, "lifecycle_state", self.lifecycle_state))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        created = _utc("created_at", self.created_at)
        updated = _utc("updated_at", self.updated_at)
        if updated < created:
            raise ValueError("updated_at must not precede created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        if self.prop_program is not None:
            object.__setattr__(self, "prop_program", _enum(PropProgram, "prop_program", self.prop_program))
        if self.prop_phase is not None:
            object.__setattr__(self, "prop_phase", _enum(PropPhase, "prop_phase", self.prop_phase))
        self._validate_scope()

    def _validate_scope(self) -> None:
        if self.execution_venue not in _VENUES_BY_MODE[self.execution_mode]:
            raise ValueError(
                f"execution_venue {self.execution_venue.value} is incompatible with "
                f"execution_mode {self.execution_mode.value}"
            )
        if self.account_type is AccountType.NORMAL:
            if self.prop_program is not None or self.prop_phase is not None:
                raise ValueError("NORMAL account must not declare PROP fields")
            return
        if self.prop_program is None or self.prop_phase is None:
            raise ValueError("PROP account requires prop_program and prop_phase")
        if self.execution_mode is ExecutionMode.LIVE:
            raise ValueError("PROP account must not be classified as real-capital LIVE")

    def to_dict(self) -> dict[str, Any]:
        """Return the public identity document; credential/external refs cannot leak."""

        return {
            "schema_version": self.schema_version,
            "account_id": self.account_id.value,
            "account_type": self.account_type.value,
            "execution_mode": self.execution_mode.value,
            "execution_venue": self.execution_venue.value,
            "lifecycle_state": self.lifecycle_state.value,
            "revision": self.revision,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "prop_program": self.prop_program.value if self.prop_program else None,
            "prop_phase": self.prop_phase.value if self.prop_phase else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccountIdentity":
        names = {item.name for item in fields(cls)}
        _exact_keys(data, names, names)
        try:
            created_at = datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00"))
            updated_at = datetime.fromisoformat(str(data["updated_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("account identity timestamps must be RFC3339") from exc
        return cls(
            schema_version=data["schema_version"],
            account_id=AccountId(data["account_id"]),
            account_type=data["account_type"],
            execution_mode=data["execution_mode"],
            execution_venue=data["execution_venue"],
            lifecycle_state=data["lifecycle_state"],
            revision=data["revision"],
            created_at=created_at,
            updated_at=updated_at,
            prop_program=data["prop_program"],
            prop_phase=data["prop_phase"],
        )


def ensure_account_match(expected: AccountId, actual: AccountId, *, label: str = "account") -> None:
    """Reject cross-account data instead of selecting or falling back to another account."""

    if not isinstance(expected, AccountId) or not isinstance(actual, AccountId):
        raise TypeError("account comparison requires AccountId values")
    if expected != actual:
        raise ValueError(f"{label} account_id mismatch")
