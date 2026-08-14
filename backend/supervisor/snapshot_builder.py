"""Pure construction of a bounded Supervisor read-only snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from pydantic import ValidationError

from .authority_mapping import CRITICAL_DOMAINS, deduplicate_warnings, values_conflict, warning
from .contracts import (
    CapitalSource, DomainSnapshot, FieldValueObservation, Freshness, InputValueState,
    MoneyManagementSnapshot, ReadOnlySupervisorSnapshot, SnapshotWarning,
)
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .snapshot_sources import SnapshotFreshnessPolicy, SnapshotSource


_FRESHNESS_PRIORITY = {
    Freshness.FRESH: 0,
    Freshness.UNKNOWN: 1,
    Freshness.STALE: 2,
    Freshness.MISSING: 3,
    Freshness.CONFLICTED: 4,
}


def _payload(source: SnapshotSource | Mapping[str, object] | None) -> Mapping[str, object] | None:
    if isinstance(source, SnapshotSource):
        return source.payload
    if source is None or isinstance(source, Mapping):
        return source
    raise SupervisorBoundaryError(
        SupervisorFailureCode.INPUT_INVALID, "snapshot sources must be typed mappings or None"
    )


def _nested(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_INVALID, f"approved nested field {key} must be a mapping"
        )
    return value


def _first(mappings: Sequence[Mapping[str, object]], *keys: str) -> object:
    for mapping in mappings:
        for key in keys:
            if key in mapping:
                return mapping[key]
    return None


def _field_state(
    field: str, mappings: Sequence[Mapping[str, object]], *keys: str
) -> FieldValueObservation:
    for mapping in mappings:
        for key in keys:
            if key in mapping:
                value = mapping[key]
                if value is None:
                    state = InputValueState.NULL
                elif isinstance(value, str) and value.strip().upper() == "UNKNOWN":
                    state = InputValueState.UNKNOWN
                else:
                    state = InputValueState.PRESENT
                return FieldValueObservation(field=field, state=state)
    return FieldValueObservation(field=field, state=InputValueState.ABSENT)


def _timestamp(value: object, *, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.TIMESTAMP_INVALID, f"{field} is not a valid timestamp"
            ) from exc
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            result = datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.TIMESTAMP_INVALID, f"{field} is not a valid timestamp"
            ) from exc
    else:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID, f"{field} is not a valid timestamp"
        )
    if result.tzinfo is None or result.utcoffset() is None:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID, f"{field} must be timezone-aware"
        )
    return result.astimezone(timezone.utc)


def _source_timestamp(source: str, payload: Mapping[str, object] | None) -> datetime | None:
    if payload is None:
        return None
    if source == "moneyManagement":
        eligibility = _nested(payload, "capitalEligibility")
        metrics = _nested(payload, "metrics")
        raw = _first(
            (eligibility, payload, metrics),
            "sourceEvaluatedAt", "evaluatedAt", "generatedAt", "metricsGeneratedAt",
        )
    else:
        raw = _first(
            (payload,), "sourceEvaluatedAt", "evaluatedAt", "generatedAt",
            "snapshotTimestamp", "timestamp",
        )
    return _timestamp(raw, field=f"{source}.sourceEvaluatedAt")


def _source_freshness(
    source: str,
    payload: Mapping[str, object] | None,
    captured_at: datetime,
    policy: SnapshotFreshnessPolicy,
    warnings: list[SnapshotWarning],
) -> tuple[Freshness, datetime | None]:
    if payload is None:
        warnings.append(warning(
            SupervisorFailureCode.INPUT_MISSING, source, "source", "authoritative source is missing", None
        ))
        return Freshness.MISSING, None
    evaluated_at = _source_timestamp(source, payload)
    if evaluated_at is not None and evaluated_at > captured_at + policy.futureTolerance:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.TIMESTAMP_INVALID, f"{source} timestamp is in the future"
        )
    explicit = payload.get("freshness")
    if explicit is not None:
        try:
            explicit_freshness = explicit if isinstance(explicit, Freshness) else Freshness(explicit)
        except ValueError as exc:
            raise SupervisorBoundaryError(
                SupervisorFailureCode.INPUT_INVALID, f"{source}.freshness is invalid"
            ) from exc
        if explicit_freshness is Freshness.CONFLICTED:
            warnings.append(warning(
                SupervisorFailureCode.INPUT_CONFLICTED, source, "freshness",
                "producer reported conflicting authority", evaluated_at,
            ))
            return Freshness.CONFLICTED, evaluated_at
        if explicit_freshness is Freshness.MISSING:
            warnings.append(warning(
                SupervisorFailureCode.INPUT_MISSING, source, "freshness",
                "producer reported missing authority", evaluated_at,
            ))
            return Freshness.MISSING, evaluated_at
        if explicit_freshness is Freshness.UNKNOWN:
            warnings.append(warning(
                SupervisorFailureCode.INPUT_INVALID, source, "freshness",
                "producer freshness is unknown", evaluated_at,
            ))
            return Freshness.UNKNOWN, evaluated_at
        if explicit_freshness is Freshness.STALE:
            warnings.append(warning(
                SupervisorFailureCode.INPUT_STALE, source, "freshness",
                "producer reported stale authority", evaluated_at,
            ))
            return Freshness.STALE, evaluated_at
    if evaluated_at is None:
        warnings.append(warning(
            SupervisorFailureCode.INPUT_MISSING, source, "sourceEvaluatedAt",
            "source timestamp is missing; freshness cannot be inferred", None,
        ))
        return Freshness.UNKNOWN, None
    maximum_age = policy.maximum_age(source)
    if maximum_age is None:
        warnings.append(warning(
            SupervisorFailureCode.INPUT_INVALID, source, "maximumAge",
            "freshness threshold was not supplied", evaluated_at,
        ))
        return Freshness.UNKNOWN, evaluated_at
    if captured_at - evaluated_at > maximum_age:
        warnings.append(warning(
            SupervisorFailureCode.INPUT_STALE, source, "sourceEvaluatedAt",
            "authoritative source is stale under the supplied policy", evaluated_at,
        ))
        return Freshness.STALE, evaluated_at
    return Freshness.FRESH, evaluated_at


def _string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, f"{field} must be a string or null")
    return value


def _bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, f"{field} must be boolean or null")
    return value


def _decimal(value: object, field: str, *, non_negative: bool = False) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, (Decimal, int, str)):
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, f"{field} must be an exact Decimal value")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, f"{field} is not a valid Decimal") from exc
    if not result.is_finite() or (non_negative and result < 0):
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, f"{field} is invalid")
    return result


def _reason_codes(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)) or any(not isinstance(item, str) for item in value):
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, "reasonCodes must be a string sequence")
    return tuple(value)


def _capital_source(value: object, warnings: list[SnapshotWarning], evaluated_at: datetime | None) -> CapitalSource:
    if value is None:
        return CapitalSource.UNKNOWN
    if not isinstance(value, str):
        raise SupervisorBoundaryError(SupervisorFailureCode.INPUT_INVALID, "capitalSource must be a string")
    normalized = value.strip().upper()
    if normalized in {"PAPER", "PAPER_SIMULATION", "PAPER_ACCOUNT"}:
        return CapitalSource.PAPER
    if normalized in {
        "LIVE", "LIVE_ACCOUNT", "LIVE_ACCOUNT_AUTHORITY", "REAL_LIVE_ACCOUNT",
    }:
        return CapitalSource.LIVE
    if normalized not in {"", "UNKNOWN", "UNSPECIFIED"}:
        warnings.append(warning(
            SupervisorFailureCode.INPUT_INVALID, "moneyManagement", "capitalSource",
            "capital source is not a recognized Paper or Live authority", evaluated_at,
        ))
    return CapitalSource.UNKNOWN


_KNOWN_RUIN_GUARD_STATES = frozenset({
    "NORMAL", "CAUTION", "DEFENSIVE", "LOCKED", "RECOVERY_25", "RECOVERY_50",
})


def _ruin_guard_status(
    value: object,
    warnings: list[SnapshotWarning],
    evaluated_at: datetime | None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SupervisorBoundaryError(
            SupervisorFailureCode.INPUT_INVALID, "riskState must be a string or null"
        )
    normalized = value.strip().upper()
    if normalized in _KNOWN_RUIN_GUARD_STATES:
        return normalized
    if normalized != "UNKNOWN":
        warnings.append(warning(
            SupervisorFailureCode.INPUT_INVALID, "moneyManagement", "riskState",
            "risk state is not a recognized Money Management authority", evaluated_at,
        ))
    return "UNKNOWN"


def _domain(
    freshness: Freshness,
    evaluated_at: datetime | None,
    source: str,
    field_states: tuple[FieldValueObservation, ...] = (),
    **values: object,
) -> DomainSnapshot:
    return DomainSnapshot(
        freshness=freshness,
        evaluatedAt=evaluated_at,
        source=source,
        fieldStates=field_states,
        **values,
    )


def _mark_conflict(
    current: Freshness,
    warnings: list[SnapshotWarning],
    domain: str,
    field: str,
    evaluated_at: datetime | None,
    message: str,
) -> Freshness:
    warnings.append(warning(
        SupervisorFailureCode.INPUT_CONFLICTED, domain, field, message, evaluated_at
    ))
    return Freshness.CONFLICTED


def build_supervisor_snapshot(
    *,
    bot_status: SnapshotSource | Mapping[str, object] | None,
    governance_status: SnapshotSource | Mapping[str, object] | None,
    money_management_status: SnapshotSource | Mapping[str, object] | None,
    health_payload: SnapshotSource | Mapping[str, object] | None,
    captured_at: datetime,
    freshness_policy: SnapshotFreshnessPolicy,
) -> ReadOnlySupervisorSnapshot:
    """Map supplied authority payloads without I/O, mutation, or recalculation."""
    captured = _timestamp(captured_at, field="capturedAt")
    assert captured is not None
    bot = _payload(bot_status)
    governance = _payload(governance_status)
    mm = _payload(money_management_status)
    health = _payload(health_payload)
    warnings: list[SnapshotWarning] = []

    bot_fresh, bot_at = _source_freshness("bot", bot, captured, freshness_policy, warnings)
    gov_fresh, gov_at = _source_freshness("governance", governance, captured, freshness_policy, warnings)
    mm_fresh, mm_at = _source_freshness("moneyManagement", mm, captured, freshness_policy, warnings)
    health_fresh, health_at = _source_freshness("health", health, captured, freshness_policy, warnings)

    bot_data = bot or {}
    gov_data = governance or {}
    health_data = health or {}
    trade_settings = _nested(bot_data, "tradeSettings")
    bot_governance = _nested(bot_data, "governance_state")
    emergency_nested = _nested(bot_data, "emergency")
    trading_decision = _nested(bot_data, "tradingDecision")
    auto_market = _nested(bot_data, "autoMarketSelection")
    market_nested = _nested(bot_data, "market")

    governance_mode = _string(_first((gov_data,), "mode"), "governance.mode")
    governance_execution = _bool(
        _first((gov_data,), "executionEnabled", "execution_enabled"), "governance.executionEnabled"
    )
    governance_risk = _string(
        _first((gov_data,), "riskProfile", "risk_profile"), "governance.riskProfile"
    )
    emergency_locked = _bool(
        _first((gov_data,), "locked", "emergencyLocked", "emergency_stop"), "emergency.locked"
    )
    emergency_state = _string(
        _first((gov_data,), "state", "emergencyState", "emergency_state"), "emergency.state"
    )

    if values_conflict(governance_mode, _first((bot_governance,), "mode")):
        gov_fresh = _mark_conflict(gov_fresh, warnings, "governance", "mode", gov_at,
                                   "Bot payload conflicts with Governance owner")
    if values_conflict(governance_execution, _first((bot_data, bot_governance), "executionEnabled", "execution_enabled")):
        gov_fresh = _mark_conflict(gov_fresh, warnings, "governance", "executionEnabled", gov_at,
                                   "Bot payload conflicts with Governance owner")
    bot_emergency_locked = _first((emergency_nested, bot_data), "locked", "emergencyLocked")
    bot_emergency_state = _first((emergency_nested, bot_data), "state", "emergencyState")
    emergency_fresh = gov_fresh
    if values_conflict(emergency_locked, bot_emergency_locked):
        emergency_fresh = _mark_conflict(emergency_fresh, warnings, "emergency", "locked", gov_at,
                                         "Bot payload conflicts with Emergency owner")
    if values_conflict(emergency_state, bot_emergency_state):
        emergency_fresh = _mark_conflict(emergency_fresh, warnings, "emergency", "state", gov_at,
                                         "Bot payload conflicts with Emergency owner")

    active_symbol = _string(_first((bot_data,), "activeSymbol"), "market.activeSymbol")
    for secondary in (
        _first((market_nested,), "activeSymbol", "symbol"),
        _first((auto_market,), "activeSymbol"),
    ):
        if values_conflict(active_symbol, secondary):
            bot_fresh = _mark_conflict(bot_fresh, warnings, "market", "activeSymbol", bot_at,
                                       "active symbol authorities conflict")

    mm_data = mm or {}
    eligibility = _nested(mm_data, "capitalEligibility")
    metrics = _nested(mm_data, "metrics")
    mm_layers = (eligibility, mm_data)
    metric_layers = (metrics, mm_data)
    capital_source = _capital_source(_first(mm_layers, "capitalSource"), warnings, mm_at)
    account_source = _capital_source(_first((bot_data,), "accountSource"), [], bot_at)
    if capital_source is not CapitalSource.UNKNOWN and account_source is not CapitalSource.UNKNOWN and capital_source is not account_source:
        mm_fresh = _mark_conflict(mm_fresh, warnings, "moneyManagement", "capitalSource", mm_at,
                                  "Money Management and account capital sources conflict")
        capital_source = CapitalSource.UNKNOWN

    risk_state_value = _first((mm_data,), "riskState")
    ruin_guard_status = (
        _ruin_guard_status(risk_state_value, warnings, mm_at)
        if risk_state_value is not None
        else _string(_first(mm_layers, "ruinGuardStatus"), "moneyManagement.ruinGuardStatus")
    )

    money_management = MoneyManagementSnapshot(
        capitalAuthority=_string(_first(mm_layers, "capitalAuthority"), "moneyManagement.capitalAuthority"),
        capitalSource=capital_source,
        equity=_decimal(_first(mm_layers + metric_layers, "equity"), "moneyManagement.equity"),
        availableCapital=_decimal(_first(mm_layers + metric_layers, "availableCapital"), "moneyManagement.availableCapital"),
        mmMode=_string(_first(mm_layers, "mmMode"), "moneyManagement.mmMode"),
        mmRegime=_string(_first(mm_layers, "mmRegime"), "moneyManagement.mmRegime"),
        riskBudget=_decimal(_first(mm_layers, "riskBudget", "riskBudgetRemaining"), "moneyManagement.riskBudget"),
        remainingExposure=_decimal(_first(mm_layers + metric_layers, "remainingExposure", "remainingExposureAmount"),
                                   "moneyManagement.remainingExposure", non_negative=True),
        remainingPositionCapacity=_decimal(_first(mm_layers, "remainingPositionCapacity"),
                                           "moneyManagement.remainingPositionCapacity", non_negative=True),
        ruinGuardStatus=ruin_guard_status,
        compoundingEnabled=_bool(_first(mm_layers, "compoundingEnabled"), "moneyManagement.compoundingEnabled"),
        executionEntryAllowed=_bool(_first(mm_layers, "executionEntryAllowed"), "moneyManagement.executionEntryAllowed"),
        policyVersion=_string(_first(mm_layers, "policyVersion"), "moneyManagement.policyVersion"),
        evaluatedAt=mm_at,
        authorityFresh=_bool(_first(mm_layers, "authorityFresh"), "moneyManagement.authorityFresh"),
        drawdown=_decimal(_first(metric_layers, "drawdown", "drawdownPercent"), "moneyManagement.drawdown"),
        currentExposure=_decimal(_first(metric_layers, "currentExposure", "openExposure"),
                                 "moneyManagement.currentExposure", non_negative=True),
        openPositionState=_string(_first(metric_layers, "openPositionState"), "moneyManagement.openPositionState"),
        reasonCodes=_reason_codes(_first(mm_layers, "reasonCodes")),
        freshness=mm_fresh,
        fieldStates=tuple(
            _field_state(field, mm_layers if field not in {"drawdown", "currentExposure", "openPositionState"}
                         else metric_layers, *keys)
            for field, keys in (
                ("capitalAuthority", ("capitalAuthority",)),
                ("capitalSource", ("capitalSource",)),
                ("equity", ("equity",)),
                ("availableCapital", ("availableCapital",)),
                ("mmMode", ("mmMode",)),
                ("mmRegime", ("mmRegime",)),
                ("riskBudget", ("riskBudget", "riskBudgetRemaining")),
                ("remainingExposure", ("remainingExposure", "remainingExposureAmount")),
                ("remainingPositionCapacity", ("remainingPositionCapacity",)),
                ("ruinGuardStatus", ("ruinGuardStatus",)),
                ("compoundingEnabled", ("compoundingEnabled",)),
                ("executionEntryAllowed", ("executionEntryAllowed",)),
                ("policyVersion", ("policyVersion",)),
                ("authorityFresh", ("authorityFresh",)),
                ("drawdown", ("drawdown", "drawdownPercent")),
                ("currentExposure", ("currentExposure", "openExposure")),
                ("openPositionState", ("openPositionState",)),
                ("reasonCodes", ("reasonCodes",)),
            )
        ),
    )

    real_order_allowed = _bool(_first((bot_data,), "realOrderAllowed"), "trade.realOrderAllowed")
    execution_fresh = bot_fresh
    mm_entry = money_management.executionEntryAllowed
    unsafe_real_order = real_order_allowed is True and (
        governance_execution is not True or emergency_locked is not False or mm_entry is not True
    )
    if unsafe_real_order:
        execution_fresh = _mark_conflict(
            execution_fresh, warnings, "execution", "realOrderAllowed", bot_at,
            "real order permission conflicts with safety authority; converted to false",
        )
        real_order_allowed = False

    domains = {
        "bot": _domain(bot_fresh, bot_at, "BOT_MANAGER_STATUS",
                       (_field_state("state", (bot_data,), "botState", "status"),),
                       status=_string(_first((bot_data,), "botState", "status"), "bot.status")),
        "loop": _domain(bot_fresh, bot_at, "BOT_MANAGER_STATUS",
                        (_field_state("enabled", (bot_data,), "loopEnabled"),
                         _field_state("state", (bot_data,), "loopState")),
                        enabled=_bool(_first((bot_data,), "loopEnabled"), "loop.enabled"),
                        state=_string(_first((bot_data,), "loopState"), "loop.state")),
        "trade": _domain(bot_fresh, bot_at, "BOT_MANAGER_STATUS",
                         (_field_state("selectedMode", (bot_data, trade_settings), "selectedMode", "mode"),
                          _field_state("dryRun", (bot_data,), "dryRun"),
                          _field_state("autoTradeEnabled", (bot_data,), "autoTradeEnabled"),
                          _field_state("realOrderAllowed", (bot_data,), "realOrderAllowed")),
                         selectedMode=_string(_first((bot_data, trade_settings), "selectedMode", "mode"), "trade.selectedMode"),
                         dryRun=_bool(_first((bot_data,), "dryRun"), "trade.dryRun"),
                         autoTradeEnabled=_bool(_first((bot_data,), "autoTradeEnabled"), "trade.autoTradeEnabled"),
                         realOrderAllowed=real_order_allowed),
        "governance": _domain(gov_fresh, gov_at, "GOVERNANCE_RUNTIME",
                              (_field_state("mode", (gov_data,), "mode"),
                               _field_state("executionEnabled", (gov_data,), "executionEnabled", "execution_enabled"),
                               _field_state("riskProfile", (gov_data,), "riskProfile", "risk_profile")),
                              mode=governance_mode,
                              executionEnabled=governance_execution, riskProfile=governance_risk),
        "emergency": _domain(emergency_fresh, gov_at, "GOVERNANCE_RUNTIME",
                             (_field_state("locked", (gov_data,), "locked", "emergencyLocked", "emergency_stop"),
                              _field_state("state", (gov_data,), "state", "emergencyState", "emergency_state")),
                             locked=emergency_locked, state=emergency_state),
        "execution": _domain(execution_fresh, bot_at, "BOT_MANAGER_STATUS",
                             (_field_state("authoritativeRuntimeState", (bot_data,), "authoritativeRuntimeState"),
                              _field_state("synchronizationState", (bot_data,), "runtimeSynchronizationState", "synchronizationState"),
                              _field_state("pendingOrderState", (bot_data,), "pendingOrderState")),
                             authoritativeRuntimeState=_string(_first((bot_data,), "authoritativeRuntimeState"),
                                                               "execution.authoritativeRuntimeState"),
                             synchronizationState=_string(_first((bot_data,), "runtimeSynchronizationState", "synchronizationState"),
                                                          "execution.synchronizationState"),
                             pendingOrderState=_string(_first((bot_data,), "pendingOrderState"),
                                                       "execution.pendingOrderState"),
                             realOrderAllowed=real_order_allowed),
        "market": _domain(bot_fresh, bot_at, "BOT_MANAGER_STATUS",
                          (_field_state("activeSymbol", (bot_data,), "activeSymbol"),
                           _field_state("marketReady", (bot_data,), "marketReady"),
                           _field_state("marketStale", (bot_data,), "marketStale"),
                           _field_state("selectionMode", (bot_data,), "selectionMode"),
                           _field_state("selectionSource", (auto_market,), "selectionSource"),
                           _field_state("amsRuntimeState", (auto_market,), "amsRuntimeState", "runtimeState"),
                           _field_state("safeSwitchState", (auto_market,), "safeSwitchState")),
                          activeSymbol=active_symbol,
                          marketReady=_bool(_first((bot_data,), "marketReady"), "market.marketReady"),
                          marketStale=_bool(_first((bot_data,), "marketStale"), "market.marketStale"),
                          lastUpdate=_timestamp(_first((bot_data,), "last_update", "lastUpdate"), field="market.lastUpdate"),
                          selectionMode=_string(_first((bot_data,), "selectionMode"), "market.selectionMode"),
                          selectionSource=_string(_first((auto_market,), "selectionSource"), "market.selectionSource"),
                          amsRuntimeState=_string(_first((auto_market,), "amsRuntimeState", "runtimeState"), "market.amsRuntimeState"),
                          selectionCycleId=_string(_first((auto_market,), "selectionCycleId", "cycleId"), "market.selectionCycleId"),
                          safeSwitchState=_string(_first((auto_market,), "safeSwitchState"), "market.safeSwitchState"),
                          suitabilityEvidenceState=_string(_first((auto_market,), "suitabilityEvidenceState"),
                                                           "market.suitabilityEvidenceState")),
        "decision": _domain(
                            bot_fresh,
                            _timestamp(_first((trading_decision,), "evaluatedAt"), field="decision.evaluatedAt") or bot_at,
                            "BOT_MANAGER_STATUS",
                            (_field_state("status", (trading_decision,), "status", "decision"),
                             _field_state("evaluatedAt", (trading_decision,), "evaluatedAt")),
                            status=_string(_first((trading_decision,), "status", "decision"), "decision.status"),
                            state=_string(_first((trading_decision,), "state"), "decision.state")),
        "health": _domain(health_fresh, health_at, "BACKEND_HEALTH_PRODUCER",
                          (_field_state("backendStatus", (health_data,), "backendStatus", "status", "health"),
                           _field_state("runtimeHealthy", (health_data,), "runtimeHealthy")),
                          backendStatus=_string(_first((health_data,), "backendStatus", "status", "health"), "health.backendStatus"),
                          runtimeHealthy=_bool(_first((health_data,), "runtimeHealthy"), "health.runtimeHealthy")),
    }

    critical_freshness = [
        money_management.freshness if name == "moneyManagement" else domains[name].freshness
        for name in CRITICAL_DOMAINS
    ]
    all_domain_freshness = [item.freshness for item in domains.values()] + [money_management.freshness]
    overall = (
        Freshness.CONFLICTED
        if Freshness.CONFLICTED in all_domain_freshness
        else max(critical_freshness, key=lambda item: _FRESHNESS_PRIORITY[item])
    )
    try:
        return ReadOnlySupervisorSnapshot(
            capturedAt=captured,
            overallFreshness=overall,
            bot=domains["bot"], loop=domains["loop"], trade=domains["trade"],
            governance=domains["governance"], emergency=domains["emergency"],
            execution=domains["execution"], market=domains["market"],
            decision=domains["decision"], health=domains["health"],
            moneyManagement=money_management,
            warnings=deduplicate_warnings(warnings),
        )
    except ValidationError as exc:
        raise SupervisorBoundaryError(
            SupervisorFailureCode.SCHEMA_INVALID, "mapped snapshot failed schema validation"
        ) from exc
