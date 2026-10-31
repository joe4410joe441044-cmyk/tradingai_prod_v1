"""Safety classification for runtime readers used by the context adapter.

Only readers in ``CONNECTED_READERS`` are called. Unsafe or unproven readers
are listed so callers can see why they are not attached. Production is not
contacted by this classification.
"""

from __future__ import annotations

from dataclasses import dataclass

VERIFIED_READ_ONLY = "VERIFIED_READ_ONLY"
READ_ONLY_WITH_CONDITIONS = "READ_ONLY_WITH_CONDITIONS"
SIDE_EFFECT_RISK = "SIDE_EFFECT_RISK"
UNKNOWN = "UNKNOWN"

RUNTIME_INSTANCE_NOT_INJECTED = "RUNTIME_INSTANCE_NOT_INJECTED"
UNSAFE_READER_SKIPPED = "UNSAFE_READER_SKIPPED"

# Re-evaluated from the BB-3.5 field list after wiring the pure readers below.
# Mock dictionaries alone do not move a field into VERIFIED_CONNECTED.
VERIFIED_CONNECTED_FIELDS = 24
SOURCE_EXISTS_NOT_CONNECTED_FIELDS = 27
SOURCE_NOT_FOUND_FIELDS = 3
UNAVAILABLE_BY_DESIGN_FIELDS = 8
STALE_OR_UNPROVEN_FIELDS = 1
CONFLICTING_SOURCES_FIELDS = 0
UNKNOWN_FIELDS = 0

CONNECTED_READERS = (
    "current_position",
    "build_trading_cycle_diagnostics",
    "build_supervisor_snapshot",
)

# Fields the pure position and cycle readers actually emit into the pack.
# diagnosticScope CURRENT stays STALE_OR_UNPROVEN: a matching cycle id is not
# proof that Production's live cycle was observed.
VERIFIED_POSITION_FIELDS = (
    "position.status",
    "position.symbol",
    "position.mode",
    "position.side",
    "position.quantity",
    "position.contractQuantity",
    "position.coinQuantity",
    "position.avgEntry",
    "position.entryTime",
    "position.pnlUsdt",
    "position.durationSeconds",
    "position.leverage",
)
VERIFIED_CYCLE_FIELDS = (
    "tradingCycle.cycleState",
    "tradingCycle.rootBlocker",
    "tradingCycle.rootBlockerStep",
    "tradingCycle.stepStatus",
    "tradingCycle.blockerType",
    "tradingCycle.userActionRequired",
    "tradingCycle.evaluatedAt",
    "tradingCycle.diagnosticsGeneratedAt",
    "tradingCycle.sourceUpdatedAt",
    "tradingCycle.currentRequired",
    "tradingCycle.HISTORICAL",
    "tradingCycle.UNKNOWN",
)
SOURCE_NOT_FOUND_NAMES = (
    "account.currency",
    "smallAccount.takeProfitPercent",
    "smallAccount.timeExitSeconds",
)
UNAVAILABLE_BY_DESIGN_NAMES = (
    "position.avgExit",
    "position.exitTime",
    "position.pnlPercent",
    "position.riskPercent",
    "position.stopLossPercent",
    "position.takeProfitPercent",
    "position.trailingPercent",
    "position.timeExitSeconds",
)
STALE_OR_UNPROVEN_NAMES = ("tradingCycle.CURRENT",)

assert len(VERIFIED_POSITION_FIELDS) + len(VERIFIED_CYCLE_FIELDS) == VERIFIED_CONNECTED_FIELDS
assert len(SOURCE_NOT_FOUND_NAMES) == SOURCE_NOT_FOUND_FIELDS
assert len(UNAVAILABLE_BY_DESIGN_NAMES) == UNAVAILABLE_BY_DESIGN_FIELDS
assert len(STALE_OR_UNPROVEN_NAMES) == STALE_OR_UNPROVEN_FIELDS
assert (
    VERIFIED_CONNECTED_FIELDS
    + SOURCE_EXISTS_NOT_CONNECTED_FIELDS
    + SOURCE_NOT_FOUND_FIELDS
    + UNAVAILABLE_BY_DESIGN_FIELDS
    + STALE_OR_UNPROVEN_FIELDS
    + CONFLICTING_SOURCES_FIELDS
    + UNKNOWN_FIELDS
) == 63

SKIPPED_READERS = (
    ("BotManager.get_status", UNKNOWN, "delegates to get_result; mutation was not ruled out"),
    ("BotManager.get_result", UNKNOWN, "large status builder; not proven free of state changes"),
    ("get_bot_manager", SIDE_EFFECT_RISK, "creates a BotManager when none exists"),
    ("RuntimeSnapshotAdapter._read_bot", UNKNOWN, "calls get_status"),
    ("BotManager._build_account_runtime", SIDE_EFFECT_RISK, "reads the real-account snapshot from the manager"),
    ("MoneyManagementHttpBoundary.get_status", UNKNOWN, "reads live application state; dispatch side effects were not ruled out"),
    ("build_emergency_status", READ_ONLY_WITH_CONDITIONS, "reads process-global governance state and is not called without an injected snapshot"),
)


@dataclass(frozen=True)
class SkippedReader:
    name: str
    safety: str
    reason: str


@dataclass(frozen=True)
class AdapterFailure:
    source: str
    category: str
    availability: str = "UNAVAILABLE"
    freshness: str = "UNKNOWN"
