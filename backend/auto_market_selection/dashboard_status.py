"""AMS-2D deterministic, read-only Dashboard status projection."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Mapping


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _value(source, key, default=None):
    value = source.get(key, default)
    return deepcopy(value)


def build_auto_market_selection_status(
    *, active_symbol=None, selection_mode="MANUAL", requested_symbol=None,
    audit_event=None, proposal=None, switch_result=None, cycle=None, lifecycle=None,
    live_observation=None, live_auto_runtime=None, live_account_authority=None,
    capital_eligibility=None, production_integration=None,
):
    audit = _mapping(audit_event.to_dict() if hasattr(audit_event, "to_dict") else audit_event)
    proposal_data = _mapping(proposal.to_dict() if hasattr(proposal, "to_dict") else proposal)
    switch = _mapping(switch_result.to_dict() if hasattr(switch_result, "to_dict") else switch_result)
    cycle_data = _mapping(cycle.to_dict() if hasattr(cycle, "to_dict") else cycle)
    lifecycle_data = _mapping(lifecycle)
    live_data = _mapping(
        live_observation.to_dict() if hasattr(live_observation, "to_dict")
        else live_observation
    )
    live_auto_data = _mapping(live_auto_runtime)
    account_data = _mapping(live_account_authority)
    integration_data = _mapping(production_integration)
    scanner = _mapping(audit.get("scannerSummary"))
    ranking = _mapping(audit.get("rankingSummary"))
    capital = _mapping(audit.get("capitalSnapshot")) or _mapping(capital_eligibility)
    universe = _mapping(audit.get("universeSummary"))
    top = _mapping(audit.get("topCandidate"))
    candidates = audit.get("candidates") if isinstance(audit.get("candidates"), list) else []
    top_entry = next((item for item in candidates
                      if isinstance(item, Mapping) and item.get("rank") == 1), {})
    features = _mapping(top_entry.get("rankingFeatures"))
    timestamps = _mapping(audit.get("timestamps"))
    live_auto = deepcopy(live_auto_data)
    candidate_score = live_data.get("candidateScore") or live_data.get("topScore")
    active_market_score = live_data.get("activeMarketScore")
    live_auto.setdefault("candidateScore", candidate_score)
    live_auto.setdefault("activeMarketScore", active_market_score)
    live_auto.setdefault("rankingCycleId", live_data.get("rankingCycleId"))
    live_auto.setdefault("observationId", live_data.get("observationId"))
    live_auto.setdefault("rankingEvaluatedAt", live_data.get("rankingEvaluatedAt"))
    if live_auto.get("scoreAdvantage") is None:
        try:
            live_auto["scoreAdvantage"] = format(
                Decimal(candidate_score) - Decimal(active_market_score), "f"
            )
        except (InvalidOperation, TypeError, ValueError):
            live_auto["scoreAdvantage"] = None

    scanner_status = scanner.get("scannerStatus") or (
        "COMPLETED" if live_data.get("scannerCycleId") else "UNAVAILABLE"
    )
    ranking_status = ranking.get("rankingStatus") or (
        "COMPLETED" if live_data.get("rankingCycleId") else "UNAVAILABLE"
    )
    capital_available = bool(capital)
    capital_eligible = (
        "ELIGIBLE" if capital.get("executionEntryAllowed") is True
        and capital.get("authorityFresh") is True
        and capital.get("remainingPositionCapacity") not in (None, 0)
        else "BLOCKED" if capital_available else "UNAVAILABLE"
    )
    reasons = []
    for source in (
        proposal_data.get("reasonCodes"), scanner.get("globalRejectionReasons"),
        top_entry.get("capitalReasonCodes"), top_entry.get("rankingReasonCodes"),
        switch.get("reasonCodes"),
    ):
        if isinstance(source, (list, tuple)):
            reasons.extend(str(item) for item in source if item)
    reasons = list(dict.fromkeys(reasons))

    return {
        "selectionMode": str(selection_mode or "MANUAL").upper(),
        "activeSymbol": str(active_symbol).upper() if active_symbol else None,
        "requestedSymbol": str(requested_symbol).upper() if requested_symbol else None,
        "autoRuntime": {
            "mode": live_data.get("mode") or lifecycle_data.get("amsMode") or cycle_data.get("mode") or "MANUAL",
            "runtimeState": "OBSERVING" if live_data else lifecycle_data.get("amsRuntimeState") or "STOPPED",
            "cycleId": cycle_data.get("autoSelectionCycleId"),
            "status": cycle_data.get("status") or "IDLE",
            "currentActiveSymbol": cycle_data.get("currentActiveSymbol"),
            "topCandidateSymbol": cycle_data.get("topCandidateSymbol"),
            "proposedSymbol": cycle_data.get("proposedSymbol"),
            "finalActiveSymbol": cycle_data.get("finalActiveSymbol"),
            "evaluatedAt": cycle_data.get("evaluatedAt"),
            "reasonCodes": deepcopy(
                lifecycle_data.get("reasonCodes") or cycle_data.get("reasonCodes") or []
            ),
            "lastCycleId": lifecycle_data.get("lastCycleId"),
            "lastCycleStatus": lifecycle_data.get("lastCycleStatus"),
        },
        "liveReadOnly": deepcopy(live_data) if live_data else None,
        "liveAuto": live_auto,
        "productionIntegration": deepcopy(integration_data),
        "liveAccountAuthority": deepcopy(account_data) if account_data else None,
        "scanner": {
            "status": scanner_status,
            "universeCount": _value(universe, "universeCount", live_data.get("universeCount")),
            "evaluatedCount": _value(scanner, "evaluatedCount", live_data.get("evaluatedCount")),
            "eligibleCount": _value(scanner, "eligibleCount", live_data.get("eligibleCount")),
            "rejectedCount": _value(scanner, "rejectedCount", live_data.get("rejectedCount")),
            "evaluatedAt": _value(timestamps, "scannerEvaluatedAt", live_data.get("timestamp")),
        },
        "ranking": {
            "status": ranking_status,
            "rankedCount": _value(ranking, "rankedCandidateCount", len(live_data.get("rankedCandidates") or [])),
            "evaluatedAt": _value(timestamps, "rankingEvaluatedAt", live_data.get("rankingEvaluatedAt")),
        },
        "topCandidate": {
            "symbol": top.get("symbol") or live_data.get("topCandidate"),
            "score": top.get("score") or live_data.get("topScore"),
            "rank": top.get("rank"),
            "spreadScore": features.get("spreadScore"),
            "liquidityScore": features.get("liquidityScore"),
            "activityScore": features.get("activityScore"),
        },
        "capitalEligibility": {
            "status": capital_eligible,
            "availableCapital": capital.get("availableCapital"),
            "riskBudget": capital.get("riskBudget"),
            "remainingExposure": capital.get("remainingExposure"),
            "remainingPositionCapacity": capital.get("remainingPositionCapacity"),
            "mmRegime": capital.get("mmRegime"),
            "evaluatedAt": capital.get("evaluatedAt"),
            "capitalAuthority": capital.get("capitalAuthority"),
            "capitalSource": capital.get("capitalSource"),
            "inputAuthority": capital.get("inputAuthority"),
            "authorityFresh": capital.get("authorityFresh"),
        },
        "switch": {
            "state": switch.get("state") or "IDLE",
            "transactionId": switch.get("switchTransactionId"),
            "previousSymbol": switch.get("previousSymbol"),
            "proposedSymbol": switch.get("proposedSymbol"),
            "committedSymbol": switch.get("committedSymbol"),
            "entryPaused": switch.get("entryPaused"),
            "reasonCodes": deepcopy(switch.get("reasonCodes") or []),
        },
        "reasons": reasons,
        "freshness": {
            "universe": "FRESH" if live_data.get("universeEvaluatedAt")
            else "FRESH" if universe.get("universeFresh") is True
            else "STALE" if universe.get("universeFresh") is False else "UNKNOWN",
            "scanner": "FRESH" if scanner_status != "UNAVAILABLE"
            and (timestamps.get("scannerEvaluatedAt") or live_data.get("timestamp"))
            else "UNKNOWN",
            "ranking": "FRESH" if ranking_status != "UNAVAILABLE"
            and (timestamps.get("rankingEvaluatedAt")
                 or live_data.get("rankingEvaluatedAt")) else "UNKNOWN",
            "mm": "FRESH" if capital.get("authorityFresh") is True
            else "STALE" if capital.get("authorityFresh") is False else "UNKNOWN",
        },
        "readOnly": True,
    }
