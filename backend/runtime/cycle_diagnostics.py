"""Observation-only per-step Trading Cycle diagnostics adapter (WORK J / J2).

This module is a pure projection.  It reads canonical runtime facts that have
already been produced elsewhere and re-expresses them for the operator:

- it never participates in strategy, money-management, governance, execution,
  close, settlement or parameter-promotion decisions;
- it never writes any store and owns no state or authority;
- it never invents a value: when canonical evidence is absent the value is
  reported as ``UNKNOWN`` / ``NOT_AVAILABLE`` rather than guessed.

The caller supplies the single aggregate facts already exposed by
``BotManager.get_result`` (``trading_decision``, the raw ``runtime_result`` and
the surrounding ``status`` payload).  ``build_trading_cycle_diagnostics`` then
returns an additive ``tradingCycleDiagnostics`` contract that the dashboard can
render per STEP.

The root blocker is *classified here*, never in the frontend.  The frontend
must not infer a reason from a string.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

SCHEMA_VERSION = 1
STEP_COUNT = 15

SOURCE = "backend.runtime.cycle_diagnostics"


# ---------------------------------------------------------------------------
# Closed vocabularies (contract § 4 / § 6)
# ---------------------------------------------------------------------------


class StepStatus:
    COMPLETED = "COMPLETED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    BYPASSED = "BYPASSED"
    NOT_REACHED = "NOT_REACHED"
    UNKNOWN = "UNKNOWN"


class BlockerType:
    PARAMETER = "PARAMETER"
    MARKET = "MARKET"
    SYSTEM = "SYSTEM"
    MODE = "MODE"
    AUTHORITY = "AUTHORITY"
    UPSTREAM = "UPSTREAM"
    RUNTIME = "RUNTIME"
    DATA = "DATA"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class Actionable:
    YES = "YES"
    NO = "NO"
    CONDITIONAL = "CONDITIONAL"
    UNKNOWN = "UNKNOWN"


# Canonical 15 stages.  Names match ``LIFECYCLE_STAGE_NAMES`` and the frontend
# ``STAGES`` order; the numeric index is the single join key.
STEP_DEFINITIONS = (
    {"index": 0, "key": "parameter", "name": "Parameter Context"},
    {"index": 1, "key": "marketSelection", "name": "Market Selection"},
    {"index": 2, "key": "marketData", "name": "Market Data"},
    {"index": 3, "key": "featureBuilder", "name": "Feature Builder"},
    {"index": 4, "key": "microEdgeStrategy", "name": "Micro Edge Strategy"},
    {"index": 5, "key": "aiDecision", "name": "AI Decision / Review"},
    {"index": 6, "key": "moneyManagement", "name": "Money Management"},
    {"index": 7, "key": "governance", "name": "Governance"},
    {"index": 8, "key": "execution", "name": "Execution"},
    {"index": 9, "key": "position", "name": "Position"},
    {"index": 10, "key": "exitMonitoring", "name": "Exit Monitoring"},
    {"index": 11, "key": "settlement", "name": "Settlement / Exit Execution"},
    {"index": 12, "key": "positionClosed", "name": "Position Closed"},
    {"index": 13, "key": "performanceRecord", "name": "Trade / Parameter Performance Record"},
    {"index": 14, "key": "readyForNext", "name": "Ready for Next Trade"},
)

# The blockingStage vocabulary is owned by ``build_trading_decision_snapshot``.
# BOT_STOPPED (OPERATION) is intentionally absent: it is a cycle-external state
# and must not be reported as a Parameter Context failure (contract § 5).
BLOCKING_STAGE_TO_STEP = {
    "MARKET": 2,
    "PYTHON STRATEGY": 4,
    "MONEY MANAGEMENT": 6,
    "GOVERNANCE": 7,
    "EXECUTION": 8,
}

# entryReadiness condition code -> blocker class.  Values are canonical codes
# emitted by ``MicrostructureEdgeStrategy.build_entry_readiness``.
_CONDITION_BLOCKER_TYPE = {
    "MARKET_SPREAD_SAFETY": BlockerType.MARKET,
    "SPREAD": BlockerType.MARKET,
    "SPREAD_VOLATILITY": BlockerType.MARKET,
    "LIQUIDITY_SAFETY": BlockerType.MARKET,
    "LIQUIDITY_QUALITY": BlockerType.MARKET,
    "LIQUIDITY_VOLUME": BlockerType.MARKET,
    "ABSORPTION": BlockerType.MARKET,
    "STAGNANT_FLOW": BlockerType.MARKET,
    "FAKE_PRESSURE": BlockerType.MARKET,
    "COMPOSITE_SCORE": BlockerType.PARAMETER,
    "EDGE": BlockerType.PARAMETER,
    "CONFIDENCE": BlockerType.PARAMETER,
    "MOMENTUM": BlockerType.PARAMETER,
    "PRESSURE_ALIGNMENT": BlockerType.PARAMETER,
    "DIRECTION_CONSISTENCY": BlockerType.PARAMETER,
}

# suppressionReason -> entryReadiness condition code (mirrors strategy mapping).
_SUPPRESSION_TO_CONDITION = {
    "ABNORMAL_SPREAD": "SPREAD",
    "SPREAD_VOLATILITY": "SPREAD_VOLATILITY",
    "LIQUIDITY_DETERIORATION": "LIQUIDITY_QUALITY",
    "LIQUIDITY_INSTABILITY": "LIQUIDITY_SAFETY",
    "MOMENTUM_WARMUP": "MOMENTUM_WARMUP",
    "CONFLICTING_MOMENTUM": "MOMENTUM",
    "DIRECTION_CONFLICT": "DIRECTION_CONSISTENCY",
    "DIRECTION_NOT_CONFIRMED": "DIRECTION_CONSISTENCY",
    "WEAK_EDGE": "EDGE",
    "LOW_CONFIDENCE": "CONFIDENCE",
    "LOW_COMPOSITE_SCORE": "COMPOSITE_SCORE",
    "ENTRY_THRESHOLD_NOT_MET": "COMPOSITE_SCORE",
}

# condition code -> canonical editable parameter key (registry metadata).
_CONDITION_PARAMETER = {
    "COMPOSITE_SCORE": "minimumCompositeScore",
    "EDGE": "minimumCompositeScore",
    "CONFIDENCE": "minimumConfidence",
    "SPREAD": "maximumStrategySpreadPct",
    "SPREAD_VOLATILITY": "maximumStrategySpreadPct",
    "LIQUIDITY_VOLUME": "liquidityQualityPercentile",
    "LIQUIDITY_QUALITY": "liquidityQualityPercentile",
    "MOMENTUM": "momentumWindowSeconds",
    "MOMENTUM_WARMUP": "momentumMinimumWarmupSeconds",
    "ABSORPTION": "absorptionVolumePercentile",
}

# blocker class -> whether the operator can change it.  ACTIONABLE=YES means
# "operator-changeable", NOT "recommended to change" (contract § 6).
_BLOCKER_ACTIONABLE = {
    BlockerType.PARAMETER: Actionable.YES,
    BlockerType.MARKET: Actionable.NO,
    BlockerType.SYSTEM: Actionable.NO,
    BlockerType.MODE: Actionable.CONDITIONAL,
    BlockerType.AUTHORITY: Actionable.CONDITIONAL,
    BlockerType.UPSTREAM: Actionable.NO,
    BlockerType.RUNTIME: Actionable.NO,
    BlockerType.DATA: Actionable.CONDITIONAL,
    BlockerType.NONE: Actionable.NO,
    BlockerType.UNKNOWN: Actionable.UNKNOWN,
}

_PARAMETER_SETTINGS_ROUTE = "/parameter-settings"

_NOT_AVAILABLE = "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_bool_or_none(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _actionable_for(blocker_type: Optional[str]) -> str:
    return _BLOCKER_ACTIONABLE.get(blocker_type, Actionable.UNKNOWN)


def _strategy_state(runtime_result: Optional[Mapping[str, Any]]) -> dict:
    output = _mapping(runtime_result).get("strategyOutput")
    if not isinstance(output, Mapping):
        return {}
    return _mapping(output.get("strategy"))


def resolve_evaluation_provenance(
    runtime_result: Optional[Mapping[str, Any]], current_cycle_id: Optional[str] = None
) -> dict:
    """Use raw evaluation identity, never the aggregate snapshot's cycle stamp.

    Legacy producers do not emit a cycle ID. Timestamps establish freshness,
    not cycle membership, so those evaluations deliberately remain UNKNOWN.
    """
    strategy = _strategy_state(runtime_result)
    readiness = _mapping(strategy.get("entryReadiness"))
    cycle_id = _clean_str(readiness.get("cycleId"))
    evaluated_at = readiness.get("evaluatedAt")
    if evaluated_at is None:
        evaluated_at = strategy.get("timestamp")
    state = "UNKNOWN"
    if cycle_id is not None and current_cycle_id is not None:
        state = "CURRENT" if cycle_id == current_cycle_id else "HISTORICAL"
    return {
        "currentCycleId": current_cycle_id,
        "evaluationCycleId": cycle_id,
        "provenance": state,
        "evaluatedAt": evaluated_at,
        "sourceUpdatedAt": strategy.get("timestamp"),
    }


def _entry_readiness(decision: Mapping[str, Any], strategy: Mapping[str, Any]) -> dict:
    # Raw strategy evidence has not been decorated with aggregate cycle/time.
    if isinstance(strategy.get("entryReadiness"), Mapping):
        return dict(strategy["entryReadiness"])
    return _mapping(decision.get("entryReadiness"))


def _condition_comparison(condition: Mapping[str, Any]) -> dict:
    current = condition.get("currentValue")
    expected = condition.get("expected")
    threshold = condition.get("threshold")
    operator = condition.get("operator")
    value_type, comparison = "UNKNOWN", "NOT_AVAILABLE"
    if isinstance(expected, bool):
        value_type = "BOOLEAN"
        if isinstance(current, bool):
            comparison = "PASS" if current == expected else "FAIL"
    elif expected is not None:
        value_type = "ENUM"
        if current is not None:
            comparison = "PASS" if current == expected else "FAIL"
    elif operator in {"<=", ">="} and _numeric(threshold) is not None:
        value_type = "NUMERIC_THRESHOLD"
        if _numeric(current) is not None:
            passed = current <= threshold if operator == "<=" else current >= threshold
            comparison = "PASS" if passed else "FAIL"
    elif operator is not None:
        value_type = "PREDICATE"
        comparison = condition.get("status") or "NOT_AVAILABLE"
    if condition.get("sourceStatus") == "MISSING":
        comparison = "NOT_AVAILABLE"
    return {"valueType": value_type, "comparison": comparison,
            "required": expected if expected is not None else threshold}


def _conditions_by_code(entry_readiness: Mapping[str, Any]) -> dict:
    result = {}
    for condition in entry_readiness.get("conditions") or []:
        if isinstance(condition, Mapping) and condition.get("code"):
            result[str(condition["code"])] = dict(condition)
    return result


def _blocking_condition_code(
    entry_readiness: Mapping[str, Any], blocking_reason: Optional[str]
) -> Optional[str]:
    explicit = _clean_str(entry_readiness.get("blockingCondition"))
    if explicit:
        return explicit
    reason = _clean_str(blocking_reason)
    if reason in _SUPPRESSION_TO_CONDITION:
        return _SUPPRESSION_TO_CONDITION[reason]
    # Last resort: the first FAILing condition reported by the strategy.
    for condition in entry_readiness.get("conditions") or []:
        if isinstance(condition, Mapping) and condition.get("status") == "FAIL":
            return _clean_str(condition.get("code"))
    return None


def _classify_blocker_type(blocker_type: Optional[str]) -> str:
    if blocker_type in {
        BlockerType.PARAMETER,
        BlockerType.MARKET,
        BlockerType.SYSTEM,
        BlockerType.MODE,
        BlockerType.AUTHORITY,
        BlockerType.UPSTREAM,
        BlockerType.RUNTIME,
        BlockerType.DATA,
        BlockerType.NONE,
    }:
        return blocker_type
    return BlockerType.UNKNOWN


def _epoch(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.replace(".", "", 1).isdigit():
            try:
                return float(text)
            except ValueError:
                return None
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def _freshness(evaluated_at: Any, source_timestamp: Any) -> dict:
    evaluated = _epoch(evaluated_at)
    source = _epoch(source_timestamp)
    if evaluated is None or source is None:
        return {"state": "UNKNOWN", "ageSeconds": None, "evaluatedAt": source_timestamp}
    age = max(0.0, evaluated - source)
    return {
        "state": "FRESH" if age <= 5 else "STALE",
        "ageSeconds": round(age, 3),
        "evaluatedAt": source_timestamp,
    }


def _parameter_location(related: list) -> Optional[dict]:
    if not related:
        return None
    # No stable per-parameter anchor exists today, so only the route is exposed.
    return {"route": _PARAMETER_SETTINGS_ROUTE, "anchor": None}


def _parameter_entry(
    *,
    key: str,
    current_setting: Any,
    scope: Optional[str],
    relationship: str,
    configured_revision: Any = None,
    effective_revision: Any = None,
) -> dict:
    return {
        "key": key,
        "currentSetting": current_setting,
        "scope": scope,
        "configuredRevision": configured_revision,
        "effectiveRevision": effective_revision,
        "relationship": relationship,
    }


def _risk_related_parameters(context: Mapping[str, Any], scope: Optional[str]) -> list:
    risk_config = _mapping(context.get("risk_config") or context.get("riskConfig"))
    if not risk_config:
        return []
    keys = (
        "risk_percent",
        "position_size",
        "max_drawdown_pct",
        "tp_percent",
        "sl_percent",
        "trailing_stop",
        "trailing_stop_distance_percent",
    )
    related = []
    for key in keys:
        if key in risk_config and risk_config[key] is not None:
            related.append(
                _parameter_entry(
                    key=key,
                    current_setting=risk_config[key],
                    scope=scope,
                    relationship="RISK_CONFIGURATION",
                )
            )
    return related


def _normalized_conditions(entry_readiness: Mapping[str, Any]) -> list:
    normalized = []
    for condition in entry_readiness.get("conditions") or []:
        if not isinstance(condition, Mapping):
            continue
        normalized.append(
            {
                **_condition_comparison(condition),
                "code": condition.get("code"),
                "status": condition.get("status"),
                "currentValue": condition.get("currentValue"),
                "threshold": condition.get("threshold"),
                "operator": condition.get("operator"),
                "expected": condition.get("expected"),
                "delta": condition.get("delta"),
                "sourceStatus": condition.get("sourceStatus"),
                "parameterKey": _CONDITION_PARAMETER.get(
                    _clean_str(condition.get("code"))
                ),
            }
        )
    return normalized


def _condition_related_parameters(
    code: Optional[str],
    condition: Mapping[str, Any],
    scope: Optional[str],
) -> list:
    parameter_key = _CONDITION_PARAMETER.get(code or "")
    if not parameter_key:
        return []
    return [
        _parameter_entry(
            key=parameter_key,
            current_setting=condition.get("threshold"),
            scope=scope,
            relationship="ENTRY_THRESHOLD",
        )
    ]


def _base_status(index: int, current_index: Optional[int], stopped: bool) -> str:
    if stopped:
        return StepStatus.NOT_REACHED
    if current_index is None:
        return StepStatus.UNKNOWN
    if index < current_index:
        return StepStatus.COMPLETED
    if index == current_index:
        return StepStatus.ACTIVE
    return StepStatus.NOT_REACHED


# ---------------------------------------------------------------------------
# root blocker
# ---------------------------------------------------------------------------


def _root_blocker(
    *,
    bot_running: bool,
    blocking_stage: Optional[str],
    blocking_reason: Optional[str],
    entry_readiness: Mapping[str, Any],
    close_state: Mapping[str, Any],
    evaluated_at: Any,
) -> Optional[dict]:
    """Classify the canonical root blocker from already-recorded facts."""

    if not bot_running:
        # BOT_STOPPED is a cycle-external state.  It is surfaced via
        # ``cycleState`` and must not masquerade as a STEP blocker.
        return None

    stage = _clean_str(blocking_stage)
    if stage:
        step = BLOCKING_STAGE_TO_STEP.get(stage.upper())
        if step is None:
            if stage.upper() == "OPERATION":
                return None
            return {
                "step": None,
                "reasonCode": blocking_reason or "UNKNOWN_BLOCK",
                "reasonText": _reason_text(
                    None, blocking_reason or "UNKNOWN_BLOCK", None, None
                ),
                "blockerType": BlockerType.UNKNOWN,
                "source": "tradingDecision.blockingStage",
                "evaluatedAt": evaluated_at,
            }

        if step == 4:
            code = _blocking_condition_code(entry_readiness, blocking_reason)
            condition = _conditions_by_code(entry_readiness).get(code or "", {})
            blocker_type = _classify_blocker_type(
                _CONDITION_BLOCKER_TYPE.get(code or "", BlockerType.UNKNOWN)
            )
            return {
                "step": step,
                "reasonCode": blocking_reason or code or "ENTRY_NOT_ALLOWED",
                "reasonText": _reason_text(
                    4, blocking_reason or code, condition, entry_readiness
                ),
                "blockerType": blocker_type,
                "source": "tradingDecision.entryReadiness",
                "evaluatedAt": evaluated_at,
            }

        blocker_type = {
            2: BlockerType.MARKET,
            6: BlockerType.PARAMETER,
            7: BlockerType.AUTHORITY,
            8: BlockerType.RUNTIME,
        }.get(step, BlockerType.UNKNOWN)
        return {
            "step": step,
            "reasonCode": blocking_reason or "UNKNOWN_BLOCK",
            "reasonText": _reason_text(step, blocking_reason, None, None),
            "blockerType": blocker_type,
            "source": "tradingDecision.blockingStage",
            "evaluatedAt": evaluated_at,
        }

    # No entry blocker: an unconfirmed close (settlement) becomes the root.
    if close_state and close_state.get("confirmed") is not True:
        status = _clean_str(close_state.get("status"))
        if status in {"RECONCILING", "RECONCILIATION_FAILED", "REJECTED", "UNKNOWN"}:
            return {
                "step": 11,
                "reasonCode": close_state.get("reason") or status,
                "reasonText": _reason_text(11, close_state.get("reason") or status, None, None),
                "blockerType": BlockerType.RUNTIME
                if status == "RECONCILING"
                else BlockerType.SYSTEM,
                "source": "tradingDecision.closeState",
                "evaluatedAt": evaluated_at,
            }

    return None


def _reason_text(
    step: Optional[int],
    reason_code: Optional[str],
    condition: Optional[Mapping[str, Any]],
    entry_readiness: Optional[Mapping[str, Any]],
) -> str:
    code = _clean_str(reason_code) or "UNKNOWN"
    if step == 4 and condition:
        current = condition.get("currentValue")
        threshold = condition.get("threshold")
        operator = condition.get("operator")
        condition_code = condition.get("code")
        if condition_code and current is not None:
            if operator and threshold is not None:
                return (
                    f"Micro Edge Strategy blocked entry: {condition_code} "
                    f"is {current}, required {operator} {threshold}"
                )
            return f"Micro Edge Strategy blocked entry: {condition_code} = {current}"
    labels = {
        0: "Parameter Context",
        1: "Market Selection",
        2: "Market Data",
        3: "Feature Builder",
        4: "Micro Edge Strategy",
        5: "AI Decision / Review",
        6: "Money Management",
        7: "Governance",
        8: "Execution",
        9: "Position",
        10: "Exit Monitoring",
        11: "Settlement / Exit Execution",
        12: "Position Closed",
        13: "Trade / Parameter Performance Record",
        14: "Ready for Next Trade",
    }
    label = labels.get(step or -1, "Cycle")
    return f"{label} blocked: {code}"


# ---------------------------------------------------------------------------
# per-step projection
# ---------------------------------------------------------------------------


def _step_details(
    index: int,
    *,
    decision: Mapping[str, Any],
    strategy: Mapping[str, Any],
    entry_readiness: Mapping[str, Any],
    close_state: Mapping[str, Any],
    stages: Mapping[str, Any],
    context: Mapping[str, Any],
    parameter_authority: Mapping[str, Any],
    bot_running: bool,
) -> dict:
    scope = _clean_str(decision.get("mode"))
    mode = scope
    details: dict = {
        "status": None,
        "reasonCode": None,
        "reasonText": None,
        "current": None,
        "required": None,
        "comparison": None,
        "blockerType": BlockerType.NONE,
        "actionable": Actionable.NO,
        "relatedParameters": [],
        "parameterLocation": None,
        "nextCondition": None,
        "nextStep": index + 1 if index < STEP_COUNT - 1 else None,
        "source": None,
        "extra": {},
    }

    if index == 0:
        if parameter_authority:
            configured = parameter_authority.get("configuredRevision")
            effective = parameter_authority.get("effectiveRevision")
            match = (
                configured is not None
                and effective is not None
                and configured == effective
            )
            details.update(
                {
                    "current": {
                        "effectiveRevision": effective,
                        "configuredRevision": configured,
                        "parameterSetId": parameter_authority.get("parameterSetId"),
                        "scope": parameter_authority.get("canonicalScope")
                        or parameter_authority.get("scope"),
                    },
                    "required": "EFFECTIVE_REVISION_MATCHES_CONFIGURED",
                    "comparison": "MATCH" if match else "MISMATCH",
                    "reasonCode": (
                        "PARAMETER_CONTEXT_READY"
                        if match
                        else "EFFECTIVE_REVISION_BEHIND_CONFIGURED"
                    ),
                    "reasonText": (
                        "Configured and effective parameter revisions match."
                        if match
                        else "Effective parameter revision is behind the "
                        "configured revision."
                    ),
                    "blockerType": BlockerType.NONE
                    if match
                    else BlockerType.PARAMETER,
                    "actionable": Actionable.NO
                    if match
                    else Actionable.YES,
                    "relatedParameters": _risk_related_parameters(context, scope),
                    "nextCondition": "PARAMETER_CONTEXT_RESOLVED",
                    "source": "runtimeResult.strategyOutput.strategy.parameterAuthority",
                }
            )
        else:
            details.update(
                {
                    "current": _NOT_AVAILABLE,
                    "required": "PARAMETER_AUTHORITY_AVAILABLE",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "PARAMETER_AUTHORITY_NOT_AVAILABLE",
                    "reasonText": "Canonical parameter authority is not exposed "
                    "for this cycle.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "relatedParameters": _risk_related_parameters(context, scope),
                    "nextCondition": "PARAMETER_CONTEXT_RESOLVED",
                    "source": "runtimeResult.strategyOutput.strategy.parameterAuthority",
                }
            )

    elif index == 1:
        ams = _mapping(context.get("autoMarketSelection") or context.get("auto_market_selection"))
        symbol = _clean_str(
            decision.get("selectedSymbol")
            or context.get("activeSymbol")
            or context.get("symbol")
        )
        selection_mode = _clean_str(
            context.get("selectionMode") or ams.get("selectionMode")
        )
        selected = symbol is not None
        details.update(
            {
                "current": symbol or _NOT_AVAILABLE,
                "required": "SYMBOL_SELECTED",
                "comparison": "PASS" if selected else "NOT_AVAILABLE",
                "reasonCode": "SYMBOL_SELECTED" if selected else "SYMBOL_NOT_SELECTED",
                "reasonText": (
                    f"Active symbol {symbol}." if selected
                    else "No active symbol is exposed for this cycle."
                ),
                "blockerType": BlockerType.NONE if selected else BlockerType.UNKNOWN,
                "actionable": Actionable.CONDITIONAL,
                "relatedParameters": (
                    [
                        _parameter_entry(
                            key="selectionMode",
                            current_setting=selection_mode,
                            scope=mode,
                            relationship="MARKET_SELECTION_MODE",
                        )
                    ]
                    if selection_mode
                    else []
                ),
                "nextCondition": "SYMBOL_LOCKED",
                "source": "tradingDecision.selectedSymbol",
            }
        )
        details["extra"] = {
            "selectionMode": selection_mode,
            "switchState": context.get("symbolSwitchState"),
        }

    elif index == 2:
        market = _mapping(stages.get("market"))
        reached = market.get("reached") is True
        stale = decision.get("stale") is True
        ready = reached and not stale
        if ready:
            current = "READY"
        elif stale:
            current = "STALE"
        else:
            current = "MISSING"
        details.update(
            {
                "current": current,
                "required": "READY",
                "comparison": "PASS" if ready else "BLOCK",
                "reasonCode": "MARKET_DATA_READY" if ready else "MARKET_DATA_MISSING_OR_STALE",
                "reasonText": (
                    "Market data is present and fresh."
                    if ready
                    else "Market data is missing or stale."
                ),
                "blockerType": BlockerType.NONE if ready else BlockerType.MARKET,
                "actionable": Actionable.NO if ready else Actionable.CONDITIONAL,
                "nextCondition": "MARKET_DATA_READY",
                "source": "tradingDecision.stages.market",
            }
        )
        details["extra"] = {"reason": market.get("reason")}

    elif index == 3:
        reached = _mapping(stages.get("pythonStrategy")).get("reached") is True
        feature_contract = _clean_str(strategy.get("featureContract"))
        available = reached and feature_contract is not None
        details.update(
            {
                "current": feature_contract or _NOT_AVAILABLE,
                "required": "FEATURE_CONTRACT_ACTIVE",
                "comparison": "PASS" if available else "NOT_AVAILABLE",
                "reasonCode": (
                    "FEATURE_CONTRACT_ACTIVE" if available
                    else "FEATURE_EVIDENCE_NOT_EXPOSED"
                ),
                "reasonText": (
                    f"Feature contract {feature_contract} is active."
                    if available
                    else "Feature-builder evidence is not exposed for this cycle."
                ),
                "blockerType": BlockerType.NONE if available else BlockerType.UNKNOWN,
                "actionable": Actionable.NO,
                "nextCondition": "FEATURES_BUILT",
                "source": "runtimeResult.strategyOutput.strategy.featureContract",
            }
        )

    elif index == 4:
        strategy_reason = entry_readiness.get("suppressionReason") or strategy.get("suppressionReason")
        conditions = _normalized_conditions(entry_readiness)
        code = _blocking_condition_code(entry_readiness, strategy_reason)
        condition = _conditions_by_code(entry_readiness).get(code or "", {})
        allowed = entry_readiness.get("executionAllowed")
        if not conditions:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "ENTRY_READINESS_AVAILABLE",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "ENTRY_READINESS_NOT_EXPOSED",
                    "reasonText": "Micro Edge entry-readiness evidence is not "
                    "exposed for this cycle.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "ENTRY_ALLOWED",
                    "source": "tradingDecision.entryReadiness",
                }
            )
        else:
            blocker_type = _classify_blocker_type(
                _CONDITION_BLOCKER_TYPE.get(code or "", BlockerType.UNKNOWN)
            )
            if allowed is True:
                blocker_type = BlockerType.NONE
            comparison = (
                "PASS"
                if allowed is True
                else "BLOCK"
                if code
                else "NOT_AVAILABLE"
            )
            details.update(
                {
                    "status": (
                        StepStatus.ACTIVE if allowed is True else StepStatus.BLOCKED
                    ),
                    "current": {
                        "edgeScore": strategy.get("edge", entry_readiness.get("edgeScore")),
                        "confidence": entry_readiness.get("confidence"),
                        "candidateDirection": entry_readiness.get("candidateDirection"),
                        "blockingCondition": code,
                        "blockingConditionCurrent": condition.get("currentValue"),
                    },
                    "required": {
                        "minimumCompositeScore": strategy.get("minimumCompositeScore"),
                        "minimumConfidence": strategy.get("minimumConfidence"),
                        "conditionThreshold": condition.get("threshold"),
                        "conditionOperator": condition.get("operator"),
                        "conditionExpected": condition.get("expected"),
                    },
                    "comparison": comparison,
                    "reasonCode": strategy_reason
                    or code
                    or "ENTRY_ALLOWED",
                    "reasonText": (
                        "Micro Edge Strategy allows entry."
                        if allowed is True
                        else _reason_text(4, strategy_reason or code, condition, entry_readiness)
                    ),
                    "blockerType": blocker_type,
                    "actionable": _actionable_for(blocker_type),
                    "relatedParameters": _condition_related_parameters(
                        code, condition, scope
                    ),
                    "nextCondition": "ENTRY_ALLOWED",
                    "source": "tradingDecision.entryReadiness",
                }
            )
            details["extra"] = {"conditions": conditions}
            predicate = _condition_comparison(condition)
            details["valueType"] = predicate["valueType"]
            if predicate["valueType"] == "BOOLEAN":
                details["comparison"] = predicate["comparison"]

    elif index == 5:
        ai = _mapping(stages.get("aiReview"))
        mode_off = (
            _clean_str(ai.get("mode")) == "OFF"
            or _clean_str(ai.get("implementationStatus")) == "NOT_INSTALLED"
            or _clean_str(ai.get("decision")) == "NOT_REQUIRED"
        )
        details.update(
            {
                "status": StepStatus.BYPASSED if mode_off else None,
                "current": ai.get("decision") or "NOT_REQUIRED",
                "required": "NOT_REQUIRED",
                "comparison": "BYPASSED" if mode_off else "NOT_AVAILABLE",
                "reasonCode": "TRADING_AI_OFF" if mode_off else "AI_STATE_UNKNOWN",
                "reasonText": (
                    "Trading AI is OFF / NOT_INSTALLED; review is bypassed and "
                    "not required for this cycle."
                    if mode_off
                    else "AI review state is not exposed for this cycle."
                ),
                "blockerType": BlockerType.MODE,
                "actionable": Actionable.CONDITIONAL,
                "relatedParameters": [
                    _parameter_entry(
                        key="tradingAiMode",
                        current_setting=ai.get("mode") or "OFF",
                        scope=mode,
                        relationship="AI_REVIEW_MODE",
                    )
                ],
                "nextCondition": "AI_REVIEW_COMPLETE_OR_BYPASSED",
                "source": "tradingDecision.stages.aiReview",
            }
        )

    elif index == 6:
        mm = _mapping(stages.get("moneyManagement"))
        reached = mm.get("reached") is True
        passed = reached and _clean_str(mm.get("status")) == "PASS"
        details.update(
            {
                "current": mm.get("status") or _NOT_AVAILABLE,
                "required": "ALLOW",
                "comparison": "PASS" if passed else "BLOCK" if reached else "NOT_EVALUATED",
                "reasonCode": (
                    "MONEY_MANAGEMENT_ALLOWED"
                    if passed
                    else _clean_str(mm.get("reason")) or "MONEY_MANAGEMENT_NOT_EVALUATED"
                ),
                "reasonText": (
                    "Money management allows the trade."
                    if passed
                    else f"Money management status: {mm.get('status') or 'NOT_EVALUATED'}."
                ),
                "blockerType": BlockerType.NONE if passed else BlockerType.PARAMETER,
                "actionable": Actionable.NO if passed else Actionable.YES,
                "nextCondition": "RISK_APPROVED",
                "source": "tradingDecision.stages.moneyManagement",
            }
        )
        details["extra"] = {
            "suggestedQuantity": mm.get("suggestedQuantity"),
            "approvedQuantity": mm.get("approvedQuantity"),
            "riskAmount": mm.get("riskAmount"),
        }

    elif index == 7:
        governance = _mapping(stages.get("governance"))
        reached = governance.get("reached") is True
        passed = reached and _clean_str(governance.get("status")) == "PASS"
        details.update(
            {
                "current": governance.get("status") or _NOT_AVAILABLE,
                "required": "ALLOWED",
                "comparison": "PASS" if passed else "BLOCK" if reached else "NOT_EVALUATED",
                "reasonCode": (
                    "GOVERNANCE_ALLOWED"
                    if passed
                    else _clean_str(governance.get("reason")) or "GOVERNANCE_NOT_EVALUATED"
                ),
                "reasonText": (
                    "Governance allows the trade."
                    if passed
                    else f"Governance status: {governance.get('status') or 'NOT_EVALUATED'}."
                ),
                "blockerType": BlockerType.NONE if passed else BlockerType.AUTHORITY,
                "actionable": Actionable.NO if passed else Actionable.CONDITIONAL,
                "nextCondition": "GOVERNANCE_APPROVED",
                "source": "tradingDecision.stages.governance",
            }
        )
        details["extra"] = {
            "executionAuthority": governance.get("executionAuthority"),
            "emergencyState": governance.get("emergencyState"),
        }

    elif index == 8:
        execution = _mapping(stages.get("execution"))
        order_state = _clean_str(execution.get("orderState"))
        status = _clean_str(execution.get("status"))
        details.update(
            {
                "current": status or order_state or _NOT_AVAILABLE,
                "required": "ORDER_ACKNOWLEDGED",
                "comparison": "IN_PROGRESS"
                if status == "WAITING FOR FILL"
                else "NOT_AVAILABLE",
                "reasonCode": _clean_str(execution.get("reason"))
                or "EXECUTION_NOT_ATTEMPTED",
                "reasonText": f"Execution status: {status or 'UNKNOWN'}.",
                "blockerType": BlockerType.RUNTIME,
                "actionable": Actionable.NO,
                "nextCondition": "ORDER_ACKNOWLEDGED",
                "source": "tradingDecision.stages.execution",
            }
        )
        details["extra"] = {
            "orderState": order_state,
            "orderSide": execution.get("orderSide"),
            "orderType": execution.get("orderType"),
        }

    elif index == 9:
        execution = _mapping(stages.get("execution"))
        position_state = _clean_str(execution.get("positionState")) or _NOT_AVAILABLE
        opened = position_state == "OPEN"
        details.update(
            {
                "status": StepStatus.ACTIVE if opened else None,
                "current": position_state,
                "required": "POSITION_MANAGED",
                "comparison": "OPEN" if opened else "FLAT",
                "reasonCode": "POSITION_OPEN" if opened else "NO_OPEN_POSITION",
                "reasonText": (
                    "A position is open and being managed."
                    if opened
                    else "No position is open."
                ),
                "blockerType": BlockerType.NONE,
                "actionable": Actionable.CONDITIONAL if opened else Actionable.NO,
                "nextCondition": "POSITION_CLOSED",
                "source": "tradingDecision.stages.execution.positionState",
            }
        )

    elif index == 10:
        if close_state.get("confirmed") is True:
            details.update(
                {
                    "status": StepStatus.COMPLETED,
                    "current": "COMPLETE",
                    "required": "EXIT_DECISION",
                    "comparison": "PASS",
                    "reasonCode": "POSITION_CLOSED",
                    "reasonText": "Exit monitoring completed with the position close.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "EXIT_DECISION",
                    "source": "tradingDecision.closeState",
                }
            )
        elif _clean_str(close_state.get("status")) in {
            "RECONCILING",
            "RECONCILIATION_FAILED",
        }:
            details.update(
                {
                    "status": StepStatus.ACTIVE,
                    "current": _clean_str(close_state.get("status")),
                    "required": "CLOSE_CONFIRMED",
                    "comparison": "IN_PROGRESS",
                    "reasonCode": _clean_str(close_state.get("reason"))
                    or "CLOSE_PENDING_RECONCILIATION",
                    "reasonText": "Exit close is pending reconciliation.",
                    "blockerType": BlockerType.RUNTIME,
                    "actionable": Actionable.NO,
                    "nextCondition": "EXIT_DECISION",
                    "source": "tradingDecision.closeState",
                }
            )
        elif _mapping(stages.get("execution")).get("positionState") == "OPEN":
            details.update(
                {
                    "status": StepStatus.ACTIVE,
                    "current": "MONITORING",
                    "required": "EXIT_DECISION",
                    "comparison": "IN_PROGRESS",
                    "reasonCode": "EXIT_MONITORING_ACTIVE",
                    "reasonText": "Exit conditions are being monitored while the "
                    "position is open.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "EXIT_DECISION",
                    "source": "tradingDecision.stages.execution.positionState",
                }
            )
        else:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "EXIT_DECISION",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "EXIT_STATE_NOT_EXPOSED",
                    "reasonText": "No canonical exit-monitoring state is exposed.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "EXIT_DECISION",
                    "source": "tradingDecision.closeState",
                }
            )

    elif index == 11:
        status = _clean_str(close_state.get("status"))
        confirmed = close_state.get("confirmed") is True
        if confirmed:
            details.update(
                {
                    "status": StepStatus.COMPLETED,
                    "current": "CLOSE_CONFIRMED",
                    "required": "CLOSE_CONFIRMED",
                    "comparison": "PASS",
                    "reasonCode": "EXCHANGE_CLOSE_CONFIRMED",
                    "reasonText": "Exit execution is confirmed closed.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "CLOSE_CONFIRMED",
                    "source": "tradingDecision.closeState",
                }
            )
        elif status:
            details.update(
                {
                    "current": status,
                    "required": "CLOSE_CONFIRMED",
                    "comparison": "BLOCK",
                    "reasonCode": _clean_str(close_state.get("reason")) or status,
                    "reasonText": f"Settlement status: {status}.",
                    "blockerType": BlockerType.SYSTEM,
                    "actionable": Actionable.NO,
                    "nextCondition": "CLOSE_CONFIRMED",
                    "source": "tradingDecision.closeState",
                }
            )
        else:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "CLOSE_CONFIRMED",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "CLOSE_STATE_NOT_EXPOSED",
                    "reasonText": "No canonical close state is exposed.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "CLOSE_CONFIRMED",
                    "source": "tradingDecision.closeState",
                }
            )
        details["extra"] = {
            "reconciliationAttempts": close_state.get("reconciliationAttempts"),
            "orderId": close_state.get("order_id"),
        }

    elif index == 12:
        confirmed = close_state.get("confirmed") is True
        position_state = _clean_str(close_state.get("positionState"))
        if confirmed:
            details.update(
                {
                    "status": StepStatus.COMPLETED,
                    "current": "CLOSED",
                    "required": "FLAT_POSITION",
                    "comparison": "PASS",
                    "reasonCode": "POSITION_CLOSED",
                    "reasonText": "The exchange reports a flat position.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "POSITION_CLOSED",
                    "source": "tradingDecision.closeState",
                }
            )
        elif _clean_str(close_state.get("status")):
            details.update(
                {
                    "current": position_state or _clean_str(close_state.get("status")),
                    "required": "FLAT_POSITION",
                    "comparison": "BLOCK",
                    "reasonCode": _clean_str(close_state.get("reason"))
                    or "POSITION_NOT_FLAT",
                    "reasonText": "The position is not yet confirmed flat.",
                    "blockerType": BlockerType.SYSTEM,
                    "actionable": Actionable.NO,
                    "nextCondition": "POSITION_CLOSED",
                    "source": "tradingDecision.closeState",
                }
            )
        else:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "FLAT_POSITION",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "POSITION_CLOSE_STATE_NOT_EXPOSED",
                    "reasonText": "No canonical position-close state is exposed.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "POSITION_CLOSED",
                    "source": "tradingDecision.closeState",
                }
            )

    elif index == 13:
        record = _mapping(
            context.get("performanceRecord")
            or context.get("parameterPerformance")
            or context.get("lastPerformanceRecord")
        )
        if record:
            details.update(
                {
                    "status": StepStatus.COMPLETED,
                    "current": {
                        "tradeId": record.get("tradeId"),
                        "effectiveRevision": record.get("effectiveRevision"),
                        "realizedPnl": record.get("realizedPnl"),
                    },
                    "required": "PERFORMANCE_RECORD_WRITTEN",
                    "comparison": "PASS",
                    "reasonCode": "PERFORMANCE_RECORD_WRITTEN",
                    "reasonText": "The trade performance record is available.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "PERFORMANCE_RECORD_WRITTEN",
                    "source": "status.performanceRecord",
                }
            )
        else:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "PERFORMANCE_RECORD_WRITTEN",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "PERFORMANCE_RECORD_NOT_EXPOSED",
                    "reasonText": "No canonical trade performance record is "
                    "exposed for this cycle.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "PERFORMANCE_RECORD_WRITTEN",
                    "source": "status.performanceRecord",
                }
            )

    elif index == 14:
        confirmed = close_state.get("confirmed") is True
        if confirmed:
            details.update(
                {
                    "status": StepStatus.ACTIVE,
                    "current": "READY",
                    "required": "FLAT_AND_RECONCILED",
                    "comparison": "PASS",
                    "reasonCode": "READY_FOR_NEXT_TRADE",
                    "reasonText": "The position is flat and reconciled; the cycle "
                    "can start a new trade.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": None,
                    "source": "tradingDecision.closeState",
                }
            )
        elif _mapping(stages.get("execution")).get("positionState") == "OPEN":
            details.update(
                {
                    "current": "TRADE_OPEN",
                    "required": "FLAT_AND_RECONCILED",
                    "comparison": "WAITING",
                    "reasonCode": "WAITING_FOR_POSITION_CLOSE",
                    "reasonText": "A trade is still open; the next cycle waits.",
                    "blockerType": BlockerType.NONE,
                    "actionable": Actionable.NO,
                    "nextCondition": "FLAT_AND_RECONCILED",
                    "source": "tradingDecision.stages.execution.positionState",
                }
            )
        else:
            details.update(
                {
                    "status": StepStatus.UNKNOWN,
                    "current": _NOT_AVAILABLE,
                    "required": "FLAT_AND_RECONCILED",
                    "comparison": "NOT_AVAILABLE",
                    "reasonCode": "CYCLE_READINESS_NOT_EXPOSED",
                    "reasonText": "Cycle readiness is not exposed for this cycle.",
                    "blockerType": BlockerType.UNKNOWN,
                    "actionable": Actionable.UNKNOWN,
                    "nextCondition": "FLAT_AND_RECONCILED",
                    "source": "tradingDecision.closeState",
                }
            )

    if not bot_running:
        # Cycle-external stop: retain the canonical reason, drop false detail.
        details.update(
            {
                "status": StepStatus.NOT_REACHED,
                "reasonCode": "BOT_STOPPED",
                "reasonText": "The bot is stopped; this STEP was not reached.",
                "blockerType": BlockerType.MODE,
                "actionable": Actionable.CONDITIONAL,
            }
        )

    return details


# ---------------------------------------------------------------------------
# public adapter
# ---------------------------------------------------------------------------


def build_trading_cycle_diagnostics(
    trading_decision: Optional[Mapping[str, Any]] = None,
    *,
    runtime_result: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
    evaluated_at: Any = None,
) -> dict:
    """Return the additive ``tradingCycleDiagnostics`` contract.

    All arguments are optional and observation-only.  Exactly fifteen STEP
    entries are always returned, indexed 0..14.
    """

    decision = _mapping(trading_decision)
    runtime = _mapping(runtime_result)
    ctx = _mapping(context)
    strategy = _strategy_state(runtime)
    entry_readiness = _entry_readiness(decision, strategy)
    close_state = _mapping(decision.get("closeState"))
    stages = _mapping(decision.get("stages"))
    parameter_authority = _mapping(strategy.get("parameterAuthority"))

    if evaluated_at is None:
        evaluated_at = decision.get("timestamp")
        if evaluated_at is None:
            evaluated_at = ctx.get("timestamp")

    bot = _mapping(ctx.get("bot"))
    running_flag = _as_bool_or_none(bot.get("running"))
    if running_flag is None:
        status_text = _clean_str(ctx.get("status"))
        if status_text in {"RUNNING", "STOPPED"}:
            running_flag = status_text == "RUNNING"
    if running_flag is None:
        current_activity = _clean_str(decision.get("currentActivity"))
        running_flag = current_activity != "BOT_STOPPED"
    bot_running = bool(running_flag)

    current_index = decision.get("currentStageIndex")
    if isinstance(current_index, bool) or not isinstance(current_index, int):
        current_index = None

    runtime_state = _mapping(_mapping(ctx.get("runtime_health")).get("runtimeEngine"))
    provenance = resolve_evaluation_provenance(runtime, decision.get("cycleId"))
    current_evaluation = provenance["provenance"] == "CURRENT"
    blocking_stage = _clean_str(decision.get("blockingStage"))
    strategy_blocked = (blocking_stage or "").upper() == "PYTHON STRATEGY"
    # Only a proven current strategy evaluation may explain a strategy root.
    # Other blockers retain their own canonical current-state dependencies.
    if not current_evaluation and strategy_blocked:
        blocking_stage = None
    root = _root_blocker(
        bot_running=bot_running,
        blocking_stage=blocking_stage,
        blocking_reason=decision.get("blockingReason"),
        entry_readiness=entry_readiness,
        close_state=close_state,
        evaluated_at=evaluated_at,
    )
    if root and root.get("step") == 4:
        root.update(provenance)
    root_step = (
        root.get("step")
        if isinstance(root, dict) and isinstance(root.get("step"), int)
        else None
    )

    if not bot_running:
        cycle_state = "BOT_STOPPED"
    elif current_index == 14:
        cycle_state = "CLOSE_CONFIRMED"
    elif root is not None:
        cycle_state = "BLOCKED"
    elif _mapping(stages.get("execution")).get("positionState") == "OPEN":
        cycle_state = "POSITION_OPEN"
    else:
        cycle_state = "RUNNING"

    steps = []
    for definition in STEP_DEFINITIONS:
        index = definition["index"]
        details = _step_details(
            index,
            decision=decision,
            strategy=strategy,
            entry_readiness=entry_readiness,
            close_state=close_state,
            stages=stages,
            context=ctx,
            parameter_authority=parameter_authority,
            bot_running=bot_running,
        )
        base = _base_status(index, current_index, not bot_running)

        detail_status = details.get("status")
        if not bot_running:
            effective = StepStatus.NOT_REACHED
        elif detail_status in (StepStatus.ACTIVE, StepStatus.BLOCKED, StepStatus.BYPASSED):
            effective = detail_status
        elif base in (StepStatus.COMPLETED, StepStatus.ACTIVE, StepStatus.BLOCKED):
            effective = detail_status or base
        else:
            effective = base

        dependency_state = None
        root_blocker_step = None
        if bot_running and root_step is not None and index > root_step:
            effective = StepStatus.WAITING
            dependency_state = f"WAITING_FOR_STEP_{root_step}"
            root_blocker_step = root_step

        elif (bot_running and root_step is None and strategy_blocked
              and not current_evaluation and current_index == 4 and index > 4):
            # Preserve the existing entry dependency without promoting the
            # retained suppression reason to a current root blocker.
            effective = StepStatus.WAITING
            dependency_state = "WAITING_FOR_STEP_4"

        if root_step is not None and index == root_step:
            effective = StepStatus.BLOCKED

        if index == 5 and detail_status == StepStatus.BYPASSED:
            effective = StepStatus.BYPASSED
            dependency_state = None
            root_blocker_step = None

        retained = None
        strategy_derived = index in {0, 3, 4}
        if strategy_derived and not current_evaluation:
            retained_details = details if bot_running else _step_details(
                index, decision=decision, strategy=strategy,
                entry_readiness=entry_readiness, close_state=close_state,
                stages=stages, context=ctx, parameter_authority=parameter_authority,
                bot_running=True,
            )
            retained = {**deepcopy(retained_details), **provenance,
                        "freshness": _freshness(evaluated_at, provenance["evaluatedAt"])}
            if index == 4:
                retained["entryReadiness"] = deepcopy(entry_readiness)
                retained["liquidityInstabilityDebug"] = deepcopy(strategy.get("liquidityInstabilityDebug"))
            # Keep the supported feature-contract predicate (STEP 3), but label
            # its evidence provenance. STEP 4 must represent current availability.
            if index == 4 and bot_running:
                effective = StepStatus.WAITING
                details = {
                    "current": _NOT_AVAILABLE, "required": "CURRENT_EVALUATION",
                    "comparison": "NOT_EVALUATED",
                    "reasonCode": "CURRENT_EVALUATION_NOT_ESTABLISHED",
                    "reasonText": "No evaluation is proven to belong to the current cycle.",
                    "blockerType": BlockerType.DATA, "actionable": Actionable.NO,
                    "nextCondition": "CURRENT_EVALUATION", "nextStep": index + 1,
                    "source": SOURCE,
                }
                if runtime_state.get("status") is not None:
                    details["current"] = {
                        "evaluation": _NOT_AVAILABLE,
                        "strategyLoop": runtime_state["status"],
                    }
        source_timestamp = (provenance["evaluatedAt"] if strategy_derived
                            else decision.get("timestamp"))
        freshness = _freshness(evaluated_at, source_timestamp)
        related = details.get("relatedParameters") or []

        step = {
            **definition,
            "status": effective,
            "reasonCode": details.get("reasonCode"),
            "reasonText": details.get("reasonText"),
            "current": details.get("current"),
            "required": details.get("required"),
            "comparison": details.get("comparison"),
            "blockerType": _classify_blocker_type(details.get("blockerType")),
            "actionable": details.get("actionable") or Actionable.UNKNOWN,
            "relatedParameters": deepcopy(related),
            "parameterLocation": _parameter_location(related),
            "nextCondition": details.get("nextCondition"),
            "nextStep": details.get("nextStep"),
            "source": details.get("source"),
            "evaluatedAt": source_timestamp,
            "diagnosticsGeneratedAt": evaluated_at,
            "freshness": freshness,
            "dependencyState": dependency_state,
            "rootBlockerStep": root_blocker_step,
        }
        if strategy_derived:
            step.update(provenance)
            step["valueType"] = details.get("valueType", "UNKNOWN")
        if retained is not None:
            step["retainedEvaluation"] = retained
        if details.get("extra"):
            step["extra"] = deepcopy(details["extra"])
        steps.append(step)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": SOURCE,
        "evaluatedAt": evaluated_at,
        "cycleId": decision.get("cycleId"),
        "diagnosticsGeneratedAt": evaluated_at,
        "evaluationProvenance": provenance,
        "runtimeState": deepcopy(runtime_state),
        "cycleState": cycle_state,
        "rootBlocker": deepcopy(root),
        "rootBlockerStep": root_step,
        "steps": steps,
    }
