"""Read-only adapters from runtime authorities to the Supervisor snapshot builder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from backend.bot_manager.bot_manager import get_existing_bot_manager
from backend.money_management.loss_http_api import (
    APPLICATION_STATE_ATTRIBUTE as MONEY_MANAGEMENT_STATE_ATTRIBUTE,
    MoneyManagementHttpBoundary,
)
from backend.runtime import runtime_registry
from backend.runtime.governance_runtime import build_emergency_status, governance_state

from .contracts import ReadOnlySupervisorSnapshot
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .snapshot_builder import build_supervisor_snapshot
from .snapshot_sources import SnapshotFreshnessPolicy


# No shared producer-level threshold exists. Keep these provisional Supervisor
# observation thresholds in one place until an authoritative setting is defined.
PROVISIONAL_SOURCE_MAXIMUM_AGE = timedelta(seconds=30)
PROVISIONAL_FUTURE_TOLERANCE = timedelta(seconds=1)
DEFAULT_FRESHNESS_POLICY = SnapshotFreshnessPolicy(
    maximumAgeBySource=tuple(
        (source, PROVISIONAL_SOURCE_MAXIMUM_AGE)
        for source in ("bot", "governance", "moneyManagement", "health")
    ),
    futureTolerance=PROVISIONAL_FUTURE_TOLERANCE,
)

AuthorityReader = Callable[[object, datetime], Mapping[str, object] | None]


@dataclass(frozen=True)
class RuntimeAuthorityReaders:
    """Read-only authority callables; command handlers are intentionally absent."""

    bot: AuthorityReader
    governance: AuthorityReader
    moneyManagement: AuthorityReader
    health: AuthorityReader


def _selected(payload: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {field: payload[field] for field in fields if field in payload}


def _selected_nested(
    payload: Mapping[str, object],
    field: str,
    allowed_fields: tuple[str, ...],
) -> dict[str, object] | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_INVALID,
            f"{field} must be a mapping",
        )
    return _selected(value, allowed_fields)


def _pending_order_state(raw: Mapping[str, object]) -> object:
    value = raw.get("pendingOrderState")
    if isinstance(value, str) or value is None:
        return value
    if isinstance(value, Mapping):
        pending = value.get("pending")
        if type(pending) is bool:
            return "PENDING" if pending else "NONE"
        return "UNKNOWN"
    return None


def _bot_payload(raw: Mapping[str, object]) -> Mapping[str, object]:
    result = _selected(
        raw,
        (
            "sourceEvaluatedAt", "evaluatedAt", "generatedAt", "snapshotTimestamp",
            "timestamp", "freshness", "botState", "status", "loopEnabled",
            "loopState", "selectedMode", "dryRun", "autoTradeEnabled",
            "realOrderAllowed", "accountSource", "authoritativeRuntimeState",
            "runtimeSynchronizationState", "synchronizationState",
            "activeSymbol", "marketReady", "marketStale", "last_update", "lastUpdate",
            "selectionMode", "emergencyLocked", "emergencyState",
        ),
    )
    if "pendingOrderState" in raw:
        result["pendingOrderState"] = _pending_order_state(raw)
    nested_fields = {
        "tradeSettings": ("selectedMode", "mode"),
        "governance_state": ("mode", "executionEnabled", "execution_enabled"),
        "emergency": ("locked", "state"),
        "tradingDecision": ("status", "decision", "state", "evaluatedAt"),
        "autoMarketSelection": (
            "activeSymbol", "selectionSource", "amsRuntimeState", "runtimeState",
            "selectionCycleId", "cycleId", "safeSwitchState", "suitabilityEvidenceState",
        ),
        "market": ("activeSymbol", "symbol"),
    }
    for field, allowed in nested_fields.items():
        value = _selected_nested(raw, field, allowed)
        if value is not None:
            result[field] = value
    return result


def _governance_payload(raw: Mapping[str, object]) -> Mapping[str, object]:
    return _selected(
        raw,
        (
            "sourceEvaluatedAt", "evaluatedAt", "generatedAt", "freshness", "mode",
            "executionEnabled", "execution_enabled", "riskProfile", "risk_profile",
            "locked", "emergencyLocked", "emergency_stop", "state", "emergencyState",
            "emergency_state",
        ),
    )


def _money_management_payload(raw: Mapping[str, object]) -> Mapping[str, object]:
    result = _selected(raw, ("sourceEvaluatedAt", "generatedAt", "freshness"))
    eligibility = _selected_nested(
        raw,
        "capitalEligibility",
        (
            "capitalAuthority", "capitalSource", "equity", "availableCapital", "mmMode",
            "mmRegime", "riskBudget", "riskBudgetRemaining", "remainingExposure",
            "remainingExposureAmount", "remainingPositionCapacity", "ruinGuardStatus",
            "compoundingEnabled", "executionEntryAllowed", "policyVersion", "evaluatedAt",
            "sourceEvaluatedAt", "authorityFresh", "reasonCodes",
        ),
    )
    metrics = _selected_nested(
        raw,
        "metrics",
        (
            "equity", "availableCapital", "drawdown", "drawdownPercent", "currentExposure",
            "openExposure", "remainingExposure", "remainingExposureAmount",
            "openPositionState", "metricsGeneratedAt",
        ),
    )
    if eligibility is not None:
        result["capitalEligibility"] = eligibility
    if metrics is not None:
        result["metrics"] = metrics
    return result


def _health_payload(raw: Mapping[str, object]) -> Mapping[str, object]:
    return _selected(
        raw,
        (
            "sourceEvaluatedAt", "evaluatedAt", "generatedAt", "freshness",
            "backendStatus", "status", "health", "runtimeHealthy",
        ),
    )


def _read_bot(_app: object, _captured_at: datetime) -> Mapping[str, object] | None:
    manager = get_existing_bot_manager()
    if manager is None:
        return None
    payload = manager.get_status()
    return payload if isinstance(payload, Mapping) else None


def _read_governance(_app: object, captured_at: datetime) -> Mapping[str, object]:
    emergency = build_emergency_status()
    return {
        "sourceEvaluatedAt": captured_at,
        "mode": governance_state.get("mode"),
        "execution_enabled": governance_state.get("execution_enabled"),
        "risk_profile": governance_state.get("risk_profile"),
        "emergency_stop": emergency.get("locked"),
        "emergency_state": emergency.get("state"),
    }


def _read_money_management(app: object, _captured_at: datetime) -> Mapping[str, object] | None:
    state = getattr(app, "state", None)
    boundary = getattr(state, MONEY_MANAGEMENT_STATE_ATTRIBUTE, None)
    if not isinstance(boundary, MoneyManagementHttpBoundary):
        return None
    status = boundary.get_status()
    payload = status.to_dict()
    return payload if isinstance(payload, Mapping) else None


def _read_health(_app: object, captured_at: datetime) -> Mapping[str, object] | None:
    runtime = runtime_registry.trading_runtime
    if runtime is None:
        return None
    return {
        "sourceEvaluatedAt": captured_at,
        "status": "ok",
        "runtimeHealthy": getattr(runtime, "runtime_healthy", None),
    }


DEFAULT_AUTHORITY_READERS = RuntimeAuthorityReaders(
    bot=_read_bot,
    governance=_read_governance,
    moneyManagement=_read_money_management,
    health=_read_health,
)


class RuntimeSnapshotAdapter:
    """Collect bounded observations and invoke the pure snapshot builder."""

    def __init__(
        self,
        *,
        readers: RuntimeAuthorityReaders = DEFAULT_AUTHORITY_READERS,
        freshness_policy: SnapshotFreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._readers = readers
        self._freshness_policy = freshness_policy
        self._clock = clock

    @staticmethod
    def _read(
        reader: AuthorityReader,
        sanitizer: Callable[[Mapping[str, object]], Mapping[str, object]],
        app: object,
        captured_at: datetime,
    ) -> Mapping[str, object] | None:
        try:
            raw = reader(app, captured_at)
            if raw is None:
                return None
            if not isinstance(raw, Mapping):
                return None
            return sanitizer(raw)
        except Exception:
            return None

    def _utc_clock(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise SupervisorBoundaryError(
                SupervisorFailureCode.TIMESTAMP_INVALID,
                "snapshot capture clock must return timezone-aware UTC",
            )
        return value.astimezone(timezone.utc)

    def build(self, app: object) -> ReadOnlySupervisorSnapshot:
        bot_status = self._read(
            self._readers.bot, _bot_payload, app, self._utc_clock()
        )
        governance_status = self._read(
            self._readers.governance, _governance_payload, app, self._utc_clock()
        )
        money_management_status = self._read(
            self._readers.moneyManagement,
            _money_management_payload,
            app,
            self._utc_clock(),
        )
        health_payload = self._read(
            self._readers.health, _health_payload, app, self._utc_clock()
        )
        captured_at = self._utc_clock()
        return build_supervisor_snapshot(
            bot_status=bot_status,
            governance_status=governance_status,
            money_management_status=money_management_status,
            health_payload=health_payload,
            captured_at=captured_at,
            freshness_policy=self._freshness_policy,
        )
