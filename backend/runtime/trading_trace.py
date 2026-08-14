"""Paper/live common, decision-scoped trading trace read model.

This module is diagnostic only.  Recorder failures must never change trading
authority or prevent an order from being evaluated.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4


STAGES = (
    "MARKET", "DETECTOR", "FEATURE", "STRATEGY", "AI",
    "MONEY_MANAGEMENT", "GOVERNANCE", "EXECUTION", "POSITION",
    "RESULT", "HISTORY",
)
TERMINAL_CLASSIFICATIONS = {
    "COMPLETE_EXECUTED", "COMPLETE_SUPPRESSED", "COMPLETE_BLOCKED",
    "INCOMPLETE", "FAILED",
}
_SECRET_KEY = re.compile(
    r"(?:api.?key|secret|passphrase|authorization|credential|private.?token|signed.?request)",
    re.IGNORECASE,
)
_MAX_METADATA_BYTES = 8192


def new_trace_id() -> str:
    """Return an opaque, restart-safe correlation identifier."""
    return f"trading-e2e-{uuid4()}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): _clean(item, depth + 1)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_clean(item, depth + 1) for item in value[:100]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sanitize_metadata(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    cleaned = _clean(dict(value or {}))
    encoded = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_METADATA_BYTES:
        return {"truncated": True, "originalBytes": len(encoded.encode("utf-8"))}
    return cleaned


def strategy_decision_snapshot(strategy_state: Mapping[str, Any]) -> dict[str, Any]:
    """Select already-computed Strategy inputs; never re-evaluate a decision."""
    state = dict(strategy_state or {})
    debug = dict(state.get("liquidityInstabilityDebug") or {})
    readiness = dict(state.get("entryReadiness") or {})
    conditions = {
        item.get("code"): item
        for item in readiness.get("conditions", [])
        if isinstance(item, Mapping) and item.get("code")
    }

    def current(code: str) -> Any:
        item = conditions.get(code) or {}
        return item.get("currentValue")

    total_volume = debug.get("totalVolume")
    buy_pressure = debug.get("buyPressure")
    sell_pressure = debug.get("sellPressure")
    pressure_difference = debug.get("pressureDiff")
    if pressure_difference is None and buy_pressure is not None and sell_pressure is not None:
        pressure_difference = abs(float(buy_pressure) - float(sell_pressure))

    parameter_authority = debug.get("parameterAuthority")
    if (
        isinstance(parameter_authority, Mapping)
        and parameter_authority.get("scope") == "PAPER_ONLY"
    ):
        parameter_authority = {
            "schemaVersion": parameter_authority.get("schemaVersion"),
            "calibrationId": parameter_authority.get("calibrationId"),
            "scope": parameter_authority.get("scope"),
            "authority": parameter_authority.get("authority"),
            "parameters": {
                str(name): {
                    "value": item.get("value"),
                    "unit": item.get("unit"),
                }
                for name, item in (
                    parameter_authority.get("parameters") or {}
                ).items()
                if isinstance(item, Mapping)
            },
        }

    return sanitize_metadata({
        "market": {
            "bestBid": debug.get("bestBid"), "bestAsk": debug.get("bestAsk"),
            "midPrice": debug.get("midPrice"), "spread": debug.get("spread"),
            "spreadPct": debug.get("spreadPct"),
        },
        "orderbook": {
            "aggregationDepth": debug.get("orderbookAggregationDepth"),
            "aggregationMode": debug.get("orderbookAggregationMode"),
            "bidDepth": debug.get("strategyBidTotal"),
            "askDepth": debug.get("strategyAskTotal"),
            "totalVolume": total_volume,
        },
        "pressure": {
            "buyPressure": buy_pressure, "sellPressure": sell_pressure,
            "pressureImbalance": pressure_difference,
        },
        "movement": {
            "priceDelta": debug.get("priceDelta"),
            "absPriceDelta": debug.get("absPriceDelta"),
            "priceDeltaPct": debug.get("priceDeltaPct"),
        },
        "liquidity": {"liquidityQuality": current("LIQUIDITY_QUALITY")},
        "detectors": {
            "calibrationReady": debug.get("calibrationReady"),
            "absorptionDetected": debug.get("absorptionDetected"),
            "stagnantHeavyFlow": debug.get("stagnantHeavyFlow"),
            "fakePressureDetected": debug.get("fakePressureDetected"),
            "details": debug.get("detectorDetails"),
        },
        "strategy": {
            "rawCandidate": readiness.get("candidateDirection"),
            "finalDecision": readiness.get("strategyDecision"),
            "confidence": state.get("confidence"), "edge": state.get("edge"),
            "minimumConfidence": state.get("minimumConfidence"),
            "executionAllowed": state.get("executionAllowed"),
            "suppressionReason": state.get("suppressionReason"),
            "momentum": current("MOMENTUM"),
            "momentumDirection": state.get("momentumDirection"),
            "directionPurity": state.get("directionPurity"),
            "activityRatio": state.get("activityRatio"),
            "normalizedMomentum": state.get("normalizedMomentum"),
            "directionAligned": state.get("directionAligned"),
            "normalizedSpreadQuality": state.get("normalizedSpreadQuality"),
            "normalizedLiquidityQuality": state.get(
                "normalizedLiquidityQuality"
            ),
            "hardGateResults": state.get("hardGateResults"),
            "minimumCompositeScore": state.get("minimumCompositeScore"),
            "featureContract": state.get("featureContract"),
            "volatility": current("SPREAD_VOLATILITY"),
        },
        "parameterAuthority": parameter_authority,
    })


@dataclass(frozen=True)
class TraceEvent:
    traceId: str
    eventId: str
    timestamp: str
    mode: str
    stage: str
    status: str
    symbol: Optional[str] = None
    runtimeId: Optional[str] = None
    observationId: Optional[str] = None
    decisionId: Optional[str] = None
    reasonCode: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_event(*, trace_id: str, mode: str, stage: str, status: str,
               symbol: Optional[str] = None, runtime_id: Optional[str] = None,
               observation_id: Optional[str] = None,
               decision_id: Optional[str] = None,
               reason_code: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None,
               timestamp: Optional[str] = None) -> TraceEvent:
    normalized_mode = str(mode).upper()
    normalized_stage = str(stage).upper()
    if normalized_mode not in {"PAPER", "LIVE"}:
        raise ValueError("trace mode must be PAPER or LIVE")
    if normalized_stage not in STAGES:
        raise ValueError(f"unknown trace stage: {stage}")
    if not str(trace_id).startswith("trading-e2e-"):
        raise ValueError("invalid traceId")
    return TraceEvent(
        traceId=str(trace_id), eventId=f"trace-event-{uuid4()}",
        timestamp=timestamp or _utc_now(), mode=normalized_mode,
        stage=normalized_stage, status=str(status).upper(), symbol=symbol,
        runtimeId=runtime_id, observationId=observation_id,
        decisionId=decision_id, reasonCode=reason_code,
        metadata=sanitize_metadata(metadata),
    )


def classify_trace(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = list(events)
    if not ordered:
        return {"classification": "INCOMPLETE", "failurePoint": "STRATEGY", "primaryReason": "NO_EVENTS"}
    failed = next((e for e in ordered if e.get("status") in {"FAILED", "REJECTED", "ERROR"}), None)
    if failed:
        return {"classification": "FAILED", "failurePoint": failed.get("stage"), "primaryReason": failed.get("reasonCode")}
    terminal = next((e for e in reversed(ordered) if e.get("stage") == "RESULT"), None)
    if terminal:
        status = terminal.get("status")
        classification = {
            "EXECUTED": "COMPLETE_EXECUTED", "CLOSED": "COMPLETE_EXECUTED",
            "SUPPRESSED": "COMPLETE_SUPPRESSED", "BLOCKED": "COMPLETE_BLOCKED",
        }.get(status)
        if classification:
            return {"classification": classification, "failurePoint": None, "primaryReason": terminal.get("reasonCode")}

    by_stage = {e.get("stage"): e for e in ordered}
    strategy = by_stage.get("STRATEGY")
    if not strategy:
        missing = "STRATEGY"
    elif strategy.get("status") in {"HOLD", "SUPPRESSED"}:
        missing = "STRATEGY → RESULT"
    elif by_stage.get("AI", {}).get("status") in {"HOLD", "SUPPRESSED"}:
        missing = "AI → RESULT"
    elif by_stage.get("MONEY_MANAGEMENT", {}).get("status") == "BLOCKED":
        missing = "MONEY_MANAGEMENT → RESULT"
    elif by_stage.get("GOVERNANCE", {}).get("status") == "BLOCKED":
        missing = "GOVERNANCE → RESULT"
    elif by_stage.get("GOVERNANCE", {}).get("status") in {"ALLOW", "ALLOWED"} and "EXECUTION" not in by_stage:
        missing = "GOVERNANCE → EXECUTION"
    elif "EXECUTION" in by_stage and "POSITION" not in by_stage and by_stage["EXECUTION"].get("status") in {"FILLED", "PAPER_FILLED"}:
        missing = "EXECUTION → POSITION"
    else:
        missing = f"{ordered[-1].get('stage')} → RESULT"
    return {"classification": "INCOMPLETE", "failurePoint": missing, "primaryReason": "EXPECTED_STAGE_MISSING"}


class TradingTraceStore:
    def __init__(self, jsonl_path: Optional[Path] = None, max_events: int = 10000):
        self._events: list[dict[str, Any]] = []
        self._lock = RLock()
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self.max_events = max_events
        self.persistence_errors = 0

    def record(self, event: TraceEvent) -> None:
        payload = event.to_dict()
        with self._lock:
            self._events.append(payload)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]
        if self.jsonl_path:
            try:
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with self.jsonl_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            except (OSError, TypeError, ValueError):
                self.persistence_errors += 1

    def events(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._events if e["traceId"] == trace_id]

    def trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        events = self.events(trace_id)
        if not events:
            return None
        result = classify_trace(events)
        first, last = events[0], events[-1]
        result_event = next((e for e in reversed(events) if e["stage"] == "RESULT"), {})
        execution = next((e for e in reversed(events) if e["stage"] == "EXECUTION"), {})
        ids = {}
        for event in events:
            for key in ("runtimeId", "observationId", "decisionId"):
                ids[key] = event.get(key) or ids.get(key)
            for key in ("rankingCycleId", "orderId", "exchangeOrderId", "positionId", "markerId"):
                ids[key] = event.get("metadata", {}).get(key) or ids.get(key)
        return {
            "traceId": trace_id, "mode": first["mode"], "symbol": first.get("symbol"),
            "startedAt": first["timestamp"], "updatedAt": last["timestamp"],
            "finalDecision": result_event.get("metadata", {}).get("decision") or first.get("metadata", {}).get("decision"),
            "finalStatus": result["classification"], "primaryReason": result["primaryReason"],
            "failurePoint": result["failurePoint"], "executionStatus": execution.get("status"),
            "netPnL": result_event.get("metadata", {}).get("netPnL"),
            **ids, "events": events,
        }

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(dict.fromkeys(e["traceId"] for e in reversed(self._events)))[:max(1, min(limit, 200))]
        return [trace for trace_id in ids if (trace := self.trace(trace_id))]

    def session(self, *, mode: Optional[str] = None, runtime_id: Optional[str] = None) -> dict[str, Any]:
        traces = self.recent(200)
        if mode:
            traces = [t for t in traces if t["mode"] == mode.upper()]
        if runtime_id:
            traces = [t for t in traces if t.get("runtimeId") == runtime_id]
        classifications = Counter(t["finalStatus"] for t in traces)
        reasons = Counter(t["primaryReason"] for t in traces if t.get("primaryReason"))
        events = [event for trace in traces for event in trace["events"]]
        return {
            "tradingAiMode": "OFF",
            "tradingAiStatus": "NOT_INSTALLED",
            "tradingAiRequired": False,
            "observedDecisions": len(traces),
            "strategy": dict(Counter(e["status"] for e in events if e["stage"] == "STRATEGY")),
            "ai": dict(Counter(e["status"] for e in events if e["stage"] == "AI")),
            "moneyManagement": dict(Counter(e["status"] for e in events if e["stage"] == "MONEY_MANAGEMENT")),
            "governance": dict(Counter(e["status"] for e in events if e["stage"] == "GOVERNANCE")),
            "executionAttempted": sum(e["stage"] == "EXECUTION" for e in events),
            "executedTrades": classifications["COMPLETE_EXECUTED"],
            "completeTraces": sum(v for k, v in classifications.items() if k.startswith("COMPLETE_")),
            "incompleteTraces": classifications["INCOMPLETE"], "failedTraces": classifications["FAILED"],
            "classificationCounts": dict(classifications), "primaryBlockReasonCounts": dict(reasons),
        }


trace_store = TradingTraceStore(Path(os.environ.get(
    "TRADING_E2E_TRACE_PATH", "logs/runtime/trading_e2e_trace.jsonl"
)))


def safe_record(**kwargs: Any) -> Optional[TraceEvent]:
    """Best-effort boundary: tracing cannot affect the trading path."""
    try:
        event = make_event(**kwargs)
        trace_store.record(event)
        return event
    except Exception:
        trace_store.persistence_errors += 1
        return None
