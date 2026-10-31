"""Result records for the read-only runtime collector.

These records sit beside ``tradingai-context/v1``. They do not extend the
canonical schema and they do not grant runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .schema import CanonicalContext

READER_NOT_INJECTED = "READER_NOT_INJECTED"
READER_UNAVAILABLE = "READER_UNAVAILABLE"
READER_REJECTED = "READER_REJECTED"
READER_FAILED = "READER_FAILED"

FAILURE_CATEGORIES = frozenset(
    {
        READER_NOT_INJECTED,
        READER_UNAVAILABLE,
        READER_REJECTED,
        READER_FAILED,
    }
)

SLOT_SUPERVISOR = "supervisor_snapshot"
SLOT_POSITION = "position"
SLOT_ACCOUNT = "account"
SLOT_MM = "mm"
SLOT_CYCLE = "trading_cycle"
SLOT_EXECUTION = "execution_control"
SLOT_BOT_STATUS = "bot_status"

RUNTIME_SLOTS = (
    SLOT_SUPERVISOR,
    SLOT_POSITION,
    SLOT_ACCOUNT,
    SLOT_MM,
    SLOT_CYCLE,
    SLOT_EXECUTION,
)

# BB-3.5 did not prove BotManager.get_status / get_result side-effect free.
# This package therefore never connects itself to the live runtime.
PRODUCTION_RUNTIME_CONNECTED = False


@dataclass(frozen=True)
class ReaderFailure:
    """One reader that did not produce evidence.

    ``category`` is a fixed token. Exception text is never stored here.
    ``observedAt`` stays empty unless the caller already proved a producer time.
    """

    source: str
    category: str
    availability: str = "UNAVAILABLE"
    observedAt: datetime | None = None
    freshness: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.source not in RUNTIME_SLOTS and self.source != SLOT_BOT_STATUS:
            raise ValueError("reader failure source is not a collector slot")
        if self.category not in FAILURE_CATEGORIES:
            raise ValueError("reader failure category is not recognized")
        if self.availability != "UNAVAILABLE":
            raise ValueError("reader failure availability must stay UNAVAILABLE")
        if self.freshness != "UNKNOWN":
            raise ValueError("reader failure freshness must stay UNKNOWN")
        if self.observedAt is not None:
            raise ValueError("a failed reader has no proven observation time")


@dataclass(frozen=True)
class RuntimeCollection:
    """Canonical pack plus the two sharing views.

    ``production_runtime_connected`` is always false. Injected readers are
    not a live Production attachment.
    """

    context: CanonicalContext
    failures: tuple[ReaderFailure, ...]
    connected_sources: tuple[str, ...]
    public_view: dict[str, object]
    operator_view: dict[str, object]
    production_runtime_connected: bool = False

    def __post_init__(self) -> None:
        if self.production_runtime_connected is not False:
            raise ValueError("collector must not claim a Production runtime connection")
        if not isinstance(self.context, CanonicalContext):
            raise TypeError("context must be a CanonicalContext")
